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

async def _groq_create(messages: list, max_tokens: int = 600, temperature: float = 0.3):
    """RateLimitError 시 fallback 모델로 자동 재시도."""
    import os
    from groq import AsyncGroq, RateLimitError
    client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    for i, model in enumerate(_GROQ_MODELS):
        try:
            return await client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
        except RateLimitError:
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


@router.get("/dashboard")
async def get_b2b_dashboard(category: str = Query(..., min_length=1), period: str = "3m", _: dict = Depends(require_b2b)):
    from app.dependencies import get_rag_optional

    _ck = f"dashboard:{category}:{period}"
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

    async def fetch_trend():
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

    async def fetch_brand_share():
        data = await search_products(query=category, page=1, display=100, sort="sim", category=category)
        counts: dict[str, int] = {}
        for it in data.get("items", []):
            b = it.get("brand", "").strip()
            if b:
                counts[b] = counts.get(b, 0) + 1
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
        results = resp.json().get("results", [])
        data = results[0]["data"] if results else []
        return sum(d["ratio"] for d in data) / len(data) if data else 0.0

    async def fetch_keywords():
        # Groq 의존성 제거: search_products 직접 호출로 키워드 추출
        raw = await search_products(query=category, page=1, display=30, sort="sim", category=category)
        items = raw.get("items", [])
        kws: list[str] = []
        seen: set[str] = set()

        # config _STOP(조사·접속사) + B2B 전용 설치/배송 노이즈 통합
        KW_STOP = _STOP | {
            "미포함", "포함", "수도권", "설치비포함", "설치비별도", "방문설치",
            "무료설치", "무료", "별도", "이하", "이상", "할인", "택배", "직접",
            "기사", "배송", "셀프", "자가설치", "원룸", "평", "인치",
        }

        def add(w: str):
            w = w.strip()
            if (w and len(w) >= 2 and w not in seen
                    and w != category and w not in KW_STOP
                    and not _has_non_korean_cjk(w)):
                seen.add(w)
                kws.append(w)

        # 1순위: 브랜드명
        for it in items:
            add(it.get("brand") or "")

        # 2순위: 제조사 (브랜드와 다른 경우 보완)
        for it in items:
            add(it.get("maker") or "")

        # 3순위: 세부 카테고리 (category3·4 — 형태 특성 키워드)
        for it in items:
            add(it.get("category3") or "")
            add(it.get("category4") or "")

        # 4순위: 제목 토큰 (숫자 포함 토큰 제외)
        for it in items:
            title = re.sub(r'[^가-힣a-zA-Z\s]', ' ', it.get("title") or "")
            for tok in title.split():
                if len(tok) >= 2 and not any(c.isdigit() for c in tok):
                    add(tok)
                if len(kws) >= 30:
                    break
            if len(kws) >= 30:
                break

        return kws[:24]

    age_groups = [["2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10", "11"]]
    age_labels = ["10대", "20대", "30대", "40대", "50대+"]

    results = await asyncio.gather(
        fetch_trend(),
        fetch_brand_share(),
        *[fetch_age(g) for g in age_groups],
        fetch_keywords(),
        return_exceptions=True,
    )

    trend_data = results[0] if not isinstance(results[0], Exception) else []
    brand_data = results[1] if not isinstance(results[1], Exception) else []
    age_raw    = [r if not isinstance(r, Exception) else 0.0 for r in results[2:7]]
    keywords   = results[7] if not isinstance(results[7], Exception) else []

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
            f"[{category} 시장 B2B 분석]\n"
            f"- 검색 관심도: 현재 {current} / 기간 평균 {avg_val}\n"
            f"- {period} 성장률: {'+' if growth >= 0 else ''}{growth}%\n"
            f"- 주요 브랜드: {top3}\n"
            f"- 주 관심층: {top_age}\n"
            f"{rag_context}\n"
            f"위 데이터를 바탕으로 {category} 시장의 미래 전망과 B2B 사업 기회를 2~3문장으로 작성하세요. "
            f"'~을 추천합니다', '~을 권장합니다', '~하시길 권합니다' 같은 권고·추천 어조를 사용하세요. 한국어만 사용."
        )
        res = await _groq_create(
            messages=[
                {"role": "system", "content": "당신은 B2B 가전 시장 분석 어드바이저입니다. '~을 추천합니다', '~을 권장합니다' 형식의 자신감 있는 권고 어조로 작성하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            temperature=0.4,
        )
        summary = res.choices[0].message.content.strip()
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

    result = {
        "category": category,
        "period":   period,
        "trend":    trend_data,
        "brands":   brand_data,
        "age_distribution": age_dist,
        "keywords": keywords,
        "market_report": market_report,
    }
    if not groq_err:
        _GROQ_CACHE[_ck] = (_time.time() + _GROQ_TTL, result)
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
        b = (it.get("brand") or "").strip()
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
         "brand": it.get("brand", ""), "link": it.get("link", "")}
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
    _ck = f"ai-report:{category}:{period}"
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
        data = await search_products(query=category, page=1, display=100, sort="sim", category=category)
        counts: dict[str, int] = {}
        for it in data.get("items", []):
            b = it.get("brand", "").strip()
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
        "action":           "관망",
        "action_reason":    "데이터를 분석 중입니다",
        "timing":           "-",
        "inventory_advice": "-",
        "opportunity":      "-",
        "risk_summary":     "-",
        "brand_focus":      top_brand,
        "summary":          f"{category} 시장 분석 결과입니다.",
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
            f'  "action_reason": "행동 권고 이유 (1문장, 수치 포함, ~을 추천합니다 어조)",\n'
            f'  "timing": "재고 확보 시점 (예: 7~8월 집중 매입을 추천합니다)",\n'
            f'  "inventory_advice": "재고 전략 (예: 현재 대비 20% 확대를 권장합니다)",\n'
            f'  "opportunity": "주요 기회 요인 (1문장, ~을 추천합니다 어조)",\n'
            f'  "risk_summary": "주요 위험 요인 (1문장, ~에 유의하시길 권합니다 어조)",\n'
            f'  "brand_focus": "집중 추천 브랜드명",\n'
            f'  "summary": "종합 시장 전망 3문장 — 현황·전망·전략 순서로, ~을 추천합니다/권장합니다 어조"\n'
            f'}}'
        )

        res = await _groq_create(
            messages=[
                {"role": "system", "content": "당신은 B2B 가전 유통 전략 어드바이저입니다. '~을 추천합니다', '~을 권장합니다', '~하시길 권합니다' 형식의 자신감 있는 권고 어조로 작성하세요. 순수 JSON만 출력하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
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
    import math as _math
    from app.dependencies import get_rag_optional
    rag = get_rag_optional()

    days_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    days = days_map.get(period, 90)
    if days <= 90:
        time_unit = "date"
    elif days <= 180:
        time_unit = "week"
    else:
        time_unit = "month"

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dl_headers = {**NAVER_HEADERS, "Content-Type": "application/json"}

    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  time_unit,
        "keywordGroups": [{"groupName": category, "keywords": [category]}],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(NAVER_DATALAB_URL, json=body, headers=dl_headers)
    results = resp.json().get("results", [])
    trend_data = results[0]["data"] if results else []

    if not trend_data:
        return {"error": "트렌드 데이터를 불러올 수 없습니다"}

    # DataLab 최신 주 미집계로 인한 trailing 저비율 데이터 제거
    while len(trend_data) > 4 and trend_data[-1]["ratio"] < trend_data[-2]["ratio"] * 0.3:
        trend_data = trend_data[:-1]

    ratios = [float(d["ratio"]) for d in trend_data]
    n = len(ratios)

    forecast_map = {"date": 14, "week": 8, "month": 6}
    forecast_n   = forecast_map[time_unit]

    # 선형회귀 (순수 Python, 외부 라이브러리 없음)
    xs  = list(range(n))
    sx  = sum(xs);  sy  = sum(ratios)
    sxy = sum(x * y for x, y in zip(xs, ratios))
    sxx = sum(x * x for x in xs)
    denom     = n * sxx - sx * sx
    slope     = (n * sxy - sx * sy) / denom if denom else 0.0
    intercept = (sy - slope * sx) / n

    residuals = [ratios[i] - (intercept + slope * i) for i in range(n)]
    res_std   = _math.sqrt(sum(r ** 2 for r in residuals) / max(n - 2, 1))

    # R² 기반 신뢰도
    mean_ratio = sy / n
    ss_tot     = sum((r - mean_ratio) ** 2 for r in ratios)
    ss_res     = sum(r ** 2 for r in residuals)
    r_squared  = max(0.0, 1.0 - ss_res / max(ss_tot, 1e-9))
    confidence = int(r_squared * 100)

    # 예측 생성
    last_dt = date.fromisoformat(trend_data[-1]["period"])
    delta_map = {"date": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    delta = delta_map[time_unit]

    forecast = []
    for i in range(forecast_n):
        xi   = n + i
        pred = max(0.0, round(intercept + slope * xi, 1))
        ci_r = _CI_MULTIPLIER * res_std
        label = (last_dt + delta * (i + 1)).strftime("%Y-%m-%d")
        forecast.append({
            "period":    label,
            "predicted": pred,
            "ci_low":    round(max(0.0, pred - ci_r), 1),
            "ci_high":   round(pred + ci_r, 1),
        })

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

    rag_insight = ""
    try:
        if rag:
            chunks = await rag.query(f"{category} 계절 수요 시즌 구매 패턴", n_results=6)
            if chunks:
                ctx = "\n".join(f"- {c[:_RAG_CHUNK_LEN]}" for c in chunks)
                peak_month = peak_period[5:7]
                res = await _groq_create(
                    messages=[
                        {"role": "system", "content": "가전 시장 수요 예측 어드바이저입니다. '~을 추천합니다', '~을 권장합니다' 형식의 자신감 있는 권고 어조로 2문장 이내로 한국어만 사용하세요."},
                        {"role": "user", "content": (
                            f"[{category} 예측 요약]\n"
                            f"- 트렌드: {trend_dir} (slope={slope:.2f})\n"
                            f"- 예측 피크: {peak_period[:7]}\n"
                            f"[소비자 구매 패턴 데이터]\n{ctx}\n\n"
                            f"{peak_month}월을 중심으로 {category} 재고 전략을 추천·권장 형식으로 조언해주세요."
                        )},
                    ],
                    max_tokens=200,
                    temperature=0.3,
                )
                rag_insight = res.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("RAG insight 생성 실패: %s", e)
        rag_insight = ""

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
    }


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
                {"title": strip_html(it["title"])[:50], "brand": it.get("brand", ""),
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
