import asyncio
import re
import time as _time
from collections import Counter
from datetime import date, timedelta, datetime

import logging

import httpx
from fastapi import APIRouter, Depends, Query

from app.auth import require_b2b
from app.config import (
    NAVER_HEADERS, NAVER_SHOP_URL, NAVER_DATALAB_URL,
    _CATEGORY_MAP, _POS_WORDS, _NEG_WORDS, _STOP,
    B2B_SHOPPING_DISPLAY, B2B_RAG_CHUNK_LEN, B2B_CI_MULTIPLIER,
    GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL, GROQ_CACHE_TTL,
    YOUTUBE_API_KEY, YOUTUBE_SEARCH_URL,
)
from app.utils.helpers import strip_html, extract_model_number, fmt_price_label
from app.routers.naver import search_products

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/b2b", tags=["b2b"])

# ── 공통 상수 (config.py에서 가져옴) ──
_SHOPPING_DISPLAY = B2B_SHOPPING_DISPLAY
_RAG_CHUNK_LEN    = B2B_RAG_CHUNK_LEN
_CI_MULTIPLIER    = B2B_CI_MULTIPLIER

def _calc_risk(growth: float) -> str:
    """성장률 기반 시장 위험도 산출 (두 엔드포인트 공통)"""
    return "낮음" if growth > -15 else ("중간" if growth > -30 else "높음")

_GROQ_MODELS = (GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL)
_GROQ_CACHE: dict = {}
_GROQ_TTL   = GROQ_CACHE_TTL
_CACHE_VER  = "v3"  # bump when prompt schema changes

# 일일 토큰 한도 감지 플래그 — 서버 재시작(다음날) 전까지 Groq 호출 건너뜀
_GROQ_DAILY_LIMIT: bool = False

import os as _os
from groq import AsyncGroq as _AsyncGroq
_groq_singleton: _AsyncGroq | None = None

def _get_groq_client() -> _AsyncGroq:
    global _groq_singleton
    if _groq_singleton is None:
        _groq_singleton = _AsyncGroq(api_key=_os.getenv("GROQ_API_KEY"))
    return _groq_singleton

async def _groq_create(messages: list, max_tokens: int = 600, temperature: float = 0.3):
    """RateLimitError 시 fallback 모델로 자동 재시도. 일일 한도 소진 시 즉시 예외."""
    global _GROQ_DAILY_LIMIT
    from groq import RateLimitError
    if _GROQ_DAILY_LIMIT:
        raise RuntimeError("Groq 일일 토큰 한도 소진 (서버 재시작 전까지 LLM 호출 중단)")
    client = _get_groq_client()
    for i, model in enumerate(_GROQ_MODELS):
        try:
            return await client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
        except RateLimitError as e:
            print("★★★★★★★★")
            print(e)
            print("★★★★★★★★")
            if "tokens per day" in str(e).lower() or "tpd" in str(e).lower():
                _GROQ_DAILY_LIMIT = True
                logger.warning("[Groq] 일일 토큰 한도 소진 — LLM 호출 중단")
                raise
            if i < len(_GROQ_MODELS) - 1:
                continue
            raise


def _has_non_korean_cjk(text: str) -> bool:
    """일본어(히라가나·가타카나) 또는 중국어(한자) 포함 여부 반환"""
    for ch in text:
        cp = ord(ch)
        # 히라가나: 3041-3096, 가타카나: 30A1-30F6, 반각가타카나: FF66-FF9F
        # CJK 통합한자: 4E00-9FFF, 확장A: 3400-4DBF
        if (0x3041 <= cp <= 0x3096 or 0x30A1 <= cp <= 0x30F6
                or 0xFF66 <= cp <= 0xFF9F
                or 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF):
            return True
    return False


@router.post("/cache/clear")
async def clear_b2b_cache(_: dict = Depends(require_b2b)):
    _GROQ_CACHE.clear()
    return {"ok": True, "message": "캐시 초기화 완료"}

@router.get("/dashboard")
async def get_b2b_dashboard(category: str = Query(..., min_length=1), period: str = "3m", _: dict = Depends(require_b2b)):
    from app.dependencies import get_rag_optional

    _ck = f"dashboard:{_CACHE_VER}:{category}:{period}"
    _cached = _GROQ_CACHE.get(_ck)
    if _cached and _time.time() < _cached[0]:
        cached_result = _cached[1]
        # complaints는 별도 캐시에서 항상 최신값 주입
        _cc = _GROQ_CACHE.get(f"complaints:{category}")
        if _cc and _time.time() < _cc[0] and _cc[1]:
            cached_result = {**cached_result, "complaints": _cc[1]}
        return cached_result

    rag = get_rag_optional()

    days_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    days = days_map.get(period, 90)
    time_unit = "week" if days > 30 else "date"
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dl_headers = {**NAVER_HEADERS, "Content-Type": "application/json"}

    async def fetch_trend():
        body = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate":   end_date.strftime("%Y-%m-%d"),
            "timeUnit":  time_unit,
            "keywordGroups": [{"groupName": category, "keywords": [category]}],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://openapi.naver.com/v1/datalab/search", json=body, headers=dl_headers)
        payload = resp.json()
        if "errorCode" in payload:
            logger.warning("DataLab trend 오류 [%s]: %s — %s", category, payload.get("errorCode"), payload.get("errorMessage"))
            return []
        results = payload.get("results", [])
        return results[0]["data"] if results else []

    async def fetch_brand_share():
        # search_products는 brand/maker를 합쳐버리므로 직접 호출
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://openapi.naver.com/v1/search/shop.json",
                headers=NAVER_HEADERS,
                params={"query": category, "display": 100, "sort": "sim"},
            )
        items = resp.json().get("items", [])
        counts: dict[str, int] = {}
        for it in items:
            # maker(제조사) 우선, 없으면 brand
            key = it.get("maker", "").strip() or it.get("brand", "").strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:6]
        total = sum(v for _, v in top)
        return [{"brand": k, "count": v, "pct": round(v / total * 100) if total else 0} for k, v in top]

    async def fetch_age(age_codes_list: list[str]) -> float:
        body = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate":   end_date.strftime("%Y-%m-%d"),
            "timeUnit":  "month",
            "keywordGroups": [{"groupName": category, "keywords": [category]}],
            "ages": age_codes_list,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://openapi.naver.com/v1/datalab/search", json=body, headers=dl_headers)
        payload = resp.json()
        if "errorCode" in payload:
            logger.warning("DataLab age 오류 [%s/%s]: %s — %s", category, age_codes_list, payload.get("errorCode"), payload.get("errorMessage"))
            return 0.0
        results = payload.get("results", [])
        data = results[0]["data"] if results else []
        return sum(d["ratio"] for d in data) / len(data) if data else 0.0

    async def fetch_keywords():
        raw = await search_products(query=category, page=1, display=30, sort="sim", category=category)
        items = raw.get("items", [])

        KW_STOP = _STOP | {
            "미포함", "포함", "수도권", "설치비포함", "설치비별도", "방문설치",
            "무료설치", "무료", "별도", "이하", "이상", "할인", "택배", "직접",
            "기사", "배송", "셀프", "자가설치", "원룸", "평", "인치",
        }
        # 순수 영문 2~4자 토큰(모델코드)은 제외
        def is_valid(w: str) -> bool:
            w = w.strip()
            if not w or len(w) < 2 or w == category or w in KW_STOP:
                return False
            if re.match(r'^[A-Za-z]{1,4}$', w):   # 짧은 영문 코드 제외
                return False
            if any(c.isdigit() for c in w):         # 숫자 포함 제외
                return False
            return True

        # 단어별 등장 제품 예시 수집
        word_counts: Counter = Counter()
        word_examples: dict[str, list[str]] = {}

        def record(w: str, title: str):
            if not is_valid(w):
                return
            word_counts[w] += 1
            if w not in word_examples:
                word_examples[w] = []
            if len(word_examples[w]) < 3:
                short = strip_html(title)[:30]
                if short not in word_examples[w]:
                    word_examples[w].append(short)

        for it in items:
            t = strip_html(it.get("title", ""))
            record(it.get("brand") or "", t)
            record(it.get("maker") or "", t)
            record(it.get("category3") or "", t)
            record(it.get("category4") or "", t)
            for tok in re.sub(r'[^가-힣a-zA-Z\s]', ' ', t).split():
                record(tok, t)

        top = word_counts.most_common(20)
        return [
            {"word": w, "count": c, "examples": word_examples.get(w, [])}
            for w, c in top
        ]

    age_groups = [["2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10", "11"]]
    age_labels = ["10대", "20대", "30대", "40대", "50대+"]

    async def fetch_complaints():
        _KW_STOP = {
            category, "제품", "구매", "사용", "배송", "설치", "가격", "서비스",
            "이번", "이후", "경우", "정도", "때문", "생각", "느낌", "부분",
            "것이", "수있", "있는", "없는", "같은", "하는", "되는", "이런",
            "저희", "우리", "모두", "정말", "너무", "매우", "조금", "약간",
            "그냥", "아직", "계속", "바로", "항상", "다시", "처음", "이미",
        }
        _POS_SENTENCE = ["없", "작아", "적어", "좋아", "좋은", "만족", "괜찮", "추천", "최고", "훌륭", "완벽", "조용"]

        # Step1: 쇼핑 API 직접 호출 (maker 필드 포함)
        async with httpx.AsyncClient(timeout=8.0) as client:
            shop_resp = await client.get(
                "https://openapi.naver.com/v1/search/shop.json",
                headers=NAVER_HEADERS,
                params={"query": category, "display": 10, "sort": "sim"},
            )
        raw_items = shop_resp.json().get("items", [])[:10]
        if not raw_items:
            logger.warning("[complaints] 쇼핑 결과 없음")
            return []

        products = [
            {
                "title": strip_html(it.get("title", "")),
                "brand": it.get("brand", "").strip(),
                "maker": it.get("maker", "").strip(),
                "price": int(it.get("lprice") or 0),
            }
            for it in raw_items
        ]

        # Step2: maker 기준 중복 제거
        seen_makers: dict[str, bool] = {}
        for p in products:
            key = p["maker"] or p["brand"] or category
            seen_makers[key] = True

        async def search_maker_complaint(maker: str) -> dict:
            articles: list[dict] = []
            all_text = ""
            naver_queries = [
                ("https://openapi.naver.com/v1/search/blog.json",        f"{maker} {category} 단점 아쉬운점"),
                ("https://openapi.naver.com/v1/search/cafearticle.json",  f"{maker} {category} 후기 불편"),
                ("https://openapi.naver.com/v1/search/news.json",         f"{maker} {category} 결함 불만"),
            ]
            async with httpx.AsyncClient(timeout=8.0) as client:
                for url, q in naver_queries:
                    try:
                        resp = await client.get(
                            url, headers=NAVER_HEADERS,
                            params={"query": q, "display": 6, "sort": "date"},
                        )
                        if "blog" in url:       src = "블로그"
                        elif "cafe" in url:     src = "카페"
                        else:                   src = "뉴스"
                        for item in resp.json().get("items", []):
                            title = strip_html(item.get("title", ""))
                            desc  = strip_html(item.get("description", ""))
                            all_text += " " + title + " " + desc
                            articles.append({
                                "title":       title,
                                "description": desc,
                                "link":        item.get("originallink") or item.get("link", ""),
                                "pubDate":     item.get("pubDate", "")[:10],
                                "source":      src,
                            })
                    except Exception as e:
                        logger.warning(f"[complaints] Naver 검색 실패 q={q}: {e}")

                # YouTube 리뷰 영상
                if YOUTUBE_API_KEY:
                    try:
                        yt_resp = await client.get(
                            YOUTUBE_SEARCH_URL,
                            params={
                                "part": "snippet", "type": "video",
                                "q": f"{maker} {category} 리뷰 단점",
                                "maxResults": 4,
                                "relevanceLanguage": "ko",
                                "key": YOUTUBE_API_KEY,
                            },
                            timeout=6.0,
                        )
                        for item in yt_resp.json().get("items", []):
                            vid   = item["id"].get("videoId", "")
                            snip  = item.get("snippet", {})
                            title = snip.get("title", "")
                            desc  = snip.get("description", "")[:120]
                            all_text += " " + title + " " + desc
                            articles.append({
                                "title":       title,
                                "description": desc or "YouTube 리뷰 영상",
                                "link":        f"https://www.youtube.com/watch?v={vid}",
                                "pubDate":     snip.get("publishedAt", "")[:10],
                                "source":      "YouTube",
                                "thumbnail":   snip.get("thumbnails", {}).get("default", {}).get("url", ""),
                                "channel":     snip.get("channelTitle", ""),
                            })
                    except Exception as e:
                        logger.warning(f"[complaints] YouTube 검색 실패: {e}")

            import json as _json

            # ── 1. 부정 문장만 필터 ──────────────────────────────────
            _NEG_MARKERS = [
                '단점', '불만', '아쉬', '불편', '문제', '고장', '결함', '냄새',
                '소음', '발열', '느린', '비싸', '무거', '오작동', '기스', '파손',
                '오래', '안됨', '안돼', '이상', '실망', '후회', '별로', '최악',
                '시끄럽', '덥다', '뜨겁', '느리다', '무겁다', '비싸다',
            ]
            _POS_SENTENCES = ['장점', '좋은점', '강추합니다', '추천합니다', '만족합니다', '최고입니다']
            sentences = re.split(r'[.!?\n。]', all_text)
            neg_sentences = [
                s.strip() for s in sentences
                if any(m in s for m in _NEG_MARKERS)
                and not any(p in s for p in _POS_SENTENCES)
                and 5 < len(s.strip()) < 200
            ]
            neg_text = '. '.join(neg_sentences[:50]) if len(neg_sentences) >= 3 else all_text
            sample = neg_text[:2500]

            # ── 2. Groq: 구조화된 키워드+근거 추출 ─────────────────────
            _POS_FILTER = {
                '좋음', '좋은', '최고', '추천', '만족', '훌륭', '완벽', '탁월', '빠름',
                '조용', '조용함', '강추', '성능', '편리', '편리함', '깔끔', '쾌적',
                '우수', '뛰어남', '탁월함', '우수함',
            }
            _POS_CONTAINS = ['좋', '추천', '만족', '최고', '훌륭', '완벽', '우수', '뛰어']

            tags: list[str] = []
            tag_evidence: dict[str, str] = {}   # 키워드 → 근거 문장

            if all_text.strip():
                try:
                    resp = await _groq_create(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "당신은 한국 소비자 불만 분석 전문가입니다. "
                                    "반드시 부정적 키워드(결함·불편·단점)만 추출하고 "
                                    "긍정적·중립적 단어는 절대 포함하지 마세요."
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"아래는 '{maker} {category}' 소비자 불만 텍스트입니다.\n\n"
                                    f"[추출 규칙]\n"
                                    f"1. 실제 불만/결함/단점 키워드만 (예: 소음, 발열, 누수, 냄새, 고장)\n"
                                    f"2. 브랜드명·모델명·일반 명사 제외\n"
                                    f"3. 좋음·추천·만족·성능 같은 긍정 단어 절대 금지\n"
                                    f"4. 최대 7개, 자주 등장한 순서대로\n\n"
                                    f"[출력 형식] JSON만 (설명 없이):\n"
                                    f"{{\"keywords\": [\"소음\", \"발열\"], "
                                    f"\"evidence\": {{\"소음\": \"실외기 진동과 작동 소음이 크다는 의견이 여러 후기에서 반복적으로 나타났습니다.\", "
                                    f"\"발열\": \"장시간 사용 시 본체 상단부에 과열 현상이 발생한다는 보고가 다수 확인되었습니다.\"}}}}\n\n"
                                    f"[근거 문장 작성 규칙]\n"
                                    f"- 최소 20자 이상의 완전한 문장으로 작성\n"
                                    f"- '~한다는 의견이 반복적으로 나타났습니다', '~는 보고가 다수 확인되었습니다' 형식 사용\n"
                                    f"- 단순 형용사(불편합니다, 아쉽습니다)만 쓰지 말고 구체적 현상을 포함\n\n"
                                    f"[텍스트]\n{sample}"
                                ),
                            },
                        ],
                        max_tokens=200,
                        temperature=0.0,
                    )
                    raw = resp.choices[0].message.content.strip()
                    # JSON 파싱
                    start, end = raw.find('{'), raw.rfind('}')
                    if start != -1 and end > start:
                        parsed = _json.loads(raw[start:end+1])
                        kws = parsed.get("keywords", [])
                        evid = parsed.get("evidence", {})
                        tags = [
                            t for t in kws
                            if isinstance(t, str) and 2 <= len(t) <= 10
                            and t not in _POS_FILTER
                            and not any(p in t for p in _POS_CONTAINS)
                        ][:7]
                        tag_evidence = {t: evid.get(t, "") for t in tags}
                except Exception as e:
                    logger.warning(f"[complaints] Groq 추출 실패: {e}")
                    # JSON 실패 시 단순 정규식 fallback
                    raw_fb = ""
                    try:
                        raw_fb = resp.choices[0].message.content.strip()
                    except Exception:
                        pass
                    parsed_fb = re.findall(r'"([가-힣]{2,6})"', raw_fb)
                    tags = [t for t in parsed_fb if t not in _POS_FILTER][:7]

            # ── 3. 교차 검증: 여러 기사에 등장한 키워드 우선 ─────────────
            if tags:
                def article_count(t):
                    return sum(1 for a in articles if t in a["title"] + " " + a["description"])
                counts = {t: article_count(t) for t in tags}
                # 1개 기사에만 등장한 키워드는 신뢰도 낮음 → 뒤로 밀기
                tags = sorted(tags, key=lambda t: counts.get(t, 0), reverse=True)

            logger.info(f"[complaints] maker={maker} tags={tags} articles={len(articles)}")

            # ── 4. 소스: 각 태그 언급 기사 우선 정렬 ─────────────────────
            def source_score(a):
                text = a["title"] + " " + a["description"]
                return sum(1 for t in tags if t in text)

            scored = sorted(articles, key=source_score, reverse=True)
            sources = [a for a in scored if source_score(a) > 0] or articles
            return {
                "tags": tags,
                "evidence": tag_evidence,   # 키워드 → 근거 문장
                "sources": sources[:8],
            }

        maker_list = list(seen_makers.keys())
        maker_results = await asyncio.gather(
            *[search_maker_complaint(m) for m in maker_list],
            return_exceptions=True,
        )
        maker_complaints: dict[str, dict] = {
            m: (r if not isinstance(r, Exception) else {"tags": [], "sources": []})
            for m, r in zip(maker_list, maker_results)
        }

        # Step3: 제품별 결과 조립
        result = []
        for i, p in enumerate(products):
            key  = p["maker"] or p["brand"] or category
            data = maker_complaints.get(key, {"tags": [], "sources": [], "evidence": {}})
            result.append({
                "rank":      i + 1,
                "product":   p["title"][:24],
                "brand":     p["brand"] or p["maker"],
                "price":     p["price"],
                "complaint": data["tags"],
                "evidence":  data.get("evidence", {}),
                "sources":   data["sources"],
            })
        return result

    results = await asyncio.gather(
        fetch_trend(),
        fetch_brand_share(),
        *[fetch_age(g) for g in age_groups],
        fetch_keywords(),
        fetch_complaints(),
        return_exceptions=True,
    )

    trend_data = results[0] if not isinstance(results[0], Exception) else []
    brand_data = results[1] if not isinstance(results[1], Exception) else []
    age_raw    = [r if not isinstance(r, Exception) else 0.0 for r in results[2:7]]
    keywords   = results[7] if not isinstance(results[7], Exception) else []
    complaints = results[8] if not isinstance(results[8], Exception) else []

    # DataLab 최신 주 미집계 trailing 저비율 데이터 제거
    while len(trend_data) > 4 and trend_data[-1]["ratio"] < trend_data[-2]["ratio"] * 0.3:
        trend_data = trend_data[:-1]

    age_total = sum(age_raw)
    age_dist = [
        {"label": lbl, "value": round(v, 1), "pct": round(v / age_total * 100) if age_total else 0}
        for lbl, v in zip(age_labels, age_raw)
    ]

    ratios   = [d["ratio"] for d in trend_data]
    current  = round(ratios[-1], 1) if ratios else 0
    avg_val  = round(sum(ratios) / len(ratios), 1) if ratios else 0
    half     = len(ratios) // 2
    old_avg  = sum(ratios[:half]) / max(half, 1)
    new_avg  = sum(ratios[half:]) / max(len(ratios) - half, 1)
    growth   = round((new_avg - old_avg) / max(old_avg, 1) * 100, 1)
    risk     = _calc_risk(growth)

    summary   = f"{category} 시장의 최근 {period} 트렌드 데이터를 분석한 결과입니다."
    groq_err  = None
    try:
        top3 = ", ".join(f"{b['brand']} {b['pct']}%" for b in brand_data[:3]) or "데이터 부족"
        top_age = max(age_dist, key=lambda x: x["value"])["label"] if age_dist else "30대"

        rag_context = ""
        if rag:
            chunks = await rag.query(f"{category} 소비자 반응 트렌드 구매 후기", n_results=6)
            if chunks:
                rag_context = "\n[소비자 실반응 데이터]\n" + "\n".join(f"- {c[:_RAG_CHUNK_LEN]}" for c in chunks)

        prompt = (
            f"[{category} 시장 B2B 분석 데이터]\n"
            f"- 검색 관심도: 현재 {current} / 기간 평균 {avg_val}\n"
            f"- {period} 성장률: {'+' if growth >= 0 else ''}{growth}%\n"
            f"- 주요 브랜드: {top3}\n"
            f"- 주 관심층: {top_age}\n"
            f"{rag_context}\n\n"
            f"위 데이터를 바탕으로 아래 JSON 구조로만 출력하세요 (설명·마크다운 없이):\n"
            f'{{\n'
            f'  "growth_potential": "높음 | 보통 | 낮음 중 하나",\n'
            f'  "competition_factors": ["경쟁 요인 1", "경쟁 요인 2", "경쟁 요인 3"],\n'
            f'  "risk_factors": ["주의 요소 1", "주의 요소 2"],\n'
            f'  "conclusion": "{category} 시장에 대한 2~3문장 종합 판단. 투자·추천 표현 금지. ~할 것으로 판단됩니다 / ~가능성이 있습니다 어조 사용."\n'
            f'}}'
        )
        res = await _groq_create(
            messages=[
                {"role": "system", "content": "당신은 B2B 가전 시장 분석 전문가입니다. 기업 보고서 형식의 객관적 어조로 분석하세요. 순수 JSON만 출력하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        import json as _json_mr
        raw_mr = res.choices[0].message.content.strip()
        start_mr, end_mr = raw_mr.find('{'), raw_mr.rfind('}')
        if start_mr != -1 and end_mr > start_mr:
            summary = _json_mr.loads(raw_mr[start_mr:end_mr+1])
        else:
            summary = raw_mr
    except Exception as e:
        groq_err = repr(e)[:200]

    market_report = {
        "trend_score": current,
        "avg_score":   avg_val,
        "growth_rate": growth,
        "risk":        risk,
        "summary":     summary,
    }
    if groq_err:
        market_report["_groq_error"] = groq_err

    # complaints 별도 캐시 (항상 최신 데이터 유지)
    _COMPLAINT_CACHE_KEY = f"complaints:{category}"
    if complaints:
        _GROQ_CACHE[_COMPLAINT_CACHE_KEY] = (_time.time() + 1800, complaints)
    else:
        _cc = _GROQ_CACHE.get(_COMPLAINT_CACHE_KEY)
        if _cc and _time.time() < _cc[0] and _cc[1]:
            complaints = _cc[1]

    result = {
        "category": category,
        "period":   period,
        "trend":    trend_data,
        "brands":   brand_data,
        "age_distribution": age_dist,
        "keywords":   keywords,
        "complaints": complaints,
        "market_report": market_report,
        "_fetched_at": _time.time(),
    }
    # complaints가 여전히 비어 있으면 메인 캐시 저장 생략 → 다음 요청에서 재시도
    complaint_ok = bool(complaints) or bool(_GROQ_CACHE.get(_COMPLAINT_CACHE_KEY))
    if not groq_err and trend_data and complaint_ok:
        result_no_complaints = {**result, "complaints": []}
        _GROQ_CACHE[_ck] = (_time.time() + _GROQ_TTL, result_no_complaints)
    return result


@router.get("/price")
async def get_price_intelligence(category: str = Query(..., min_length=1), _: dict = Depends(require_b2b)):
    import json as _json
    from app.database import fetchall, execute as db_exec

    today = date.today()

    raw = await search_products(query=category, page=1, display=100, sort="sim", category=category)
    items = [it for it in raw.get("items", []) if it.get("price", 0) > 0]

    if not items:
        return {"error": "가격 데이터를 불러올 수 없습니다"}

    prices = [it["price"] for it in items]
    sorted_prices = sorted(prices)
    avg_price    = int(sum(prices) / len(prices))
    min_price    = sorted_prices[0]
    max_price    = sorted_prices[-1]
    median_price = sorted_prices[len(sorted_prices) // 2]

    brand_map: dict[str, list[int]] = {}
    for it in items:
        b = (it.get("maker") or it.get("brand") or "").strip()
        if b:
            brand_map.setdefault(b, []).append(it["price"])

    by_brand = sorted(
        [
            {
                "brand":     b,
                "avg_price": int(sum(ps) / len(ps)),
                "min_price": min(ps),
                "max_price": max(ps),
                "count":     len(ps),
            }
            for b, ps in brand_map.items()
            if len(ps) >= 2
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    top_deals = [
        {"title": strip_html(it.get("title", ""))[:60], "price": it["price"],
         "brand": it.get("maker", "") or it.get("brand", ""), "link": it.get("link", "")}
        for it in sorted(items, key=lambda x: x["price"])[:10]
    ]

    rng  = max_price - min_price if max_price > min_price else 1
    step = rng / 5
    distribution = []
    for i in range(5):
        lo = int(min_price + i * step)
        hi = int(min_price + (i + 1) * step) if i < 4 else max_price + 1
        cnt = sum(1 for p in prices if lo <= p < hi)
        if i < 4:
            label = f"{fmt_price_label(lo)}~{fmt_price_label(hi)}"
        else:
            label = f"{fmt_price_label(lo)}+"
        distribution.append({"range": label, "count": cnt, "lo": lo})
    distribution[-1]["hi"] = None

    b_json = _json.dumps(
        [{"brand": b["brand"], "avg": b["avg_price"], "cnt": b["count"]} for b in by_brand[:5]],
        ensure_ascii=False,
    )
    try:
        await db_exec(
            """
            INSERT INTO price_history
                (category, snapshot_date, avg_price, min_price, max_price, median_price, total_products, brand_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                avg_price      = VALUES(avg_price),
                min_price      = VALUES(min_price),
                max_price      = VALUES(max_price),
                median_price   = VALUES(median_price),
                total_products = VALUES(total_products),
                brand_data     = VALUES(brand_data)
            """,
            (category, today, avg_price, min_price, max_price, median_price, len(prices), b_json),
        )
    except Exception as e:
        logger.warning("가격 스냅샷 DB 저장 실패 [%s]: %s", category, e)

    history_rows = await fetchall(
        "SELECT snapshot_date, avg_price, min_price, max_price FROM price_history "
        "WHERE category = %s ORDER BY snapshot_date ASC LIMIT 30",
        (category,),
    )

    # 데이터가 14일 미만이면 Danawa 백필을 백그라운드에서 실행
    if len(history_rows) < 14:
        from app.services.price_service import backfill_category_price_history
        asyncio.create_task(backfill_category_price_history(category, today))

    price_history = [
        {
            "date":      str(row["snapshot_date"]),
            "avg_price": row["avg_price"],
            "min_price": row["min_price"],
            "max_price": row["max_price"],
        }
        for row in history_rows
    ]

    price_change_pct = None
    if len(price_history) >= 2:
        prev = price_history[-2]["avg_price"]
        curr = price_history[-1]["avg_price"]
        price_change_pct = round((curr - prev) / max(prev, 1) * 100, 1)

    # ── AI 가격 인사이트 (RAG + Groq) ──
    import json as _json2
    from app.dependencies import get_rag_optional
    rag = get_rag_optional()

    price_insight = {
        "signal":     "적정가",
        "reason":     f"현재 평균가 {avg_price // 10000}만원으로 적정 수준입니다.",
        "strategy":   "현재 재고 수준을 유지하세요.",
        "brand_pick": by_brand[0]["brand"] if by_brand else "-",
        "summary":    f"{category} 가격 분석 결과입니다.",
    }
    try:
        rag_ctx = ""
        if rag:
            chunks = await rag.query(f"{category} 가격 구매 시점 납품 전략", n_results=6)
            if chunks:
                rag_ctx = "\n[소비자 가격 반응 데이터]\n" + "\n".join(f"- {c[:_RAG_CHUNK_LEN]}" for c in chunks)

        brand_summary = ", ".join(
            f"{b['brand']} 평균 {b['avg_price'] // 10000}만원"
            for b in by_brand[:3]
        ) or "데이터 부족"
        change_str = (
            f"{'+' if price_change_pct >= 0 else ''}{price_change_pct}%"
            if price_change_pct is not None else "첫 스냅샷"
        )

        prompt = (
            f"[{category} 가격 인텔리전스 — {today}]\n"
            f"- 평균가: {avg_price // 10000}만원 / 최저가: {min_price // 10000}만원 / 최고가: {max_price // 10000}만원\n"
            f"- 전일 대비: {change_str}\n"
            f"- 상위 브랜드 평균가: {brand_summary}\n"
            f"{rag_ctx}\n\n"
            f"아래 JSON으로만 응답하세요:\n"
            f'{{\n'
            f'  "signal": "매입 적기 또는 관망 권장 또는 적정가 중 하나",\n'
            f'  "reason": "판단 근거 1문장 (수치 포함, ~으로 판단됩니다 어조)",\n'
            f'  "strategy": "B2B 구매 전략 1문장 (예: 2개월치 선매입을 추천합니다)",\n'
            f'  "brand_pick": "납품 추천 브랜드명",\n'
            f'  "summary": "종합 가격 시장 전망 2~3문장 (~을 추천합니다/권장합니다 어조)"\n'
            f'}}'
        )
        res = await _groq_create(
            messages=[
                {"role": "system", "content": "B2B 가전 유통 가격 전략 어드바이저입니다. '~을 추천합니다', '~을 권장합니다', '~하시길 권합니다' 형식의 자신감 있는 권고 어조를 사용하세요. 순수 JSON만 출력하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        raw = res.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = _json2.loads(raw)
        price_insight.update({k: v for k, v in parsed.items() if k in price_insight})
    except Exception as e:
        price_insight["_groq_error"] = repr(e)[:300]

    return {
        "category":      category,
        "snapshot_date": str(today),
        "summary": {
            "avg_price":        avg_price,
            "min_price":        min_price,
            "max_price":        max_price,
            "median_price":     median_price,
            "total_products":   len(prices),
            "price_change_pct": price_change_pct,
        },
        "by_brand":           by_brand,
        "price_distribution": distribution,
        "top_deals":          top_deals,
        "price_history":      price_history,
        "price_insight":      price_insight,
    }


@router.get("/ai-report")
async def get_ai_report(category: str = Query(..., min_length=1), period: str = "3m", _: dict = Depends(require_b2b)):
    import json as _json
    from app.dependencies import get_rag_optional

    # ── 캐시 확인 ──
    _ck = f"ai-report:{_CACHE_VER}:{category}:{period}"
    _cached = _GROQ_CACHE.get(_ck)
    if _cached and _time.time() < _cached[0]:
        return _cached[1]

    rag = get_rag_optional()

    days_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    days = days_map.get(period, 90)
    time_unit = "week" if days > 30 else "date"
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dl_headers = {**NAVER_HEADERS, "Content-Type": "application/json"}

    async def _fetch_trend():
        body = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate":   end_date.strftime("%Y-%m-%d"),
            "timeUnit":  time_unit,
            "keywordGroups": [{"groupName": category, "keywords": [category]}],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://openapi.naver.com/v1/datalab/search", json=body, headers=dl_headers)
        results = resp.json().get("results", [])
        return results[0]["data"] if results else []

    async def _fetch_brands():
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://openapi.naver.com/v1/search/shop.json",
                headers=NAVER_HEADERS,
                params={"query": category, "display": 100, "sort": "sim"},
            )
        counts: dict[str, int] = {}
        for it in resp.json().get("items", []):
            b = it.get("maker", "").strip() or it.get("brand", "").strip()
            if b:
                counts[b] = counts.get(b, 0) + 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:6]
        total = sum(v for _, v in top)
        return [{"brand": k, "count": v, "pct": round(v / total * 100) if total else 0} for k, v in top]

    trend_data, brand_data = await asyncio.gather(_fetch_trend(), _fetch_brands(), return_exceptions=True)
    trend_data = trend_data if not isinstance(trend_data, Exception) else []
    brand_data = brand_data if not isinstance(brand_data, Exception) else []

    # DataLab 최신 주 미집계 trailing 저비율 데이터 제거
    while len(trend_data) > 4 and trend_data[-1]["ratio"] < trend_data[-2]["ratio"] * 0.3:
        trend_data = trend_data[:-1]

    ratios  = [d["ratio"] for d in trend_data]
    current = round(ratios[-1], 1) if ratios else 0
    avg_val = round(sum(ratios) / len(ratios), 1) if ratios else 0
    half    = len(ratios) // 2
    old_avg = sum(ratios[:half]) / max(half, 1)
    new_avg = sum(ratios[half:]) / max(len(ratios) - half, 1)
    growth  = round((new_avg - old_avg) / max(old_avg, 1) * 100, 1)
    risk    = _calc_risk(growth)

    top3       = ", ".join(f"{b['brand']} {b['pct']}%" for b in brand_data[:3]) or "데이터 부족"
    top_brand  = brand_data[0]["brand"] if brand_data else "데이터 없음"

    report = {
        "action":               "관망",
        "action_reason":        "데이터를 분석 중입니다",
        "timing":               "-",
        "inventory_advice":     "-",
        "opportunity":          [],
        "risk_summary":         [],
        "brand_focus":          top_brand,
        "summary":              f"{category} 시장 분석 결과입니다.",
        "action_basis":         [],
        "target_segment":       "-",
        "price_range":          "-",
        "key_keywords":         [],
        "recommended_products": "-",
        "risk_factor":          "-",
        "product_strategy":     [],
        "sales_strategy":       [],
        "service_strategy":     [],
    }

    try:
        rag_context = ""
        if rag:
            chunks = await rag.query(f"{category} 소비자 반응 구매 결정 트렌드", n_results=8)
            if chunks:
                rag_context = "\n[소비자 실반응 RAG 데이터]\n" + "\n".join(f"- {c[:_RAG_CHUNK_LEN]}" for c in chunks)

        prompt = (
            f"[{category} B2B 시장 데이터 — {period}]\n"
            f"- 검색 관심도: 현재 {current} / 기간 평균 {avg_val}\n"
            f"- 성장률: {'+' if growth >= 0 else ''}{growth}%\n"
            f"- 주요 브랜드: {top3}\n"
            f"- 시장 위험도: {risk}\n"
            f"{rag_context}\n\n"
            f"아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):\n"
            f'{{\n'
            f'  "action": "매입 확대 또는 매입 유지 또는 재고 축소 또는 관망 중 하나",\n'
            f'  "action_reason": "행동 권고 핵심 이유 1문장 (수치 포함)",\n'
            f'  "timing": "권장 매입 시기 (예: 7~8월)",\n'
            f'  "inventory_advice": "권장 재고 조정 (예: 현재 대비 +20%)",\n'
            f'  "action_basis": ["AI 판단 근거 ①(15자 이내)", "근거②", "근거③", "근거④"],\n'
            f'  "opportunity": ["기회 요인① (15자 이내)", "기회 요인②", "기회 요인③"],\n'
            f'  "risk_summary": ["위험 요인① (15자 이내)", "위험 요인②", "위험 요인③"],\n'
            f'  "target_segment": "추천 소비 타깃 (예: 50대+)",\n'
            f'  "price_range": "추천 가격대 (예: 50~80만원)",\n'
            f'  "key_keywords": ["핵심키워드1", "키워드2", "키워드3"],\n'
            f'  "recommended_products": "추천 제품군 (예: 프리미엄·AI 에어컨)",\n'
            f'  "risk_factor": "핵심 위험 요소 (10자 이내 명사형)",\n'
            f'  "summary": "AI 종합 시장 전망 3문장 (현황·전망·전략 순서)",\n'
            f'  "product_strategy": ["제품 전략① (20자 이내 구체적 행동)", "전략②", "전략③"],\n'
            f'  "sales_strategy":   ["판매 전략① (20자 이내 구체적 행동)", "전략②", "전략③"],\n'
            f'  "service_strategy": ["서비스 전략① (20자 이내 구체적 행동)", "전략②", "전략③"]\n'
            f'}}'
        )

        res = await _groq_create(
            messages=[
                {"role": "system", "content": "당신은 B2B 가전 유통 전략 어드바이저입니다. 구체적인 수치와 근거를 포함해 작성하세요. 순수 JSON만 출력하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.3,
        )
        raw = res.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = _json.loads(raw)
        report.update({k: v for k, v in parsed.items() if k in report})
    except Exception as e:
        report["_groq_error"] = repr(e)[:300]

    result = {
        "category": category,
        "period":   period,
        "metrics": {
            "trend_score": current,
            "avg_score":   avg_val,
            "growth_rate": growth,
            "risk":        risk,
        },
        "brands": brand_data,
        "report": report,
    }
    if "_groq_error" not in report:
        _GROQ_CACHE[_ck] = (_time.time() + _GROQ_TTL, result)
    return result


@router.get("/demand-forecast")
async def get_demand_forecast(category: str = Query(..., min_length=1), period: str = "3m", _: dict = Depends(require_b2b)):
    import logging
    import numpy as np
    import pandas as pd
    from prophet import Prophet
    from app.dependencies import get_rag_optional
    rag = get_rag_optional()

    days_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    days = days_map.get(period, 90)
    if days <= 30:
        time_unit = "date"
    elif days < 365:
        time_unit = "week"
    else:
        time_unit = "month"

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dl_headers = {**NAVER_HEADERS, "Content-Type": "application/json"}

    # ── 표시용 데이터: 선택한 period ──────────────────────────────────────────
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  time_unit,
        "keywordGroups": [{"groupName": category, "keywords": [category]}],
    }
    # ── 학습용 데이터: 항상 2년치 주별 (Prophet 연간 패턴 학습 위해) ──────────
    train_start = end_date - timedelta(days=730)
    train_body = {
        "startDate": train_start.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  "week",
        "keywordGroups": [{"groupName": category, "keywords": [category]}],
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp, train_resp = await asyncio.gather(
            client.post("https://openapi.naver.com/v1/datalab/search", json=body, headers=dl_headers),
            client.post("https://openapi.naver.com/v1/datalab/search", json=train_body, headers=dl_headers),
        )
    results = resp.json().get("results", [])
    trend_data = results[0]["data"] if results else []
    train_results = train_resp.json().get("results", [])
    train_data = train_results[0]["data"] if train_results else trend_data

    if not trend_data:
        return {"error": "트렌드 데이터를 불러올 수 없습니다"}

    # DataLab 최신 주 미집계로 인한 trailing 저비율 데이터 제거
    def _trim_trailing(data):
        while len(data) > 4 and data[-1]["ratio"] < data[-2]["ratio"] * 0.3:
            data = data[:-1]
        return data

    trend_data = _trim_trailing(trend_data)
    train_data = _trim_trailing(train_data)

    # 1m(date)는 일별 데이터로 단기 정확도 유지, 그 외는 2년 주별 학습 데이터 사용
    if time_unit == "date":
        df = pd.DataFrame({
            "ds": pd.to_datetime([d["period"] for d in trend_data]),
            "y":  [float(d["ratio"]) for d in trend_data],
        })
    else:
        df = pd.DataFrame({
            "ds": pd.to_datetime([d["period"] for d in train_data]),
            "y":  [float(d["ratio"]) for d in train_data],
        })

    freq_map     = {"date": "D", "week": "W", "month": "MS"}
    forecast_map = {"date": 14,  "week": 22,  "month": 6}
    freq         = freq_map[time_unit]
    forecast_n   = forecast_map[time_unit]

    hist_max  = float(df["y"].max())  if not df.empty else 100.0
    hist_mean = float(df["y"].mean()) if not df.empty else 50.0
    forecast_cap = max(hist_max * 1.5, hist_mean * 3.0)

    def _run_prophet() -> pd.DataFrame:
        logging.getLogger("prophet").setLevel(logging.ERROR)
        logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
        n_pts = len(df)
        m = Prophet(
            yearly_seasonality=(n_pts >= 52),   # 1년치 이상 있을 때만
            weekly_seasonality=False,
            daily_seasonality=False,
            interval_width=0.80,
            seasonality_mode="additive",
            changepoint_prior_scale=0.1,        # 변화점 민감도 상향 (0.05→0.1)
            seasonality_prior_scale=12.0,       # 계절성 강도 상향
        )
        if n_pts >= 26:
            # 반년 이상 데이터 시 월별 계절성 추가
            m.add_seasonality(name="monthly", period=4.33, fourier_order=5)
        m.fit(df)
        future = m.make_future_dataframe(periods=forecast_n, freq=freq)
        return m.predict(future)

    # ── 선형회귀: 폴백 + 계절 영향도 분석 ────────────────────────────────────
    def _run_linear_fallback():
        """Prophet 실패 시 선형회귀 폴백."""
        import math as _math
        ratios = df["y"].tolist()
        n = len(ratios)
        xs = list(range(n))
        sx = sum(xs); sy = sum(ratios)
        sxy = sum(x * y for x, y in zip(xs, ratios))
        sxx = sum(x * x for x in xs)
        denom = n * sxx - sx * sx
        slope_lr = (n * sxy - sx * sy) / denom if denom else 0.0
        intercept = (sy - slope_lr * sx) / n
        residuals_lr = [ratios[i] - (intercept + slope_lr * i) for i in range(n)]
        std_lr = _math.sqrt(sum(r ** 2 for r in residuals_lr) / max(n - 2, 1))
        last_dt = df["ds"].iloc[-1]
        delta_map = {"date": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
        delta = delta_map[time_unit]
        rows = []
        for i in range(forecast_n):
            xi = n + i
            pred = max(0.0, round(intercept + slope_lr * xi, 1))
            lbl = (last_dt + delta * (i + 1)).strftime("%Y-%m-%d")
            rows.append({"ds": lbl, "yhat": pred,
                         "yhat_lower": max(0.0, pred - _CI_MULTIPLIER * std_lr),
                         "yhat_upper": pred + _CI_MULTIPLIER * std_lr,
                         "trend": intercept + slope_lr * xi})
        return rows, slope_lr, std_lr

    def _run_lr_influence():
        """선형회귀: 계절 영향도 분석 (월별 효과 + 추세 기울기)"""
        y_arr = df["y"].values
        n     = len(y_arr)
        months = [d.month for d in df["ds"]]
        # X: intercept + trend + 12 month dummies
        X = np.zeros((n, 14))
        X[:, 0] = 1.0                          # intercept
        X[:, 1] = np.arange(n, dtype=float)    # trend
        for i, m in enumerate(months):
            X[i, m + 1] = 1.0                  # month dummy (cols 2-13)
        try:
            coefs, _, _, _ = np.linalg.lstsq(X, y_arr, rcond=None)
        except Exception:
            return None
        trend_slope  = float(coefs[1])
        month_coefs  = {m: float(coefs[m + 1]) for m in range(1, 13)}
        mn = {1:'1월',2:'2월',3:'3월',4:'4월',5:'5월',6:'6월',
              7:'7월',8:'8월',9:'9월',10:'10월',11:'11월',12:'12월'}
        peak_m = max(month_coefs, key=month_coefs.get)
        low_m  = min(month_coefs, key=month_coefs.get)
        direction = '증가' if trend_slope > 0 else '감소'
        return {
            "trend_slope":     round(trend_slope, 3),
            "peak_month":      mn[peak_m],
            "low_month":       mn[low_m],
            "monthly_effects": [
                {"month": mn[m], "effect": round(month_coefs[m], 1)}
                for m in range(1, 13)
            ],
            "interpretation": (
                f"매 기간 관심도가 {abs(round(trend_slope, 2))} 포인트씩 {direction}하는 추세이며, "
                f"{mn[peak_m]}에 계절 관심도가 가장 높고 {mn[low_m]}에 가장 낮습니다."
            ),
        }

    # ── XGBoost: lag + 시간 features ──────────────────────────────────────────
    def _run_xgb():
        try:
            import xgboost as xgb
            logger.info("[XGB] xgboost import OK, version=%s", xgb.__version__)
        except ImportError as e:
            logger.warning("[XGB] import 실패: %s", e)
            return None, None
        try:
            y_arr = df["y"].values
            n     = len(y_arr)
            # 2년 주별(104주) 학습 데이터 → LAG 최대 12주(3개월)로 확장
            LAG   = min(12, max(2, n // 8))
            logger.info("[XGB] n=%d, LAG=%d, threshold=%d", n, LAG, LAG + 4)
            if n < LAG + 4:
                logger.warning("[XGB] 데이터 부족으로 스킵 (n=%d < %d)", n, LAG + 4)
                return None, None

            def _feats(t_idx: int, month: int, lags: list) -> list:
                lag_arr = lags[-LAG:]
                return [
                    t_idx,
                    month,
                    float(np.sin(2 * np.pi * month / 12)),
                    float(np.cos(2 * np.pi * month / 12)),
                    float(np.sin(2 * np.pi * (t_idx % 52) / 52)),  # 연간 위치
                    *lag_arr,
                    float(np.mean(lag_arr)),
                    float(np.std(lag_arr)) if len(lag_arr) > 1 else 0.0,
                ]

            X_tr, Y_tr = [], []
            for i in range(LAG, n):
                m = df["ds"].iloc[i].month
                X_tr.append(_feats(i, m, list(y_arr[i - LAG:i])))
                Y_tr.append(float(y_arr[i]))
            X_tr = np.array(X_tr); Y_tr = np.array(Y_tr)

            n_est = 300 if n >= 52 else 200
            model = xgb.XGBRegressor(
                n_estimators=n_est, max_depth=4, learning_rate=0.04,
                subsample=0.85, colsample_bytree=0.8,
                min_child_weight=2, gamma=0.1,
                random_state=42, verbosity=0, n_jobs=1,
            )
            model.fit(X_tr, Y_tr)

            hist_pred = model.predict(X_tr)
            rmse_xgb  = float(np.sqrt(np.mean((Y_tr - hist_pred) ** 2)))

            delta_map2 = {"D": timedelta(days=1), "W": timedelta(weeks=1), "MS": timedelta(days=30)}
            delta2  = delta_map2[freq]
            last_dt = df["ds"].iloc[-1]
            rolling = list(y_arr[-LAG:])
            preds   = []
            for i in range(forecast_n):
                future_ds = last_dt + delta2 * (i + 1)
                m  = future_ds.month
                xf = np.array([_feats(n + i, m, rolling)])
                p  = float(model.predict(xf)[0])
                p  = max(0.0, min(forecast_cap, p))
                preds.append({"period": future_ds.strftime("%Y-%m-%d"), "predicted": round(p, 1)})
                rolling.append(p)
            return preds, rmse_xgb
        except Exception as e:
            logger.warning("XGBoost 학습 실패: %s", e)
            return None, None

    # ── 모델 실행 ─────────────────────────────────────────────────────────────
    use_prophet = True
    try:
        fc = await asyncio.to_thread(_run_prophet)
    except Exception as e:
        logger.warning("Prophet 실패, 선형회귀 폴백 사용: %s", e)
        use_prophet = False

    try:
        xgb_preds, xgb_rmse = await asyncio.to_thread(_run_xgb)
    except Exception as e:
        logger.warning("XGBoost 실행 실패: %s", e)
        xgb_preds, xgb_rmse = None, None
    influence = _run_lr_influence()

    if use_prophet:
        # R² 기반 신뢰도
        hist_yhat = fc.iloc[:len(df)]["yhat"].values
        ss_res    = float(np.sum((df["y"].values - hist_yhat) ** 2))
        ss_tot    = float(np.sum((df["y"].values - df["y"].mean()) ** 2))
        r_squared = max(0.0, 1.0 - ss_res / max(ss_tot, 1e-9))
        confidence = int(r_squared * 100)
        prophet_rmse = float(np.sqrt(ss_res / len(df)))
        future_fc = fc.iloc[len(df):]
        prophet_forecast = [
            {
                "period":    row["ds"].strftime("%Y-%m-%d"),
                "predicted": round(min(forecast_cap, max(0.0, row["yhat"])), 1),
                "ci_low":    round(min(forecast_cap, max(0.0, row["yhat_lower"])), 1),
                "ci_high":   round(min(forecast_cap * 1.2, max(0.0, row["yhat_upper"])), 1),
            }
            for _, row in future_fc.iterrows()
        ]
        trend_vals    = future_fc["trend"].values
        slope         = float((trend_vals[-1] - trend_vals[0]) / max(forecast_n - 1, 1))
        hist_yhat_arr = hist_yhat
    else:
        fb_rows, slope, res_std_fb = _run_linear_fallback()
        prophet_forecast = [
            {
                "period":    r["ds"],
                "predicted": round(r["yhat"], 1),
                "ci_low":    round(max(0.0, r["yhat_lower"]), 1),
                "ci_high":   round(r["yhat_upper"], 1),
            }
            for r in fb_rows
        ]
        prophet_rmse  = float(res_std_fb)
        confidence    = 50
        hist_yhat_arr = np.array([df["y"].mean()] * len(df))

    # ── 앙상블: Prophet + XGBoost (RMSE 기반 가중치) ──────────────────────────
    if xgb_preds and use_prophet and xgb_rmse is not None and prophet_rmse > 0:
        total_rmse = prophet_rmse + xgb_rmse
        w_p = xgb_rmse  / total_rmse   # XGB가 나쁠수록 Prophet 가중치 ↑
        w_x = prophet_rmse / total_rmse
        forecast = [
            {
                "period":    prophet_forecast[i]["period"],
                "predicted": round(w_p * prophet_forecast[i]["predicted"] + w_x * xgb_preds[i]["predicted"], 1),
                "ci_low":    prophet_forecast[i]["ci_low"],
                "ci_high":   prophet_forecast[i]["ci_high"],
            }
            for i in range(forecast_n)
        ]
        model_used  = "ensemble"
        model_weights = {"prophet": round(w_p, 2), "xgb": round(w_x, 2)}
    else:
        forecast      = prophet_forecast
        model_used    = "prophet" if use_prophet else "linear"
        model_weights = None

    if use_prophet:
        residuals  = df["y"].values - hist_yhat_arr
        res_std    = float(np.sqrt((residuals ** 2).mean()))
    else:
        res_std = res_std_fb
    slope_threshold = max(0.15, res_std * 0.3)
    if slope > slope_threshold:
        trend_dir = "상승"
    elif slope < -slope_threshold:
        trend_dir = "하락"
    else:
        trend_dir = "안정"

    peak_idx    = max(range(forecast_n), key=lambda i: forecast[i]["predicted"])
    peak_period = forecast[peak_idx]["period"]

    recommendation = (
        f"수요 상승세가 예측됩니다. {peak_period[:7]} 이전에 재고를 선제적으로 확보하시길 추천합니다."
        if trend_dir == "상승"
        else f"수요 하락세가 예측됩니다. 재고를 보수적으로 운영하시고 프로모션 전략 검토를 권장합니다."
        if trend_dir == "하락"
        else "수요가 안정적으로 유지될 것으로 예측됩니다. 현재 재고 수준 유지를 추천합니다."
    )

    rag_insight: dict = {}
    _ri_ck = f"forecast-rag:{_CACHE_VER}:{category}:{trend_dir}:{peak_period[:7]}"
    _ri_cached = _GROQ_CACHE.get(_ri_ck)
    if _ri_cached and _ri_cached[0] > _time.time():
        rag_insight = _ri_cached[1]
    else:
      try:
        import json as _json_fc
        peak_month = peak_period[5:7]
        ctx = ""
        if rag:
            chunks = await rag.query(f"{category} 계절 수요 시즌 구매 패턴", n_results=6)
            if chunks:
                ctx = "\n[소비자 구매 패턴 데이터]\n" + "\n".join(f"- {c[:_RAG_CHUNK_LEN]}" for c in chunks)
        res = await _groq_create(
            messages=[
                {"role": "system", "content": "가전 시장 수요 예측 어드바이저입니다. 순수 JSON만 출력하세요."},
                {"role": "user", "content": (
                    f"[{category} 예측 요약]\n"
                    f"- 트렌드: {trend_dir}\n"
                    f"- 예측 피크: {peak_period[:7]}\n"
                    f"- 성수기 방향: {trend_dir}"
                    f"{ctx}\n\n"
                    f"다음 JSON 형식으로 응답하세요:\n"
                    f'{{\n'
                    f'  "opportunity": ["기회요인1 (15자 이내)", "기회요인2", "기회요인3"],\n'
                    f'  "risk": ["위험요인1 (15자 이내)", "위험요인2", "위험요인3"],\n'
                    f'  "strategy": ["전략1 (20자 이내 행동지침)", "전략2", "전략3"]\n'
                    f'}}\n'
                    f'opportunity: {category} 시장의 기회 요인 2~3가지 (명사형)\n'
                    f'risk: 주요 위험 요인 2~3가지 (명사형)\n'
                    f'strategy: {peak_month}월 전후 구매·판매 전략 2~3가지 (구체적 행동 지침)\n'
                    f'순수 JSON만 출력하세요.'
                )},
            ],
            max_tokens=350,
            temperature=0.3,
        )
        raw_fc = res.choices[0].message.content.strip()
        s_fc = raw_fc.find("{"); e_fc = raw_fc.rfind("}")
        if s_fc != -1 and e_fc != -1:
            rag_insight = _json_fc.loads(raw_fc[s_fc:e_fc + 1])
            _GROQ_CACHE[_ri_ck] = (_time.time() + _GROQ_TTL, rag_insight)
      except Exception as e:
        logger.warning("RAG insight 생성 실패: %s", e)
        rag_insight = {}

    return {
        "category":        category,
        "period":          period,
        "time_unit":       time_unit,
        "history":         [{"period": d["period"], "ratio": d["ratio"]} for d in trend_data],
        "forecast":        forecast,
        "trend_direction": trend_dir,
        "slope":           round(slope, 3),
        "peak_period":     peak_period,
        "confidence":      confidence,
        "recommendation":  recommendation,
        "rag_insight":     rag_insight,
        "model_info": {
            "used":    model_used,
            "weights": model_weights,
            "rmse": {
                "prophet": round(prophet_rmse, 2) if use_prophet else None,
                "xgb":     round(xgb_rmse, 2)    if xgb_rmse is not None else None,
            },
        },
        "influence": influence,
    }


_TREND_CTX_FALLBACK: dict[str, dict] = {
    "에어컨": {
        "region":  [{"label":"서울","pct":25},{"label":"경기","pct":21},{"label":"부산","pct":16},{"label":"대구","pct":14},{"label":"인천","pct":10}],
        "install": [{"label":"벽걸이형","pct":48},{"label":"스탠드형","pct":32},{"label":"2in1","pct":12},{"label":"창문형","pct":8}],
        "purpose": [{"label":"냉방 성능","pct":35},{"label":"전기료 절감","pct":28},{"label":"AI 기능","pct":18},{"label":"저소음","pct":12},{"label":"디자인","pct":7}],
        "related": [{"label":"제습기","pct":31},{"label":"선풍기","pct":24},{"label":"공기청정기","pct":18},{"label":"서큘레이터","pct":15},{"label":"창문형에어컨","pct":12}],
    },
    "냉장고": {
        "region":  [{"label":"서울","pct":28},{"label":"경기","pct":24},{"label":"부산","pct":14},{"label":"인천","pct":12},{"label":"대구","pct":10}],
        "install": [{"label":"일반형","pct":45},{"label":"양문형","pct":30},{"label":"4도어","pct":15},{"label":"소형","pct":10}],
        "purpose": [{"label":"용량","pct":35},{"label":"에너지효율","pct":25},{"label":"신선도","pct":20},{"label":"디자인","pct":12},{"label":"소음","pct":8}],
        "related": [{"label":"김치냉장고","pct":28},{"label":"정수기","pct":22},{"label":"전자레인지","pct":18},{"label":"식기세척기","pct":15},{"label":"와인냉장고","pct":17}],
    },
    "세탁기": {
        "region":  [{"label":"서울","pct":27},{"label":"경기","pct":23},{"label":"부산","pct":15},{"label":"인천","pct":11},{"label":"대구","pct":9}],
        "install": [{"label":"드럼형","pct":55},{"label":"통돌이형","pct":30},{"label":"미니세탁기","pct":10},{"label":"벽걸이형","pct":5}],
        "purpose": [{"label":"세척력","pct":38},{"label":"에너지효율","pct":24},{"label":"소음","pct":18},{"label":"용량","pct":12},{"label":"건조 겸용","pct":8}],
        "related": [{"label":"건조기","pct":42},{"label":"세탁세제","pct":22},{"label":"스팀다리미","pct":16},{"label":"옷걸이","pct":12},{"label":"세탁망","pct":8}],
    },
    "건조기": {
        "region":  [{"label":"서울","pct":30},{"label":"경기","pct":25},{"label":"부산","pct":13},{"label":"인천","pct":10},{"label":"대구","pct":9}],
        "install": [{"label":"콘덴서형","pct":50},{"label":"히트펌프형","pct":35},{"label":"벽걸이형","pct":15}],
        "purpose": [{"label":"빠른 건조","pct":35},{"label":"에너지효율","pct":28},{"label":"저소음","pct":18},{"label":"살균 기능","pct":12},{"label":"대용량","pct":7}],
        "related": [{"label":"세탁기","pct":45},{"label":"건조대","pct":20},{"label":"스팀다리미","pct":15},{"label":"에어드레서","pct":12},{"label":"세탁세제","pct":8}],
    },
    "공기청정기": {
        "region":  [{"label":"서울","pct":30},{"label":"경기","pct":26},{"label":"부산","pct":13},{"label":"인천","pct":10},{"label":"대구","pct":8}],
        "install": [{"label":"스탠드형","pct":55},{"label":"소형","pct":28},{"label":"벽걸이형","pct":10},{"label":"차량용","pct":7}],
        "purpose": [{"label":"미세먼지 제거","pct":40},{"label":"바이러스 제거","pct":25},{"label":"냄새 제거","pct":18},{"label":"소음","pct":10},{"label":"디자인","pct":7}],
        "related": [{"label":"가습기","pct":32},{"label":"제습기","pct":25},{"label":"에어컨","pct":20},{"label":"서큘레이터","pct":15},{"label":"환풍기","pct":8}],
    },
    "로봇청소기": {
        "region":  [{"label":"서울","pct":32},{"label":"경기","pct":27},{"label":"부산","pct":12},{"label":"인천","pct":9},{"label":"대구","pct":8}],
        "install": [{"label":"일반형","pct":60},{"label":"물걸레형","pct":25},{"label":"올인원","pct":15}],
        "purpose": [{"label":"청소 편의","pct":42},{"label":"흡입력","pct":25},{"label":"물걸레 기능","pct":18},{"label":"소음","pct":8},{"label":"배터리","pct":7}],
        "related": [{"label":"진공청소기","pct":35},{"label":"물걸레청소기","pct":28},{"label":"스팀청소기","pct":18},{"label":"청소포","pct":12},{"label":"공기청정기","pct":7}],
    },
    "TV": {
        "region":  [{"label":"서울","pct":26},{"label":"경기","pct":22},{"label":"부산","pct":15},{"label":"인천","pct":11},{"label":"대구","pct":10}],
        "install": [{"label":"벽걸이형","pct":55},{"label":"스탠드형","pct":35},{"label":"이동형","pct":10}],
        "purpose": [{"label":"화질","pct":38},{"label":"크기","pct":25},{"label":"스마트 기능","pct":18},{"label":"음질","pct":12},{"label":"디자인","pct":7}],
        "related": [{"label":"사운드바","pct":35},{"label":"HDMI케이블","pct":22},{"label":"OTT 구독","pct":18},{"label":"게임콘솔","pct":15},{"label":"TV받침대","pct":10}],
    },
    "식기세척기": {
        "region":  [{"label":"서울","pct":29},{"label":"경기","pct":25},{"label":"부산","pct":13},{"label":"인천","pct":11},{"label":"대구","pct":9}],
        "install": [{"label":"빌트인형","pct":40},{"label":"일반형","pct":38},{"label":"미니형","pct":22}],
        "purpose": [{"label":"세척력","pct":35},{"label":"용량","pct":25},{"label":"건조 성능","pct":20},{"label":"소음","pct":12},{"label":"에너지효율","pct":8}],
        "related": [{"label":"냉장고","pct":30},{"label":"세제","pct":28},{"label":"가스레인지","pct":18},{"label":"음식물처리기","pct":14},{"label":"전자레인지","pct":10}],
    },
}
_GENERIC_FALLBACK = {
    "region":  [{"label":"서울","pct":26},{"label":"경기","pct":22},{"label":"부산","pct":15},{"label":"인천","pct":11},{"label":"대구","pct":10}],
    "install": [{"label":"일반형","pct":50},{"label":"소형","pct":28},{"label":"대형","pct":22}],
    "purpose": [{"label":"성능","pct":35},{"label":"에너지효율","pct":25},{"label":"가격","pct":20},{"label":"디자인","pct":12},{"label":"소음","pct":8}],
    "related": [{"label":"관련제품1","pct":35},{"label":"관련제품2","pct":28},{"label":"관련제품3","pct":18},{"label":"관련제품4","pct":12},{"label":"관련제품5","pct":7}],
}


@router.get("/trend-context")
async def get_trend_context(category: str = Query(..., min_length=1), period: str = "3m", _: dict = Depends(require_b2b)):
    """
    트렌드 분석3: 주요 사용 환경(지역별) / 설치 형태 / 구매 목적 / 연관 가전
    """
    import json as _json

    _ck = f"trend-context:{category}:{period}"
    _cached = _GROQ_CACHE.get(_ck)
    if _cached and _time.time() < _cached[0]:
        return _cached[1]

    # 카테고리별 기본 fallback 준비
    fb = _TREND_CTX_FALLBACK.get(category, _GENERIC_FALLBACK)

    # 제품 데이터 + 블로그 텍스트 수집
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            shop_resp = await client.get(
                "https://openapi.naver.com/v1/search/shop.json",
                headers=NAVER_HEADERS,
                params={"query": category, "display": 50, "sort": "sim"},
            )
            blog_resp = await client.get(
                "https://openapi.naver.com/v1/search/blog.json",
                headers=NAVER_HEADERS,
                params={"query": f"{category} 구매 후기 설치", "display": 20, "sort": "date"},
            )
        shop_items = shop_resp.json().get("items", [])
        blog_items = blog_resp.json().get("items", [])
    except Exception as e:
        logger.warning(f"[trend-context] 네이버 API 실패: {e}")
        shop_items, blog_items = [], []

    # 제품 타이틀에서 설치 형태 직접 추출
    install_kws = {
        "벽걸이형": ["벽걸이", "벽결이"],
        "스탠드형": ["스탠드"],
        "2in1": ["2in1", "투인원"],
        "창문형": ["창문형"],
        "드럼형": ["드럼"],
        "통돌이형": ["통돌이"],
        "콘덴서형": ["콘덴서"],
        "히트펌프형": ["히트펌프"],
        "양문형": ["양문형", "양문냉장고"],
        "4도어": ["4도어", "빌트인"],
    }
    install_counts: dict[str, int] = {}
    for it in shop_items:
        title_low = strip_html(it.get("title", "")).lower()
        for label, kws in install_kws.items():
            if any(k in title_low for k in kws):
                install_counts[label] = install_counts.get(label, 0) + 1

    total_inst = sum(install_counts.values()) or 0
    install_data = sorted(
        [{"label": k, "pct": round(v / total_inst * 100)} for k, v in install_counts.items()],
        key=lambda x: x["pct"], reverse=True
    )[:4] if total_inst >= 3 else []

    # Groq로 region/purpose/related 생성
    blog_text = " ".join(
        strip_html(b.get("title", "")) + " " + strip_html(b.get("description", ""))
        for b in blog_items
    )[:2000]
    shop_text = " ".join(strip_html(it.get("title", "")) for it in shop_items[:25])

    groq_ok = False
    result = {
        "region":  list(fb["region"]),
        "install": install_data or list(fb["install"]),
        "purpose": list(fb["purpose"]),
        "related": list(fb["related"]),
    }

    try:
        prompt = (
            f"한국 '{category}' 가전 시장을 분석해 JSON만 출력하세요. 다른 텍스트 없이 JSON만.\n\n"
            f"쇼핑 제품명: {shop_text[:600]}\n"
            f"블로그 내용: {blog_text[:900]}\n\n"
            f'{{"region":[{{"label":"서울","pct":숫자}},{{"label":"경기","pct":숫자}},{{"label":"부산","pct":숫자}},{{"label":"대구","pct":숫자}},{{"label":"인천","pct":숫자}}],'
            f'"purpose":[{{"label":"구매이유1","pct":숫자}},{{"label":"구매이유2","pct":숫자}},{{"label":"구매이유3","pct":숫자}},{{"label":"구매이유4","pct":숫자}},{{"label":"구매이유5","pct":숫자}}],'
            f'"related":[{{"label":"연관가전1","pct":숫자}},{{"label":"연관가전2","pct":숫자}},{{"label":"연관가전3","pct":숫자}},{{"label":"연관가전4","pct":숫자}},{{"label":"연관가전5","pct":숫자}}]}}'
            f'\n위 형식대로 실제 한국 {category} 시장 데이터로 채워 JSON만 출력하세요.'
        )
        groq_resp = await _groq_create(
            messages=[
                {"role": "system", "content": "당신은 한국 가전 시장 데이터 전문가입니다. 요청한 JSON 형식만 출력하세요. 마크다운, 설명 없이 순수 JSON만."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.1,
        )
        raw = groq_resp.choices[0].message.content.strip()
        # 마크다운 코드블록 제거
        if "```" in raw:
            raw = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()
        # JSON 추출 (첫 { 부터 마지막 } 까지)
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            parsed = _json.loads(raw[start:end+1])
            if parsed.get("region") and parsed.get("purpose") and parsed.get("related"):
                result["region"]  = parsed["region"]
                result["purpose"] = parsed["purpose"]
                result["related"] = parsed["related"]
                groq_ok = True
    except Exception as e:
        logger.warning(f"[trend-context] Groq 실패 (fallback 사용): {e}")

    # Groq 성공 시만 캐시 (실패 결과는 캐시 안 함)
    if groq_ok:
        _GROQ_CACHE[_ck] = (_time.time() + 1800, result)
    return result


@router.get("/product-price")
async def get_product_price(title: str = Query(..., min_length=1), _: dict = Depends(require_b2b)):
    import json as _json
    from app.database import fetchall, execute as db_exec

    today = date.today()
    model = extract_model_number(title)
    product_key = model if model else re.sub(r'\s+', ' ', title.strip())[:100]
    search_q = model if model else title

    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            NAVER_SHOP_URL,
            headers=NAVER_HEADERS,
            params={"query": search_q, "display": 50, "sort": "sim"},
        )

    items_raw = resp.json().get("items", []) if resp.status_code == 200 else []
    _RENTAL_MALL_KW = ["렌탈", "리스", "렌트", "월정액", "구독"]

    items = [
        {
            "mall":  strip_html(it.get("mallName", "")),
            "title": strip_html(it["title"]),
            "price": int(it["lprice"]),
            "link":  it.get("link", ""),
        }
        for it in items_raw
        if it.get("lprice") and int(it["lprice"]) > 0
        and not any(kw in strip_html(it.get("mallName", "")) for kw in _RENTAL_MALL_KW)
        and not any(kw in strip_html(it["title"]) for kw in _RENTAL_MALL_KW)
    ]

    if not items:
        return {"available": False, "product_key": product_key, "model_number": model}

    raw_prices = sorted(it["price"] for it in items)
    median_price = raw_prices[len(raw_prices) // 2]
    items = [it for it in items if median_price * 0.2 <= it["price"] <= median_price * 5]

    if not items:
        return {"available": False, "product_key": product_key, "model_number": model}

    prices = [it["price"] for it in items]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = int(sum(prices) / len(prices))

    mall_map: dict[str, int] = {}
    for it in items:
        mall = it["mall"]
        if mall and (mall not in mall_map or it["price"] < mall_map[mall]):
            mall_map[mall] = it["price"]

    malls = sorted(
        [{"mall": m, "price": p} for m, p in mall_map.items()],
        key=lambda x: x["price"],
    )[:8]

    cheapest = min(items, key=lambda x: x["price"])

    mall_json = _json.dumps(malls, ensure_ascii=False)
    try:
        await db_exec(
            """
            INSERT INTO product_price_history
                (product_key, product_name, model_number, min_price, max_price, avg_price, snapshot_date, mall_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                min_price = VALUES(min_price),
                max_price = VALUES(max_price),
                avg_price = VALUES(avg_price),
                mall_data = VALUES(mall_data)
            """,
            (product_key, title[:500], model, min_price, max_price, avg_price, today, mall_json),
        )
    except Exception as e:
        logger.warning("상품 가격 DB 저장 실패 [%s]: %s", title[:50], e)

    history_rows = await fetchall(
        "SELECT snapshot_date, min_price, avg_price, max_price "
        "FROM product_price_history WHERE product_key = %s "
        "ORDER BY snapshot_date ASC LIMIT 30",
        (product_key,),
    )
    price_history = [
        {
            "date":      str(r["snapshot_date"]),
            "min_price": r["min_price"],
            "avg_price": r["avg_price"],
        }
        for r in history_rows
    ]

    hist_avg = (
        int(sum(r["avg_price"] for r in history_rows) / len(history_rows))
        if history_rows else avg_price
    )
    hist_min = min(r["min_price"] for r in history_rows) if history_rows else min_price

    vs_hist_avg_pct = round((min_price - hist_avg) / max(hist_avg, 1) * 100, 1)

    if vs_hist_avg_pct <= -5:
        signal_type, signal = "buy", "구매 추천"
        reason = f"현재 최저가({min_price // 10000}만원)가 {abs(int(vs_hist_avg_pct))}% 저렴합니다. 지금이 적기입니다."
    elif vs_hist_avg_pct >= 5:
        signal_type, signal = "wait", "관망 권장"
        reason = f"현재 최저가({min_price // 10000}만원)가 평소보다 {int(vs_hist_avg_pct)}% 비쌉니다."
    else:
        signal_type, signal = "neutral", "적정가"
        reason = "현재 가격이 평소 수준입니다."

    return {
        "available":      True,
        "product_key":    product_key,
        "model_number":   model,
        "min_price":      min_price,
        "max_price":      max_price,
        "avg_price":      avg_price,
        "hist_avg_price": hist_avg,
        "hist_min_price": hist_min,
        "cheapest_mall":  cheapest["mall"],
        "cheapest_link":  cheapest["link"],
        "malls":          malls,
        "price_history":  price_history,
        "signal":         signal,
        "signal_type":    signal_type,
        "reason":         reason,
        "snapshot_date":  str(today),
    }


@router.get("/product-analysis")
async def get_product_analysis(q: str = Query(..., min_length=1), _: dict = Depends(require_b2b)):
    from app.database import fetchall
    from app.dependencies import get_rag_optional
    rag = get_rag_optional()

    today = date.today()
    model = extract_model_number(q)
    product_key = model if model else re.sub(r'\s+', ' ', q.strip())[:100]
    search_q = model if model else q

    detected_category = None
    for kw, cat in _CATEGORY_MAP.items():
        if kw in q:
            detected_category = cat
            break

    async def _fetch_price():
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(NAVER_SHOP_URL, headers=NAVER_HEADERS,
                    params={"query": search_q, "display": 50, "sort": "sim"})
            _RKW = ["렌탈", "리스", "렌트", "월정액", "구독"]
            items_raw = resp.json().get("items", []) if resp.status_code == 200 else []
            items = [
                {"mall": strip_html(it.get("mallName", "")), "price": int(it["lprice"]), "link": it.get("link", "")}
                for it in items_raw
                if it.get("lprice") and int(it["lprice"]) > 0
                and not any(kw in strip_html(it.get("mallName", "")) for kw in _RKW)
                and not any(kw in strip_html(it.get("title", "")) for kw in _RKW)
            ]
            if not items:
                return None
            raw = sorted(it["price"] for it in items)
            med = raw[len(raw) // 2]
            items = [it for it in items if med * 0.2 <= it["price"] <= med * 5]
            if not items:
                return None
            prices = [it["price"] for it in items]
            mall_map: dict = {}
            for it in items:
                m = it["mall"]
                if m and (m not in mall_map or it["price"] < mall_map[m]["price"]):
                    mall_map[m] = it
            malls = sorted([{"mall": m, "price": v["price"], "link": v["link"]}
                            for m, v in mall_map.items()], key=lambda x: x["price"])[:10]
            cheapest = malls[0]
            history_rows = await fetchall(
                "SELECT snapshot_date, min_price, avg_price FROM product_price_history "
                "WHERE product_key = %s ORDER BY snapshot_date ASC LIMIT 30",
                (product_key,),
            )
            price_history = [{"date": str(r["snapshot_date"]), "min_price": r["min_price"],
                               "avg_price": r["avg_price"]} for r in history_rows]
            hist_avg = int(sum(r["avg_price"] for r in history_rows) / len(history_rows)) if history_rows else int(sum(prices) / len(prices))
            hist_min = min(r["min_price"] for r in history_rows) if history_rows else min(prices)
            min_p = min(prices)
            vs_pct = round((min_p - hist_avg) / max(hist_avg, 1) * 100, 1)
            if vs_pct <= -5:
                signal, signal_type = "구매 추천", "buy"
                reason = f"현재 최저가({min_p // 10000}만원)가 {abs(int(vs_pct))}% 저렴합니다."
            elif vs_pct >= 5:
                signal, signal_type = "관망 권장", "wait"
                reason = f"현재 가격이 평소보다 {int(vs_pct)}% 비쌉니다."
            else:
                signal, signal_type = "적정가", "neutral"
                reason = "현재 가격이 평소 수준입니다."
            return {
                "min_price": min_p, "avg_price": int(sum(prices) / len(prices)),
                "max_price": max(prices), "hist_avg": hist_avg, "hist_min": hist_min,
                "malls": malls, "cheapest_mall": cheapest["mall"], "cheapest_link": cheapest["link"],
                "price_history": price_history, "signal": signal, "signal_type": signal_type,
                "reason": reason, "model_number": model,
            }
        except Exception as e:
            logger.warning("상품 가격 조회 실패: %s", e)
            return None

    async def _fetch_trend():
        try:
            start_d = (today - timedelta(days=90)).strftime("%Y-%m-%d")
            end_d   = today.strftime("%Y-%m-%d")
            headers = {**NAVER_HEADERS, "Content-Type": "application/json"}
            body = {"startDate": start_d, "endDate": end_d, "timeUnit": "week",
                    "keywordGroups": [{"groupName": q, "keywords": [q]}]}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://openapi.naver.com/v1/datalab/search",
                                         json=body, headers=headers)
            results = resp.json().get("results", [])
            return results[0]["data"] if results else []
        except Exception as e:
            logger.warning("트렌드 데이터 조회 실패: %s", e)
            return []

    async def _fetch_reviews():
        try:
            rq = f"{q} 사용후기"
            async with httpx.AsyncClient(timeout=8.0) as client:
                blog_r, cafe_r = await asyncio.gather(
                    client.get("https://openapi.naver.com/v1/search/blog.json",
                               headers=NAVER_HEADERS, params={"query": rq, "display": 10, "sort": "date"}),
                    client.get("https://openapi.naver.com/v1/search/cafearticle.json",
                               headers=NAVER_HEADERS, params={"query": rq, "display": 8, "sort": "date"}),
                )
            reviews = []
            for it in blog_r.json().get("items", []):
                txt = strip_html(it.get("description", "")).strip()
                if len(txt) < 30:
                    continue
                reviews.append({"source": "블로그", "title": strip_html(it["title"]),
                                 "review": txt[:200], "link": it.get("link", "")})
            for it in cafe_r.json().get("items", []):
                txt = strip_html(it.get("description", "")).strip()
                if len(txt) < 30:
                    continue
                reviews.append({"source": "카페", "title": strip_html(it["title"]),
                                 "review": txt[:200], "link": it.get("link", "")})
            return reviews[:12]
        except Exception:
            return []

    async def _fetch_competitors():
        if not detected_category:
            return []
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(NAVER_SHOP_URL, headers=NAVER_HEADERS,
                    params={"query": detected_category, "display": 40, "sort": "sim"})
            items = resp.json().get("items", []) if resp.status_code == 200 else []
            filtered = [
                {"title": strip_html(it["title"])[:50],
                 "brand": it.get("maker", "") or it.get("brand", ""),
                 "price": int(it["lprice"]), "link": it.get("link", ""), "image": it.get("image", "")}
                for it in items if it.get("lprice") and int(it["lprice"]) > 0
            ]
            if filtered:
                prices = sorted(f["price"] for f in filtered)
                med = prices[len(prices) // 2]
                filtered = [f for f in filtered if med * 0.2 <= f["price"] <= med * 5]
            seen: dict = {}
            result = []
            for f in filtered:
                b = f["brand"] or "기타"
                if b not in seen:
                    seen[b] = True
                    result.append(f)
                if len(result) >= 8:
                    break
            return result
        except Exception:
            return []

    price_data, trend_data, reviews, competitors = await asyncio.gather(
        _fetch_price(), _fetch_trend(), _fetch_reviews(), _fetch_competitors(),
        return_exceptions=True,
    )
    price_data  = price_data  if not isinstance(price_data,  Exception) else None
    trend_data  = trend_data  if not isinstance(trend_data,  Exception) else []
    reviews     = reviews     if not isinstance(reviews,     Exception) else []
    competitors = competitors if not isinstance(competitors, Exception) else []

    all_text = ' '.join(r["review"] for r in reviews)
    pos = sum(1 for w in _POS_WORDS if w in all_text)
    neg = sum(1 for w in _NEG_WORDS if w in all_text)
    score = round(pos / (pos + neg) * 100) if (pos + neg) > 0 else 50
    words = re.findall(r'[가-힣]{2,5}', all_text)
    kw_counts = Counter(w for w in words if w not in _STOP)
    keywords = [{"word": w, "count": c} for w, c in kw_counts.most_common(16)]

    return {
        "query":    q,
        "model_number": model,
        "category": detected_category,
        "price":    price_data,
        "trend":    trend_data,
        "reviews":  reviews[:8],
        "sentiment": {"pos": pos, "neg": neg, "score": score, "keywords": keywords},
        "competitors": competitors,
    }
