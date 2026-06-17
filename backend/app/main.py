from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.security import OAuth2PasswordBearer
from contextlib import asynccontextmanager
from pydantic import BaseModel, EmailStr
import bcrypt
from jose import jwt
from datetime import datetime, timedelta
import random
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import re
import asyncio
from datetime import date, timedelta
from dotenv import load_dotenv
from typing import TYPE_CHECKING

from app.database import get_pool, close_pool
import app.dependencies as deps
from app.routers.insights import router as insights_router

if TYPE_CHECKING:
    from app.rag_service import RAGService

load_dotenv()

rag: "RAGService | None" = None


def extract_model_number(title: str) -> str | None:
    """제품 타이틀에서 모델번호 자동 추출."""
    patterns = [
        r'\b([A-Z]{2,}[0-9]{3,}[A-Z0-9]*)\b',        # WHDU181WSW, AF17TX7720GFD
        r'\b([A-Z]{2,}-[A-Z0-9]{3,}[A-Z0-9\-]*)\b',  # KR-C663RDFT
        r'\b([0-9]{2,}[A-Z]{2,}[0-9A-Z]{3,})\b',     # 85QN900D
    ]
    for pat in patterns:
        m = re.search(pat, title)
        if m and len(m.group(1)) >= 6:
            return m.group(1)
    return None


async def _init_tables():
    from app.database import execute, fetchall
    status_columns = await fetchall("SHOW COLUMNS FROM users LIKE 'status'")
    if not status_columns:
        await execute("""
            ALTER TABLE users
            ADD COLUMN status ENUM('pending', 'active', 'rejected')
            NOT NULL DEFAULT 'active'
            AFTER user_type
        """)
    await execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            category      VARCHAR(50)  NOT NULL,
            snapshot_date DATE         NOT NULL,
            avg_price     INT          NOT NULL DEFAULT 0,
            min_price     INT          NOT NULL DEFAULT 0,
            max_price     INT          NOT NULL DEFAULT 0,
            median_price  INT          NOT NULL DEFAULT 0,
            total_products INT         NOT NULL DEFAULT 0,
            brand_data    JSON,
            created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_cat_date (category, snapshot_date)
        )
    """)
    await execute("""
        CREATE TABLE IF NOT EXISTS product_price_history (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            product_key   VARCHAR(200) NOT NULL,
            product_name  VARCHAR(500),
            model_number  VARCHAR(100),
            min_price     INT          NOT NULL DEFAULT 0,
            max_price     INT          NOT NULL DEFAULT 0,
            avg_price     INT          NOT NULL DEFAULT 0,
            snapshot_date DATE         NOT NULL,
            mall_data     JSON,
            created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_prod_date (product_key, snapshot_date)
        )
    """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag
    await get_pool()
    await _init_tables()

    # 학원 PC에서는 RAG 모델 다운로드/ChromaDB 때문에 서버가 멈출 수 있어서 일단 끔
    rag = None
    deps.set_rag(None)
    print("[RAG] disabled for local development")

    yield
    await close_pool()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(insights_router)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"
NAVER_HEADERS = {
    "X-Naver-Client-Id":     NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

# 카테고리별 필터 규칙 — 부품·청소제·의류·통신사 상품 제거
CATEGORY_RULES = {
    "에어컨":    {
        "must":  ["에어컨", "냉난방기"],
        "block": ["청소", "세정", "스프레이", "필터만", "교체필터", "커버", "탈취",
                  "세척", "방향제", "부품", "블레이드", "날개", "팬날개", "의류",
                  "옷", "티셔츠", "팬블레이드", "선풍기 블레이드", "기기변경", "요금제", "개통"],
        "min_price": 50000,
    },
    "냉장고":    {
        "must":  ["냉장고"],
        "block": ["청소", "탈취", "보관용기", "정리함", "부품", "세제", "의류",
                  "스티커", "자석", "기기변경", "요금제"],
        "min_price": 100000,
    },
    "세탁기":    {
        "must":  ["세탁기"],
        "block": ["청소", "세제", "세탁망", "커버", "부품", "의류", "기기변경"],
        "min_price": 150000,
    },
    "건조기":    {
        "must":  ["건조기"],
        "block": ["청소", "부품", "필터", "의류", "기기변경"],
        "min_price": 150000,
    },
    "공기청정기": {
        "must":  ["공기청정기"],
        "block": ["필터만", "교체필터", "부품", "소모품", "의류", "기기변경"],
        "min_price": 30000,
    },
    "로봇청소기": {
        "must":  ["로봇청소기", "로봇 청소기"],
        "block": ["부품", "걸레만", "소모품", "필터만", "의류", "기기변경"],
        "min_price": 50000,
    },
    "식기세척기": {
        "must":  ["식기세척기"],
        "block": ["세제", "부품", "청소", "의류", "기기변경"],
        "min_price": 100000,
    },
    "TV":        {
        "must":  ["TV", "텔레비전"],
        "block": ["거치대", "브라켓", "케이블", "리모컨", "청소", "의류", "가방",
                  "기기변경", "요금제", "개통"],
        "min_price": 100000,
    },
    "세탁건조기": {
        "must":  ["세탁건조기", "건조세탁기"],
        "block": ["청소", "세제", "부품", "의류", "기기변경"],
        "min_price": 300000,
    },
    "에어프라이어": {
        "must":  ["에어프라이어"],
        "block": ["부품", "액세서리", "오일종이", "호일", "용지", "세제", "기기변경", "종이"],
        "min_price": 12000,
    },
    "전기밥솥":  {
        "must":  ["전기밥솥", "밥솥"],
        "block": ["부품", "패킹", "세제", "기기변경"],
        "min_price": 20000,
    },
    "전자레인지": {
        "must":  ["전자레인지"],
        "block": ["부품", "청소", "기기변경"],
        "min_price": 30000,
    },
    "가습기":    {
        "must":  ["가습기"],
        "block": ["청소", "세제", "필터만", "부품", "기기변경"],
        "min_price": 10000,
    },
    "제습기":    {
        "must":  ["제습기"],
        "block": ["부품", "기기변경"],
        "min_price": 30000,
    },
    "선풍기":    {
        "must":  ["선풍기"],
        "block": ["부품", "날개만", "커버", "기기변경"],
        "min_price": 10000,
    },
}


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def _fetch_transcript(video_id: str) -> str:
    # youtube_transcript_api는 동기 라이브러리라 to_thread로 실행
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = await asyncio.to_thread(
            YouTubeTranscriptApi.get_transcript,
            video_id,
            languages=["ko", "ko-KR"],
        )
        return " ".join(t["text"] for t in transcript[:80])[:300]
    except Exception:
        return ""


@app.get("/api/naver/products")
async def search_products(
    query:    str = Query(..., min_length=1),
    page:     int = Query(1,  ge=1),
    display:  int = Query(15, ge=1, le=100),
    sort:     str = Query("sim"),
    category: str = Query(None),
):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Naver API key not configured")

    rules = CATEGORY_RULES.get(category) if category else None
    fetch_display = 100 if rules else display
    start = (page - 1) * fetch_display + 1

    # 가격 정렬 + 카테고리 필터를 동시에 쓰면 저가 액세서리가 먼저 반환돼서
    # 관련도순으로 받아 필터 후 직접 정렬
    naver_sort = "sim" if (rules and sort in ("asc", "dsc")) else sort
    params = {"query": query, "display": fetch_display, "start": start, "sort": naver_sort}

    async with httpx.AsyncClient(timeout=8.0) as client:
        for attempt in range(3):
            resp = await client.get(NAVER_SHOP_URL, headers=NAVER_HEADERS, params=params)
            if resp.status_code != 429:
                break
            if attempt < 2:
                await asyncio.sleep(1.0 * (attempt + 1))

    if resp.status_code != 200:
        if resp.status_code == 429:
            raise HTTPException(status_code=429, detail="Naver API 요청 한도 초과. 잠시 후 다시 시도해주세요.")
        raise HTTPException(status_code=resp.status_code, detail="Naver API error")

    data = resp.json()

    items = [
        {
            "id":          item.get("productId", ""),
            "title":       strip_html(item["title"]),
            "brand":       item.get("brand") or item.get("maker", ""),
            "price":       int(item["lprice"]) if item.get("lprice") else 0,
            "image":       item.get("image", ""),
            "link":        item.get("link", ""),
            "mallName":    item.get("mallName", ""),
            "reviewCount": int(item.get("reviewCount") or 0),
            "reviewScore": float(item.get("reviewScore") or 0),
        }
        for item in data.get("items", [])
    ]

    if rules:
        safety = [
            it for it in items
            if not any(kw in it["title"] for kw in rules["block"])
            and (it["price"] == 0 or it["price"] >= rules["min_price"])
        ]
        must_ok = [it for it in safety if any(kw in it["title"] for kw in rules["must"])]
        items = (must_ok if must_ok else safety)

        if sort == "asc":
            items.sort(key=lambda x: x["price"] if x["price"] > 0 else 10**9)
        elif sort == "dsc":
            items.sort(key=lambda x: x["price"], reverse=True)

        items = items[:display]

    return {"items": items, "total": data.get("total", 0), "page": page, "display": display}


@app.get("/api/naver/news")
async def get_news(
    query:   str = Query(..., min_length=1),
    display: int = Query(5, ge=1, le=10),
):
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": query, "display": display, "sort": "date"}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=NAVER_HEADERS, params=params)
        data = resp.json()
        return {
            "items": [
                {
                    "title":       strip_html(item["title"]),
                    "description": strip_html(item["description"]),
                    "pubDate":     item["pubDate"],
                    "link": item.get("originallink") or item["link"],
                }
                for item in data.get("items", [])
            ]
        }
    except Exception:
        return {"items": []}


@app.get("/api/naver/datalab")
async def get_datalab(query: str = Query(..., min_length=1)):
    end_date   = date.today()
    start_date = end_date - timedelta(days=30)

    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {**NAVER_HEADERS, "Content-Type": "application/json"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  "date",
        "keywordGroups": [
            {
                "groupName": query,
                "keywords":  [query],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
        data = resp.json()
        results = data.get("results", [])
        return {"data": results[0]["data"] if results else []}
    except Exception:
        return {"data": []}


@app.get("/api/timing")
async def get_timing(category: str = Query(..., min_length=1)):
    end_date   = date.today()
    start_date = end_date - timedelta(days=90)
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {**NAVER_HEADERS, "Content-Type": "application/json"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate":   end_date.strftime("%Y-%m-%d"),
        "timeUnit":  "date",
        "keywordGroups": [{"groupName": category, "keywords": [category]}],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
        results = resp.json().get("results", [])
        data = results[0]["data"] if results else []
        if len(data) < 7:
            return {"data": [], "analysis": None}

        ratios = [d["ratio"] for d in data]
        avg_all  = sum(ratios) / len(ratios)
        recent7  = ratios[-7:]
        avg_r7   = sum(recent7) / len(recent7)
        oldest7  = ratios[:7]
        avg_o7   = sum(oldest7) / len(oldest7)
        current  = round(ratios[-1], 1)
        diff_pct = round((avg_r7 - avg_all) / max(avg_all, 1) * 100, 1)
        direction = (avg_r7 - avg_o7) / max(avg_o7, 1)

        if diff_pct <= -15:
            score = "최고"
            msg   = f"관심도가 90일 평균보다 {abs(diff_pct):.0f}% 낮아요. 수요가 적을 때 가격 협상력이 높습니다."
            color = "green"
        elif diff_pct <= 0:
            score = "좋음"
            msg   = f"관심도가 평균 수준이에요. 지금 구매도 무난합니다."
            color = "blue"
        elif diff_pct <= 20:
            score = "보통"
            msg   = f"관심도가 평균보다 {diff_pct:.0f}% 높아요. 조금 더 기다리면 좋을 수 있어요."
            color = "yellow"
        else:
            score = "대기"
            msg   = f"관심도가 급상승 중이에요 (+{diff_pct:.0f}%). 수요가 꺾인 후 구매를 권장합니다."
            color = "red"

        trend_dir = "상승" if direction > 0.05 else "하락" if direction < -0.05 else "안정"
        peak_day  = data[ratios.index(max(ratios))]["period"]

        return {
            "data":     data,
            "analysis": {
                "current":    current,
                "avg90":      round(avg_all, 1),
                "diff_pct":   diff_pct,
                "score":      score,
                "color":      color,
                "message":    msg,
                "trend_dir":  trend_dir,
                "peak_day":   peak_day,
            },
        }
    except Exception as e:
        return {"data": [], "analysis": None, "error": str(e)}


@app.get("/api/youtube/search")
async def youtube_search(
    query:       str = Query(..., min_length=1),
    max_results: int = Query(4, ge=1, le=6),
):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part":              "snippet",
        "q":                 f"{query} 리뷰",
        "type":              "video",
        "maxResults":        max_results,
        "relevanceLanguage": "ko",
        "key":               YOUTUBE_API_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
        data = resp.json()

        videos = [
            {
                "videoId":      item["id"]["videoId"],
                "title":        item["snippet"]["title"],
                "channelTitle": item["snippet"]["channelTitle"],
                "publishedAt":  item["snippet"]["publishedAt"][:10],
                "thumbnail":    item["snippet"]["thumbnails"]["medium"]["url"],
            }
            for item in data.get("items", [])
        ]

        transcript_tasks = [_fetch_transcript(v["videoId"]) for v in videos]

        try:
            transcripts = await asyncio.wait_for(
                asyncio.gather(*transcript_tasks, return_exceptions=True),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            transcripts = [""] * len(videos)

        for video, t in zip(videos, transcripts):
            video["transcript"] = t if isinstance(t, str) else ""

        if rag:
            docs = [
                {
                    "text": f"[YouTube] {v['title']} - {v['transcript']}",
                    "metadata": {"source": "youtube", "product": query},
                }
                for v in videos if v.get("transcript")
            ]
            if docs:
                asyncio.create_task(rag.add_documents(docs))

        return {"items": videos}
    except Exception:
        return {"items": []}


@app.get("/api/ppomppu")
async def get_ppomppu(query: str = Query(..., min_length=1)):
    try:
        import urllib.parse
        from bs4 import BeautifulSoup

        encoded = urllib.parse.quote(query)
        url = f"https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&keyword={encoded}&category=0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Accept":          "text/html,application/xhtml+xml",
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        # resp.content로 넘겨야 EUC-KR 인코딩을 BeautifulSoup이 올바르게 감지함
        soup = BeautifulSoup(resp.content, "html.parser")

        posts = []

        for row in soup.select("tr.baseList")[:10]:
            # td.title 안에서 href가 "view"로 시작하고 텍스트가 있는 a 태그만 선택
            title_el = None
            for a in row.select("td.title a[href]"):
                if a.get("href", "").startswith("view") and a.get_text(strip=True):
                    title_el = a
                    break

            if not title_el:
                continue

            href = title_el.get("href", "")
            link = (
                "https://www.ppomppu.co.kr/zboard/" + href
                if href.startswith("view")
                else "https://www.ppomppu.co.kr" + href
            )

            date = ""
            for td in row.find_all("td"):
                if re.match(r"^\d{2}/\d{2}/\d{2}$", td.get_text(strip=True)):
                    date = td.get_text(strip=True)
                    break

            comment_el = row.select_one(".reply_num")

            posts.append({
                "title":        str(title_el.get_text(strip=True)),
                "link":         str(link),
                "date":         str(date),
                "commentCount": str(comment_el.get_text(strip=True).strip("[]")) if comment_el else "0",
            })

        kw_list = [w for w in query.split() if len(w) >= 2]
        if kw_list:
            posts = [p for p in posts if any(kw in p["title"] for kw in kw_list)]

        if rag and posts:
            docs = [
                {
                    "text": f"[뽐뿌] {p['title']}",
                    "metadata": {"source": "ppomppu", "product": query},
                }
                for p in posts
            ]
            asyncio.create_task(rag.add_documents(docs))

        return {"items": posts}
    except Exception as e:
        return {"items": [], "error": str(e)}


@app.get("/api/trend")
async def get_trend(category: str = Query(None)):
    try:
        import json, math
        from groq import AsyncGroq
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

        ALL_CATS = ["냉장고", "세탁기", "건조기", "에어컨", "공기청정기",
                    "로봇청소기", "식기세척기", "에어프라이어", "TV", "세탁건조기"]

        def quality(it):
            return it["reviewScore"] * math.log(it["reviewCount"] + 1, 10)

        def dl_diff(dl_data):
            if len(dl_data) < 14:
                return 0
            h = len(dl_data) // 2
            return (sum(d["ratio"] for d in dl_data[h:]) / max(len(dl_data[h:]), 1)
                  - sum(d["ratio"] for d in dl_data[:h]) / max(len(dl_data[:h]), 1))

        if category and category != "전체":
            products_data, datalab = await asyncio.gather(
                search_products(query=category, page=1, display=20, sort="sim", category=category),
                get_datalab(category),
                return_exceptions=True,
            )
            items_raw = (products_data.get("items", []) if not isinstance(products_data, Exception) else [])
            dl_data   = (datalab.get("data", [])        if not isinstance(datalab, Exception) else [])
            ts = dl_data[-1]["ratio"] if dl_data else 50
            td = round(dl_diff(dl_data), 1)
            items_raw.sort(key=quality, reverse=True)
            pool = [{**it, "category": category, "trend_score": ts, "trend_diff": td}
                    for it in items_raw[:10]]
        else:
            async def fetch_cat(cat):
                products, datalab = await asyncio.gather(
                    search_products(query=cat, page=1, display=8, sort="sim", category=cat),
                    get_datalab(cat),
                    return_exceptions=True,
                )
                items = (products.get("items", []) if not isinstance(products, Exception) else [])
                dl    = (datalab.get("data", [])   if not isinstance(datalab, Exception) else [])
                ts = dl[-1]["ratio"] if dl else 0
                td = round(dl_diff(dl), 1)
                items.sort(key=quality, reverse=True)
                return [{**it, "category": cat, "trend_score": ts, "trend_diff": td}
                        for it in items[:2]]

            results  = await asyncio.gather(*[fetch_cat(c) for c in ALL_CATS])
            all_items = [it for sub in results for it in sub]
            all_items.sort(
                key=lambda x: x["trend_score"] + x["trend_diff"] * 1.5 + quality(x) * 3,
                reverse=True,
            )
            pool = all_items[:10]

        if not pool:
            return {"items": []}

        product_text = "\n".join([
            f"[{i}] 카테고리:{p['category']} | {p['title']} | {p['price']:,}원 "
            f"| 트렌드:{p['trend_score']:.0f} | 변화:{p['trend_diff']:+.1f}"
            for i, p in enumerate(pool)
        ])

        rec_res = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"오늘은 {date.today()}입니다. 각 제품이 지금 트렌드인 이유를 한국어 1문장으로 쓰세요. "
                        "각 제품마다 반드시 다른 이유를 쓰고 계절·생활트렌드·소비패턴을 반영하세요. "
                        "범용 표현('좋은 성능', '인기 많은')은 금지입니다. "
                        "반드시 JSON 형식으로만 응답: "
                        '{"items": [{"index": 0, "reason": "문장", "tag": "2~3단어"}, ...]}'
                    ),
                },
                {"role": "user", "content": product_text},
            ],
            max_tokens=900,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        reasons = json.loads(rec_res.choices[0].message.content).get("items", [])

        result = []
        for i, item in enumerate(pool):
            r = next((x for x in reasons if x.get("index") == i), {})
            result.append({**item, "reason": r.get("reason", ""), "tag": r.get("tag", "")})

        return {"items": result}

    except Exception as e:
        return {"items": [], "error": str(e)}


@app.get("/api/recommend")
async def get_recommend(query: str = Query(..., min_length=1)):
    try:
        import json, math
        from groq import AsyncGroq
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

        # LLM 단위 변환 오류 방지 — Python 정규식으로 직접 파싱
        budget_match = re.search(r'(\d+(?:\.\d+)?)만원', query)
        budget_max = int(float(budget_match.group(1)) * 10000) if budget_match else None

        parse_res = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "사용자의 가전제품 구매 요구사항을 분석해서 JSON으로만 반환하세요.\n"
                        "【search_term 규칙】\n"
                        "search_term은 네이버 쇼핑에서 검색할 2~3단어입니다. 반드시 다음을 지키세요:\n"
                        "- 가격·금액·예산 표현(만원, 원, 이하, 이상 등)을 절대 포함하지 마세요\n"
                        "- 사용 환경(자취, 1인, 가족, 사무실 등)도 포함하지 마세요\n"
                        "- 제품 카테고리 + 핵심 스펙만 2~3단어로 추출하세요\n"
                        "예시) '에어컨 1인 자취용 30만원 이하' → search_term: '벽걸이 에어컨'\n"
                        "      '4인 가족 냉장고 200만원' → search_term: '양문형 냉장고'\n"
                        "      '로봇청소기 가성비 30만원 이하' → search_term: '로봇청소기'\n"
                        "【constraints 규칙】\n"
                        "사용 환경·공간·기능 조건을 constraints 배열에 넣으세요.\n"
                        '{"search_term": "카테고리+스펙 2~3단어", '
                        '"constraints": ["조건1", "조건2"]}'
                    ),
                },
                {"role": "user", "content": query},
            ],
            max_tokens=120,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(parse_res.choices[0].message.content)
        search_term = parsed.get("search_term", query[:20]).strip()
        constraints = parsed.get("constraints", [])

        detected_cat = next(
            (cat for cat in CATEGORY_RULES if cat in query or cat in search_term), None
        )
        products_data = await search_products(
            query=search_term, page=1, display=20, sort="sim",
            category=detected_cat,
        )
        items = products_data.get("items", [])

        if budget_max:
            filtered = [it for it in items if it["price"] == 0 or it["price"] <= budget_max]
            if len(filtered) < 3:
                prices_gt0 = [it["price"] for it in items if it["price"] > 0]
                budget_wan = round(budget_max / 10000)
                if not prices_gt0:
                    return {
                        "recommendations": [],
                        "search_term": search_term,
                        "error": f"'{search_term}' 관련 제품을 찾지 못했어요. 검색어를 바꿔보거나 카테고리를 다시 선택해주세요.",
                    }
                min_price = min(prices_gt0)
                min_wan   = round(min_price / 10000)
                return {
                    "recommendations": [],
                    "search_term": search_term,
                    "error": f"'{search_term}'의 최저가는 약 {min_wan}만원이에요. {budget_wan}만원 예산으로는 찾기 어려워요. 예산을 높여보세요!",
                }
            items = filtered

        items = items[:10]
        if not items:
            return {"recommendations": [], "search_term": search_term, "error": "관련 제품을 찾지 못했습니다"}

        def quality(it):
            return round(it["reviewScore"] * math.log(it["reviewCount"] + 1, 10), 2)

        product_list_text = "\n".join([
            f"[{i}] {it['title']} | {it['price']:,}원 | 평점 {it['reviewScore']}/5 | 리뷰 {it['reviewCount']:,}개 | 품질점수 {quality(it)}"
            for i, it in enumerate(items)
        ])
        constraint_text = "\n".join(f"- {c}" for c in constraints) if constraints else "- 특별 조건 없음"
        budget_text = f"{budget_max:,}원 이하" if budget_max else "제한 없음"

        rec_res = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 15년 경력의 가전제품 전문 컨설턴트입니다. 아래 규칙을 반드시 지켜 제품 3개를 추천하세요.\n"
                        "규칙:\n"
                        "1. 예산 초과 제품은 절대 추천하지 마세요\n"
                        "2. 품질점수(평점×log리뷰수)가 높은 제품을 우선 고려하세요\n"
                        "3. reason은 반드시 제품마다 달라야 합니다. 제품명·모델·평형수·브랜드 특성 등 이 제품만의 차별점을 언급하세요\n"
                        "4. '가격이 저렴하다', '에너지 효율이 높다' 처럼 모든 제품에 쓸 수 있는 범용 문장은 금지입니다\n"
                        "5. reason은 사용자의 핵심 조건(공간 크기·예산·기능 등)과 연결해 이 제품이 왜 적합한지 구체적으로 쓰세요 (한국어 1~2문장)\n"
                        "6. highlight도 제품마다 달라야 합니다. 이 제품만의 핵심 한 줄 장점 (2~4단어)\n"
                        "7. 1위가 가장 적합한 제품입니다\n"
                        "JSON으로만 응답:\n"
                        '{"recommendations": [{"index": 정수, "reason": "제품 고유 이유", "highlight": "고유 장점"}, ...]}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"[요구사항] {query}\n"
                        f"[예산] {budget_text}\n"
                        f"[핵심 조건]\n{constraint_text}\n\n"
                        f"[제품 목록]\n{product_list_text}"
                    ),
                },
            ],
            max_tokens=400,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        rec_data = json.loads(rec_res.choices[0].message.content)
        recommendations = rec_data.get("recommendations", [])

        result = []
        for rec in recommendations[:3]:
            idx = rec.get("index", 0)
            if 0 <= idx < len(items):
                result.append({
                    **items[idx],
                    "reason":    rec.get("reason", ""),
                    "highlight": rec.get("highlight", ""),
                })

        return {"recommendations": result, "search_term": search_term}

    except Exception as e:
        return {"recommendations": [], "error": str(e)}


@app.get("/api/report")
async def get_report(query: str = Query(..., min_length=1)):
    STOPWORDS = {"이하", "이상", "포함", "이내", "기준", "용", "형"}
    raw = [w for w in query.split() if re.search(r"[가-힣]", w) and w not in STOPWORDS]
    seen = []
    for w in raw:
        if not any(w in s or s in w for s in seen):
            seen.append(w)
    short_query = " ".join(seen[:3]) if seen else " ".join(query.split()[:2])
    # DataLab은 단어가 너무 많으면 데이터가 없어서 카테고리+변형어 조합으로 시도
    dl_alt = " ".join(seen[2:4]) if len(seen) >= 4 else short_query

    results = await asyncio.gather(
        get_news(short_query, display=5),
        get_datalab(dl_alt),
        get_datalab(short_query),
        youtube_search(query, max_results=4),
        get_ppomppu(short_query),
        return_exceptions=True,
    )

    fallbacks = [{"items": []}, {"data": []}, {"data": []}, {"items": []}, {"items": []}]
    news, dl_alt_r, dl_main_r, youtube, ppomppu = [
        r if not isinstance(r, Exception) else fb
        for r, fb in zip(results, fallbacks)
    ]
    if len(dl_alt_r.get("data", [])) >= 10:
        datalab = dl_alt_r
        datalab_query = dl_alt
    else:
        datalab = dl_main_r
        datalab_query = short_query

    return {"news": news, "datalab": datalab, "youtube": youtube, "ppomppu": ppomppu, "datalab_query": datalab_query}


@app.get("/api/user-reviews")
async def get_user_reviews(query: str = Query(..., min_length=1)):
    blog_url  = "https://openapi.naver.com/v1/search/blog.json"
    cafe_url  = "https://openapi.naver.com/v1/search/cafearticle.json"
    review_query = f"{query} 사용후기"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            blog_resp, cafe_resp = await asyncio.gather(
                client.get(blog_url,  headers=NAVER_HEADERS, params={"query": review_query, "display": 8, "sort": "date"}),
                client.get(cafe_url,  headers=NAVER_HEADERS, params={"query": review_query, "display": 5, "sort": "date"}),
            )

        reviews = []

        for item in blog_resp.json().get("items", []):
            text = strip_html(item.get("description", "")).strip()
            if len(text) < 30:
                continue
            reviews.append({
                "source": "블로그",
                "title":  strip_html(item.get("title", "")),
                "review": text[:200],
                "date":   item.get("postdate", ""),
                "link":   item.get("link", ""),
            })

        for item in cafe_resp.json().get("items", []):
            text = strip_html(item.get("description", "")).strip()
            if len(text) < 30:
                continue
            reviews.append({
                "source": "카페",
                "title":  strip_html(item.get("title", "")),
                "review": text[:200],
                "date":   item.get("postdate", ""),
                "link":   item.get("link", ""),
            })

        if rag:
            docs = [
                {
                    "text": f"[{r['source']}] {r['title']} - {r['review']}",
                    "metadata": {"source": r["source"], "product": query},
                }
                for r in reviews
            ]
            asyncio.create_task(rag.add_documents(docs))

        return {"reviews": reviews[:10]}

    except Exception as e:
        return {"reviews": [], "error": str(e)}


@app.get("/api/ai-analysis")
async def get_ai_analysis(query: str = Query(..., min_length=1)):
    try:
        import json
        from groq import AsyncGroq
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

        reviews_result, news_result = await asyncio.gather(
            get_user_reviews(query),
            get_news(query, display=5),
            return_exceptions=True,
        )

        user_reviews = [] if isinstance(reviews_result, Exception) else reviews_result.get("reviews", [])
        news_items   = [] if isinstance(news_result,    Exception) else news_result.get("items",   [])

        # RAG: 수집 데이터를 ChromaDB에 저장
        if rag:
            docs = []
            for r in user_reviews:
                if r.get("review"):
                    docs.append({
                        "text": f"[{r.get('source','')}] {r.get('title','')} - {r.get('review','')}",
                        "metadata": {"source": r.get("source", ""), "product": query},
                    })
            for n in news_items:
                docs.append({
                    "text": f"[뉴스] {n['title']} - {n.get('description','')}",
                    "metadata": {"source": "news", "product": query},
                })
            await rag.add_documents(docs)

        context_parts = []

        # RAG: 쿼리와 관련된 청크만 검색해서 컨텍스트 구성
        if rag:
            rag_chunks = await rag.query(f"{query} 구매 후기 장단점 특징", n_results=8)
            if rag_chunks:
                context_parts.append(
                    f"[RAG 검색 결과 — {query} 관련 문서 {len(rag_chunks)}개]\n"
                    + "\n".join(rag_chunks)
                )

        # RAG 결과가 없으면 기존 방식으로 컨텍스트 구성
        if not context_parts:
            if user_reviews:
                lines = [
                    f"[{r.get('source', '')}] {r.get('title', '')} - {r.get('review', '')[:120]}"
                    for r in user_reviews[:12]
                    if r.get("review")
                ]
                if lines:
                    context_parts.append(f"[실사용자 후기 {len(lines)}개]\n" + "\n".join(lines))

            if news_items:
                lines = [f"- {n['title']}: {n.get('description', '')[:80]}" for n in news_items[:5]]
                context_parts.append("[최신 뉴스]\n" + "\n".join(lines))

        if not context_parts:
            return {"analysis": None, "reviews": [], "error": "분석할 데이터가 부족합니다"}

        res = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 가전제품 전문 구매 분석가입니다. 제공된 실제 구매 리뷰와 뉴스를 분석해서 구매 리포트 JSON을 작성하세요.\n"
                        "규칙:\n"
                        "1. 리뷰에 실제로 언급된 내용만 장단점으로 작성 (추측 금지)\n"
                        "2. pros/cons는 각 2~4개, 구체적으로\n"
                        "3. defects는 여러 리뷰에 반복 언급된 결함만 포함 (없으면 빈 배열)\n"
                        "4. recall은 뉴스에 명시적 리콜 언급이 있을 때만 true\n"
                        "5. score는 리뷰 평점과 내용을 종합해 1.0~5.0 소수점 한 자리\n"
                        "6. suitable_for는 실제 사용 후기 기반 구체적인 사용자 유형\n"
                        "반드시 JSON으로만 응답:\n"
                        '{"score": 4.2, "pros": ["장점1","장점2"], "cons": ["단점1","단점2"], '
                        '"defects": [], "recall": false, '
                        '"suitable_for": "추천 대상 1~2문장", '
                        '"cautions": ["주의사항1","주의사항2"], "summary": "종합 한줄평"}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"제품명: {query}\n\n" + "\n\n".join(context_parts),
                },
            ],
            max_tokens=800,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        analysis = json.loads(res.choices[0].message.content)
        return {"analysis": analysis, "reviews": user_reviews[:10]}

    except Exception as e:
        return {"analysis": None, "reviews": [], "error": str(e)}


_verification_codes: dict[str, dict] = {}

def _send_email_smtp(to_email: str, code: str):
    smtp_user     = os.getenv("SMTP_USER") or os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    if not smtp_user or not smtp_password:
        print(f"\n[DEV] 인증코드 → {to_email} : {code}\n")
        return
    msg = MIMEMultipart()
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg["Subject"] = "[가전무쌍] 이메일 인증코드"
    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0f0f18;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f18;padding:40px 16px;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
        style="background:#1a1a2e;border-radius:20px;border:1px solid rgba(99,102,241,0.25);overflow:hidden;max-width:480px;width:100%;">

        <tr><td style="background:linear-gradient(135deg,#6366f1,#a855f7);padding:32px 40px;text-align:center;">
          <div style="display:inline-flex;align-items:center;gap:10px;">
            <div style="width:32px;height:32px;background:rgba(255,255,255,0.2);border-radius:8px;
              display:inline-flex;align-items:center;justify-content:center;
              font-size:14px;font-weight:900;color:white;">A</div>
            <span style="font-size:20px;font-weight:800;color:white;letter-spacing:-0.5px;">가전무쌍</span>
          </div>
        </td></tr>

        <tr><td style="padding:40px 40px 32px;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:800;color:white;letter-spacing:-0.5px;">
            이메일 인증코드
          </p>
          <p style="margin:0 0 32px;font-size:14px;color:#a0a0b8;line-height:1.6;">
            아래 인증코드를 입력해 이메일을 인증하세요.<br>코드는 <strong style="color:#c4b5fd;">10분간</strong> 유효합니다.
          </p>

          <div style="background:rgba(99,102,241,0.1);border:1.5px solid rgba(99,102,241,0.35);
            border-radius:16px;padding:28px;text-align:center;margin-bottom:32px;">
            <div style="display:flex;justify-content:center;gap:8px;">
              {"".join(f'<span style="display:inline-block;width:44px;height:52px;line-height:52px;background:rgba(255,255,255,0.07);border-radius:10px;font-size:24px;font-weight:800;color:white;text-align:center;">{c}</span>' for c in code)}
            </div>
          </div>

          <p style="margin:0;font-size:12px;color:#6b6b80;line-height:1.6;">
            본인이 요청하지 않은 경우 이 이메일을 무시하세요.<br>
            계정 보안을 위해 인증코드를 타인과 공유하지 마세요.
          </p>
        </td></tr>

        <tr><td style="padding:20px 40px 28px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;font-size:11px;color:#4a4a60;text-align:center;">
            © 2025 가전무쌍 · 국내 가전 트렌드 인사이트
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as s:
            s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.ehlo()
            s.starttls()
            s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())

def _send_rejection_email(to_email: str, company_name: str):
    smtp_user     = os.getenv("SMTP_USER") or os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    if not smtp_user or not smtp_password:
        print(f"\n[DEV] 거절 이메일 → {to_email} ({company_name})\n")
        return
    msg = MIMEMultipart()
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg["Subject"] = "[가전무쌍] 사업자 계정 가입 심사 결과 안내"
    display = company_name or "귀사"
    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0f0f18;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f18;padding:40px 16px;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
        style="background:#1a1a2e;border-radius:20px;border:1px solid rgba(239,68,68,0.25);overflow:hidden;max-width:480px;width:100%;">

        <tr><td style="background:linear-gradient(135deg,#ef4444,#dc2626);padding:32px 40px;text-align:center;">
          <div style="display:inline-flex;align-items:center;gap:10px;">
            <div style="width:32px;height:32px;background:rgba(255,255,255,0.2);border-radius:8px;
              display:inline-flex;align-items:center;justify-content:center;
              font-size:14px;font-weight:900;color:white;">A</div>
            <span style="font-size:20px;font-weight:800;color:white;letter-spacing:-0.5px;">가전무쌍</span>
          </div>
          <p style="margin:16px 0 0;font-size:14px;color:rgba(255,255,255,0.8);">사업자 계정 심사 결과</p>
        </td></tr>

        <tr><td style="padding:36px 40px;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:800;color:white;">심사 결과 안내</p>
          <p style="margin:0 0 24px;font-size:14px;color:#9ca3af;line-height:1.7;">
            <strong style="color:#e5e7eb;">{display}</strong> 사업자 계정 가입 신청을 검토한 결과,<br>
            아쉽게도 이번 심사에서 승인이 어렵게 되었습니다.
          </p>

          <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:14px;padding:20px 24px;margin-bottom:24px;">
            <p style="margin:0;font-size:13px;color:#fca5a5;line-height:1.7;">
              📋 가입 심사 기준에 부합하지 않아 승인이 거절되었습니다.<br>
              문의사항이 있으시면 관리자에게 직접 연락해 주세요.
            </p>
          </div>

          <p style="margin:0;font-size:12px;color:#4a4a60;line-height:1.6;">
            개인(B2C) 계정으로는 언제든지 가입하실 수 있습니다.<br>
            가전무쌍을 이용해 주셔서 감사합니다.
          </p>
        </td></tr>

        <tr><td style="padding:20px 40px 28px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;font-size:11px;color:#4a4a60;text-align:center;">
            © 2025 가전무쌍 · 국내 가전 트렌드 인사이트
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as s:
            s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.ehlo(); s.starttls(); s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())


def _send_approval_email(to_email: str, company_name: str):
    smtp_user     = os.getenv("SMTP_USER") or os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "587"))
    if not smtp_user or not smtp_password:
        print(f"\n[DEV] 승인 이메일 → {to_email} ({company_name})\n")
        return
    msg = MIMEMultipart()
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg["Subject"] = "[가전무쌍] 사업자 계정이 승인되었습니다 🎉"
    display = company_name or "귀사"
    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0f0f18;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f18;padding:40px 16px;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
        style="background:#1a1a2e;border-radius:20px;border:1px solid rgba(99,102,241,0.25);overflow:hidden;max-width:480px;width:100%;">

        <tr><td style="background:linear-gradient(135deg,#6366f1,#a855f7);padding:32px 40px;text-align:center;">
          <div style="display:inline-flex;align-items:center;gap:10px;">
            <div style="width:32px;height:32px;background:rgba(255,255,255,0.2);border-radius:8px;
              display:inline-flex;align-items:center;justify-content:center;
              font-size:14px;font-weight:900;color:white;">A</div>
            <span style="font-size:20px;font-weight:800;color:white;letter-spacing:-0.5px;">가전무쌍</span>
          </div>
          <p style="margin:16px 0 0;font-size:14px;color:rgba(255,255,255,0.8);">사업자 계정 승인 완료</p>
        </td></tr>

        <tr><td style="padding:36px 40px;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:800;color:white;">🎉 승인되었습니다!</p>
          <p style="margin:0 0 24px;font-size:14px;color:#9ca3af;line-height:1.7;">
            <strong style="color:#e5e7eb;">{display}</strong> 사업자 계정이 승인되었습니다.<br>
            이제 가전무쌍의 모든 B2B 기능을 이용하실 수 있습니다.
          </p>

          <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:14px;padding:20px 24px;margin-bottom:24px;">
            <p style="margin:0;font-size:13px;color:#c4b5fd;line-height:1.8;">
              ✅ 가전 트렌드 AI 리포트 이용 가능<br>
              ✅ 제품 비교 분석 이용 가능<br>
              ✅ AI 추천 서비스 이용 가능
            </p>
          </div>

          <p style="margin:0;font-size:12px;color:#4a4a60;line-height:1.6;">
            지금 바로 로그인하여 서비스를 이용해보세요.
          </p>
        </td></tr>

        <tr><td style="padding:20px 40px 28px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;font-size:11px;color:#4a4a60;text-align:center;">
            © 2025 가전무쌍 · 국내 가전 트렌드 인사이트
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as s:
            s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.ehlo(); s.starttls(); s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())


class SendCodeRequest(BaseModel):
    email: str

class VerifyCodeRequest(BaseModel):
    email: str
    code: str

@app.post("/api/auth/send-code")
async def send_code(body: SendCodeRequest):
    import re
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", body.email):
        raise HTTPException(status_code=400, detail="올바른 이메일 주소를 입력해주세요")
    code = str(random.randint(100000, 999999))
    _verification_codes[body.email] = {"code": code, "expires_at": time.time() + 600}
    try:
        await asyncio.to_thread(_send_email_smtp, body.email, code)
    except smtplib.SMTPRecipientsRefused:
        raise HTTPException(status_code=400, detail="존재하지 않는 이메일 주소입니다")
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="메일 서버 인증 오류입니다")
    except Exception as e:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다. 주소를 확인해주세요")
    is_dev = not ((os.getenv("SMTP_USER") or os.getenv("SMTP_EMAIL")) and os.getenv("SMTP_PASSWORD"))
    return {"message": "인증코드가 발송되었습니다", **({"dev_code": code} if is_dev else {})}

@app.post("/api/auth/verify-code")
async def verify_code(body: VerifyCodeRequest):
    stored = _verification_codes.get(body.email)
    if not stored:
        raise HTTPException(status_code=400, detail="인증코드를 먼저 요청해주세요")
    if time.time() > stored["expires_at"]:
        _verification_codes.pop(body.email, None)
        raise HTTPException(status_code=400, detail="인증코드가 만료되었습니다. 재발송해주세요")
    if stored["code"] != body.code:
        raise HTTPException(status_code=400, detail="인증코드가 올바르지 않습니다")
    _verification_codes.pop(body.email, None)
    return {"message": "이메일 인증 완료"}


JWT_SECRET = os.getenv("JWT_SECRET", "changeme-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7

def make_token(user_id: int, user_type: str, role: str = "user") -> str:
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": str(user_id), "type": user_type, "role": role, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def _get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")


async def _require_admin(payload: dict = Depends(_get_current_user)):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다")
    return payload


class SignupB2C(BaseModel):
    email: str
    password: str
    nickname: str

class SignupB2B(BaseModel):
    email: str
    password: str
    company_name: str
    business_type: str
    contact_phone: str

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup/b2c")
async def signup_b2c(body: SignupB2C):
    from app.database import get_user_by_email, create_user, create_b2c_profile
    if await get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다")
    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user_id = await create_user(body.email, hashed, "b2c")
    await create_b2c_profile(user_id, body.nickname)
    return {"token": make_token(user_id, "b2c"), "user_type": "b2c", "nickname": body.nickname}

@app.post("/api/auth/signup/b2b")
async def signup_b2b(body: SignupB2B):
    from app.database import get_user_by_email, create_user, create_b2b_profile
    if await get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다")
    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user_id = await create_user(body.email, hashed, "b2b", status="pending")
    await create_b2b_profile(user_id, body.company_name, body.business_type, body.contact_phone)
    return {"user_type": "b2b", "company_name": body.company_name, "status": "pending"}


@app.post("/api/auth/login")
async def login(body: LoginRequest):
    from app.database import get_user_by_email, fetchone
    user = await get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다")
    if user.get("status") == "pending":
        raise HTTPException(status_code=403, detail="PENDING")
    if user.get("status") == "rejected":
        raise HTTPException(status_code=403, detail="사업자 인증이 거절되었습니다. 관리자에게 문의해주세요")

    extra = {}
    if user["user_type"] == "b2c":
        profile = await fetchone("SELECT nickname FROM user_b2c_profiles WHERE user_id = %s", (user["user_id"],))
        extra["nickname"] = profile["nickname"] if profile else ""
    else:
        profile = await fetchone("SELECT company_name FROM user_b2b_profiles WHERE user_id = %s", (user["user_id"],))
        extra["company_name"] = profile["company_name"] if profile else ""

    return {
        "token": make_token(user["user_id"], user["user_type"], role=user.get("role", "user")),
        "user_type": user["user_type"],
        "role": user.get("role", "user"),
        "status": user.get("status", "active"),
        **extra,
    }


@app.get("/api/admin/pending-users")
async def admin_pending_users(_: dict = Depends(_require_admin)):
    from app.database import fetchall
    rows = await fetchall(
        """
        SELECT u.user_id, u.email, u.status, u.created_at,
               p.company_name, p.business_type, p.contact_phone
        FROM users u
        LEFT JOIN user_b2b_profiles p ON p.user_id = u.user_id
        WHERE u.user_type = 'b2b' AND u.status = 'pending'
        ORDER BY u.created_at DESC
        """,
    )
    return {"users": [dict(r) for r in rows]}


@app.get("/api/admin/b2b-users")
async def admin_all_b2b(status: str = "all", _: dict = Depends(_require_admin)):
    from app.database import fetchall
    where = "u.user_type = 'b2b'"
    if status in ("pending", "active", "rejected"):
        where += f" AND u.status = '{status}'"
    rows = await fetchall(
        f"""
        SELECT u.user_id, u.email, u.status, u.created_at,
               p.company_name, p.business_type, p.contact_phone
        FROM users u
        LEFT JOIN user_b2b_profiles p ON p.user_id = u.user_id
        WHERE {where}
        ORDER BY
          FIELD(u.status, 'pending', 'active', 'rejected'),
          u.created_at DESC
        """,
    )
    result = [dict(r) for r in rows]
    counts = {"pending": 0, "active": 0, "rejected": 0, "total": len(result)}
    for r in result:
        s = r.get("status", "")
        if s in counts:
            counts[s] += 1
    return {"users": result, "counts": counts}


@app.post("/api/admin/users/{user_id}/approve")
async def admin_approve_user(user_id: int, _: dict = Depends(_require_admin)):
    from app.database import execute, fetchone
    user = await fetchone("SELECT user_id FROM users WHERE user_id = %s AND user_type = 'b2b'", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    user_row    = await fetchone("SELECT email FROM users WHERE user_id = %s", (user_id,))
    company_row = await fetchone("SELECT company_name FROM user_b2b_profiles WHERE user_id = %s", (user_id,))
    await execute("UPDATE users SET status = 'active' WHERE user_id = %s", (user_id,))
    if user_row:
        await asyncio.to_thread(
            _send_approval_email,
            user_row["email"],
            company_row["company_name"] if company_row else ""
        )
    return {"message": "승인 완료"}


@app.post("/api/admin/users/{user_id}/reject")
async def admin_reject_user(user_id: int, _: dict = Depends(_require_admin)):
    from app.database import execute, fetchone
    user = await fetchone("SELECT user_id FROM users WHERE user_id = %s AND user_type = 'b2b'", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    user_row    = await fetchone("SELECT email FROM users WHERE user_id = %s", (user_id,))
    company_row = await fetchone("SELECT company_name FROM user_b2b_profiles WHERE user_id = %s", (user_id,))
    await execute("UPDATE users SET status = 'rejected' WHERE user_id = %s", (user_id,))
    if user_row:
        await asyncio.to_thread(
            _send_rejection_email,
            user_row["email"],
            company_row["company_name"] if company_row else ""
        )
    return {"message": "거절 완료"}


@app.get("/api/user/me")
async def get_my_profile(payload: dict = Depends(_get_current_user)):
    from app.database import fetchone as db_fetchone
    user_id = int(payload["sub"])
    user = await db_fetchone("SELECT user_id, email, user_type, role, status, created_at FROM users WHERE user_id = %s", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    profile = {}
    if user["user_type"] == "b2c":
        row = await db_fetchone("SELECT nickname FROM user_b2c_profiles WHERE user_id = %s", (user_id,))
        profile = {"nickname": row["nickname"] if row else ""}
    else:
        row = await db_fetchone("SELECT company_name, business_type, contact_phone FROM user_b2b_profiles WHERE user_id = %s", (user_id,))
        if row:
            profile = {
                "company_name":  row["company_name"],
                "business_type": row["business_type"],
                "contact_phone": row["contact_phone"],
            }

    return {
        "user_id":    user["user_id"],
        "email":      user["email"],
        "user_type":  user["user_type"],
        "role":       user.get("role", "user"),
        "status":     user.get("status", "active"),
        "created_at": str(user["created_at"]) if user.get("created_at") else None,
        **profile,
    }


class AlertCreate(BaseModel):
    product_name: str
    target_price: float
    current_price: float
    product_url: str = ""
    alert_type: str = "below"

@app.get("/api/user/alerts")
async def get_my_alerts(payload: dict = Depends(_get_current_user)):
    from app.database import get_user_alerts
    user_id = int(payload["sub"])
    rows = await get_user_alerts(user_id)
    return {"alerts": [dict(r) for r in rows]}

@app.post("/api/user/alerts")
async def create_my_alert(body: AlertCreate, payload: dict = Depends(_get_current_user)):
    from app.database import create_alert, fetchall
    user_id = int(payload["sub"])
    existing = await fetchall(
        "SELECT alert_id FROM price_alert WHERE user_id=%s AND product_name=%s AND is_active=1",
        (user_id, body.product_name),
    )
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 알림입니다")
    alert_id = await create_alert(
        user_id, body.product_name, body.target_price,
        body.current_price, body.product_url, body.alert_type,
    )
    return {"alert_id": alert_id, "message": "알림이 등록됐습니다"}

@app.delete("/api/user/alerts/{alert_id}")
async def delete_my_alert(alert_id: int, payload: dict = Depends(_get_current_user)):
    from app.database import execute, fetchone
    user_id = int(payload["sub"])
    row = await fetchone(
        "SELECT alert_id FROM price_alert WHERE alert_id=%s AND user_id=%s",
        (alert_id, user_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")
    await execute("UPDATE price_alert SET is_active=0 WHERE alert_id=%s", (alert_id,))
    return {"message": "알림이 삭제됐습니다"}


@app.get("/api/ai-compare")
async def ai_compare(
    q1: str = Query(..., min_length=1),
    q2: str = Query(..., min_length=1),
    _payload: dict = Depends(_get_current_user),
):
    try:
        import json
        from groq import AsyncGroq
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

        r1, r2, n1, n2 = await asyncio.gather(
            get_user_reviews(q1),
            get_user_reviews(q2),
            get_news(q1, display=3),
            get_news(q2, display=3),
            return_exceptions=True,
        )

        def fmt_ctx(reviews_res, news_res, name):
            parts = [f"=== 제품: {name} ==="]
            reviews = [] if isinstance(reviews_res, Exception) else reviews_res.get("reviews", [])
            news    = [] if isinstance(news_res,    Exception) else news_res.get("items", [])
            if reviews:
                lines = [f"- {r.get('title','')} | {r.get('review','')[:100]}"
                         for r in reviews[:8] if r.get("review")]
                if lines:
                    parts.append("실사용 리뷰:\n" + "\n".join(lines))
            if news:
                parts.append("관련 뉴스:\n" + "\n".join(f"- {n['title']}" for n in news[:3]))
            return "\n".join(parts)

        # RAG: 수집 데이터 저장
        if rag:
            docs = []
            for reviews_res, product_name in [(r1, q1), (r2, q2)]:
                reviews_list = [] if isinstance(reviews_res, Exception) else reviews_res.get("reviews", [])
                for r in reviews_list:
                    if r.get("review"):
                        docs.append({
                            "text": f"[{r.get('source','')}] {r.get('title','')} - {r.get('review','')}",
                            "metadata": {"source": r.get("source", ""), "product": product_name},
                        })
            await rag.add_documents(docs)

            # RAG: 두 제품 각각 관련 청크 검색
            chunks1, chunks2 = await asyncio.gather(
                rag.query(f"{q1} 특징 장단점 후기", n_results=5),
                rag.query(f"{q2} 특징 장단점 후기", n_results=5),
            )

            def fmt_rag(chunks, name):
                if not chunks:
                    return ""
                return f"=== {name} 관련 문서 ===\n" + "\n".join(chunks)

            context = fmt_rag(chunks1, q1) + "\n\n" + fmt_rag(chunks2, q2)
            if not context.strip():
                context = fmt_ctx(r1, n1, q1) + "\n\n" + fmt_ctx(r2, n2, q2)
        else:
            context = fmt_ctx(r1, n1, q1) + "\n\n" + fmt_ctx(r2, n2, q2)

        res = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 가전제품 전문 비교 분석가입니다. 두 제품의 리뷰와 뉴스를 분석해 비교 리포트 JSON을 작성하세요.\n"
                        "규칙:\n"
                        "1. 실제 언급된 내용만 장단점으로 (추측 금지)\n"
                        "2. pros/cons 각 2~3개, 구체적으로\n"
                        "3. winner는 0(첫번째 제품) 또는 1(두번째 제품) 또는 null(무승부)\n"
                        "4. 모든 텍스트는 반드시 한국어로\n"
                        "반드시 아래 JSON만 응답:\n"
                        '{"products":[{"pros":["장점1","장점2"],"cons":["단점1","단점2"],"score":4.2,"summary":"한줄요약"},{"pros":["장점1"],"cons":["단점1"],"score":3.8,"summary":"한줄요약"}],'
                        '"winner":0,"winner_reason":"승자 선택 이유 한 문장","verdict":"어떤 사용자에게 어떤 제품이 적합한지 2문장"}'
                    ),
                },
                {"role": "user", "content": f"비교 대상:\n제품1: {q1}\n제품2: {q2}\n\n수집 데이터:\n{context}"},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        raw = res.choices[0].message.content.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        return data
    except Exception as e:
        return {
            "products": [
                {"pros": [], "cons": [], "score": None, "summary": "분석 실패"},
                {"pros": [], "cons": [], "score": None, "summary": "분석 실패"},
            ],
            "winner": None,
            "winner_reason": "",
            "verdict": "AI 분석 중 오류가 발생했습니다.",
            "error": str(e),
        }


@app.get("/api/b2b/dashboard")
async def get_b2b_dashboard(category: str = Query(..., min_length=1), period: str = "3m"):
    from groq import AsyncGroq

    days_map = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    days = days_map.get(period, 90)
    time_unit = "week" if days > 30 else "date"
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dl_headers = {**NAVER_HEADERS, "Content-Type": "application/json"}

    async def fetch_trend():
        body = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "timeUnit": time_unit,
            "keywordGroups": [
                {
                    "groupName": category,
                    "keywords": [category],
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://openapi.naver.com/v1/datalab/search",
                    json=body,
                    headers=dl_headers,
                )

            if resp.status_code != 200:
                print("[DATALAB ERROR]", resp.status_code, resp.text)
                return []

            data = resp.json()
            results = data.get("results", [])

            return results[0]["data"] if results else []

        except Exception as e:
            print("[DATALAB EXCEPTION]", e)
            return []

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
            "endDate": end_date.strftime("%Y-%m-%d"),
            "timeUnit": "month",
            "keywordGroups": [{"groupName": category, "keywords": [category]}],
            "ages": age_codes_list,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://openapi.naver.com/v1/datalab/search", json=body, headers=dl_headers)
        results = resp.json().get("results", [])
        data = results[0]["data"] if results else []
        return sum(d["ratio"] for d in data) / len(data) if data else 0.0

    async def fetch_keywords():
        products = await search_products(
            query=category,
            page=1,
            display=40,
            sort="sim",
            category=category
        )
        items = products.get("items", [])

        STOP = {
            "미포함", "포함", "수도권", "설치비포함", "설치비별도", "방문설치",
            "무료설치", "무료", "별도", "이하", "이상", "할인", "택배", "직접",
            "기사", "배송", "셀프", "자가설치", "평", "인치", "대한", "공식"
        }

        def extract_words(target_items):
            scores = {}

            def add(w, weight=1):
                w = (w or "").strip()
                if not w or w == category:
                    return
                if len(w) < 2:
                    return
                if any(c.isdigit() for c in w):
                    return
                if w in STOP:
                    return
                scores[w] = scores.get(w, 0) + weight

            for it in target_items:
                add(it.get("brand") or "", 3)

                title = re.sub(r"[^\w가-힣]", " ", it.get("title") or "")
                for tok in title.split():
                    add(tok, 1)

            return scores

        half = max(len(items) // 2, 1)
        recent_scores = extract_words(items[:half])
        old_scores = extract_words(items[half:])

        all_words = set(recent_scores) | set(old_scores)

        rising = []
        falling = []

        for word in all_words:
            recent = recent_scores.get(word, 0)
            old = old_scores.get(word, 0)
            diff = recent - old

            if recent > 0 and diff >= 0:
                rising.append((word, recent + diff))

            if old > 0 and diff < 0:
                falling.append((word, old + abs(diff)))

        rising.sort(key=lambda x: x[1], reverse=True)
        falling.sort(key=lambda x: x[1], reverse=True)

        all_keywords = sorted(recent_scores.items(), key=lambda x: x[1], reverse=True)

        seasonal = all_keywords[3:9] if len(all_keywords) > 3 else all_keywords

        return {
            "all": [w for w, _ in all_keywords[:24]],
            "rising": [w for w, _ in rising[:6]],
            "falling": [w for w, _ in falling[:6]],
            "seasonal": [w for w, _ in seasonal[:6]],
        }

    async def fetch_pain_points():
        try:
            import json
            from groq import AsyncGroq

            reviews_result = await get_user_reviews(category)
            reviews = reviews_result.get("reviews", [])

            if not reviews:
                return {
                    "top": [],
                    "suggestions": [],
                    "sources": []
                }

            review_text = "\n".join(
                [
                    f"- [{r.get('source', '')}] {r.get('title', '')}: {r.get('review', '')}"
                    for r in reviews[:10]
                    if r.get("review")
                ]
            )

            groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

            res = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 가전제품 소비자 후기 분석가입니다. "
                            "제공된 실제 후기에서 반복적으로 나타나는 불만 키워드 TOP 5와 개선 제안을 추출하세요. "
                            "후기에 없는 내용은 절대 추측하지 마세요. "
                            "반드시 JSON으로만 응답하세요. "
                            '{"top":[{"keyword":"불만키워드","count":1,"reason":"근거 요약"}],'
                            '"suggestions":["개선 제안1","개선 제안2"]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"카테고리: {category}\n\n[실사용자 후기]\n{review_text}",
                    },
                ],
                max_tokens=500,
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            parsed = json.loads(res.choices[0].message.content)

            return {
                "top": parsed.get("top", [])[:5],
                "suggestions": parsed.get("suggestions", [])[:5],
                "sources": [
                    {
                        "source": r.get("source", ""),
                        "title": r.get("title", ""),
                        "link": r.get("link", "")
                    }
                    for r in reviews[:5]
                ]
            }

        except Exception as e:
            print("[pain_points error]", e)
            return {
                "top": [],
                "suggestions": [],
                "sources": []
            }

    # Naver DataLab 연령 코드: 2=10대, 3·4=20대, 5·6=30대, 7·8=40대, 9·10·11=50대+
    age_groups = [["2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10", "11"]]
    age_labels = ["10대", "20대", "30대", "40대", "50대+"]

    results = await asyncio.gather(
        fetch_trend(),
        fetch_brand_share(),
        *[fetch_age(g) for g in age_groups],
        fetch_keywords(),
        fetch_pain_points(),
        return_exceptions=True,
    )

    trend_data = results[0] if not isinstance(results[0], Exception) else []
    brand_data = results[1] if not isinstance(results[1], Exception) else []
    age_raw    = [r if not isinstance(r, Exception) else 0.0 for r in results[2:7]]
    keyword_result = results[7] if not isinstance(results[7], Exception) else {
        "all": [],
        "rising": [],
        "falling": [],
        "seasonal": [],
    }
    pain_points = results[8] if not isinstance(results[8], Exception) else {
    "top": [],
    "suggestions": [],
    "sources": [],
    }

    keywords = keyword_result.get("all", [])
    trend_drivers = {
        "rising": keyword_result.get("rising", []),
        "falling": keyword_result.get("falling", []),
        "seasonal": keyword_result.get("seasonal", []),
    }

    age_total = sum(age_raw)
    age_dist = [
        {"label": lbl, "value": round(v, 1), "pct": round(v / age_total * 100) if age_total else 0}
        for lbl, v in zip(age_labels, age_raw)
    ]

    ratios = [d["ratio"] for d in trend_data]
    current  = round(ratios[-1], 1) if ratios else 0
    avg_val  = round(sum(ratios) / len(ratios), 1) if ratios else 0
    half     = len(ratios) // 2
    old_avg  = sum(ratios[:half]) / max(half, 1)
    new_avg  = sum(ratios[half:]) / max(len(ratios) - half, 1)
    growth   = round((new_avg - old_avg) / max(old_avg, 1) * 100, 1)
    risk     = "낮음" if growth > -15 else ("중간" if growth > -30 else "높음")

    summary = f"{category} 시장의 최근 {period} 트렌드 데이터를 분석한 결과입니다."
    try:
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        top3 = ", ".join(f"{b['brand']} {b['pct']}%" for b in brand_data[:3]) or "데이터 부족"
        top_age = max(age_dist, key=lambda x: x["value"])["label"] if age_dist else "30대"

        # RAG: 해당 카테고리 소비자 반응 검색
        rag_context = ""
        if rag:
            chunks = await rag.query(f"{category} 소비자 반응 트렌드 구매 후기", n_results=6)
            if chunks:
                rag_context = "\n[소비자 실반응 데이터]\n" + "\n".join(f"- {c[:120]}" for c in chunks)

        prompt = (
            f"[{category} 시장 B2B 분석]\n"
            f"- 검색 관심도: 현재 {current} / 기간 평균 {avg_val}\n"
            f"- {period} 성장률: {'+' if growth >= 0 else ''}{growth}%\n"
            f"- 주요 브랜드: {top3}\n"
            f"- 주 관심층: {top_age}\n"
            f"{rag_context}\n"
            f"위 데이터를 바탕으로 {category} 시장의 미래 전망과 B2B 사업 기회를 2~3문장으로 작성하세요. 한국어만 사용."
        )
        res = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "당신은 B2B 가전 시장 분석 전문가입니다. 간결하고 전문적으로 작성하세요."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            temperature=0.4,
        )
        summary = res.choices[0].message.content.strip()
    except Exception:
        pass

    return {
        "category": category,
        "period": period,
        "trend": trend_data,
        "brands": brand_data,
        "age_distribution": age_dist,
        "keywords": keywords,
        "trend_drivers": trend_drivers,
        "pain_points": pain_points,
        "market_report": {
            "trend_score": current,
            "avg_score": avg_val,
            "growth_rate": growth,
            "risk": risk,
            "summary": summary,
        },
    }


@app.get("/api/price-position")
async def get_price_position(
    category: str = Query(..., min_length=1),
    price:    int = Query(0),
):
    from app.database import fetchall

    rows = await fetchall(
        "SELECT snapshot_date, avg_price, min_price, max_price "
        "FROM price_history WHERE category = %s ORDER BY snapshot_date DESC LIMIT 2",
        (category,),
    )
    if not rows:
        return {"available": False}

    latest    = rows[0]
    avg_price = latest["avg_price"]
    min_price = latest["min_price"]
    max_price = latest["max_price"]

    price_range      = max(max_price - min_price, 1)
    position_pct     = max(0, min(100, round((price - min_price) / price_range * 100)))
    avg_position_pct = max(0, min(100, round((avg_price - min_price) / price_range * 100)))

    vs_avg_pct = round((price - avg_price) / max(avg_price, 1) * 100, 1) if price > 0 else None

    if price == 0 or vs_avg_pct is None:
        signal_type, signal = "neutral", "가격 정보 없음"
        reason = "현재 가격 정보를 확인할 수 없습니다"
    elif vs_avg_pct <= -5:
        signal_type, signal = "buy", "구매 추천"
        reason = f"카테고리 평균보다 {abs(vs_avg_pct):.1f}% 저렴합니다. 지금이 구매하기 좋은 시기입니다."
    elif vs_avg_pct >= 5:
        signal_type, signal = "wait", "관망 권장"
        reason = f"카테고리 평균보다 {vs_avg_pct:.1f}% 비쌉니다. 가격이 내려갈 때까지 기다려보세요."
    else:
        signal_type, signal = "neutral", "적정가"
        reason = f"카테고리 평균 수준의 가격입니다."

    return {
        "available":        True,
        "avg_price":        avg_price,
        "min_price":        min_price,
        "max_price":        max_price,
        "position_pct":     position_pct,
        "avg_position_pct": avg_position_pct,
        "vs_avg_pct":       vs_avg_pct,
        "signal":           signal,
        "signal_type":      signal_type,
        "reason":           reason,
        "snapshot_date":    str(latest["snapshot_date"]),
    }


def _fmt_price_label(won: int) -> str:
    if won >= 10000:
        return f"{won // 10000}만"
    return str(won)


@app.get("/api/b2b/price")
async def get_price_intelligence(category: str = Query(..., min_length=1)):
    import json as _json
    from app.database import fetchall, execute as db_exec

    today = date.today()

    # 1. 네이버 쇼핑에서 제품 수집 (필터 적용)
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

    # 2. 브랜드별 가격 통계
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

    # 3. 가격대별 분포 (5구간)
    rng  = max_price - min_price if max_price > min_price else 1
    step = rng / 5
    distribution = []
    for i in range(5):
        lo = int(min_price + i * step)
        hi = int(min_price + (i + 1) * step) if i < 4 else max_price + 1
        cnt = sum(1 for p in prices if lo <= p < hi)
        if i < 4:
            label = f"{_fmt_price_label(lo)}~{_fmt_price_label(hi)}"
        else:
            label = f"{_fmt_price_label(lo)}+"
        distribution.append({"range": label, "count": cnt, "lo": lo})
    # 마지막 버킷 hi 보정
    distribution[-1]["hi"] = None

    # 4. 최저가 TOP 10
    top_deals = sorted(items, key=lambda x: x["price"])[:10]

    # 5. DB 스냅샷 저장 (당일 upsert)
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
    except Exception:
        pass

    # 6. 히스토리 조회 (최근 30일)
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

    # 7. 전일 대비 가격 변동
    price_change_pct = None
    if len(price_history) >= 2:
        prev = price_history[-2]["avg_price"]
        curr = price_history[-1]["avg_price"]
        price_change_pct = round((curr - prev) / max(prev, 1) * 100, 1)

    return {
        "category":     category,
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
    }


@app.get("/api/b2b/product-price")
async def get_product_price(title: str = Query(..., min_length=1)):
    import json as _json
    from app.database import fetchall, execute as db_exec

    today = date.today()

    # 1. 모델번호 자동 추출 → 없으면 타이틀 정규화를 키로 사용
    model = extract_model_number(title)
    product_key = model if model else re.sub(r'\s+', ' ', title.strip())[:100]

    # 2. Naver Shopping에서 이 모델/제품명으로 검색
    search_q = model if model else title
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            NAVER_SHOP_URL,
            headers=NAVER_HEADERS,
            params={"query": search_q, "display": 50, "sort": "sim"},
        )

    items_raw = resp.json().get("items", []) if resp.status_code == 200 else []

    # 3. 가격 있는 항목만, 의미없는 가격 0 제외
    items = [
        {
            "mall":  strip_html(it.get("mallName", "")),
            "title": strip_html(it["title"]),
            "price": int(it["lprice"]),
            "link":  it.get("link", ""),
        }
        for it in items_raw
        if it.get("lprice") and int(it["lprice"]) > 0
    ]

    if not items:
        return {"available": False, "product_key": product_key, "model_number": model}

    # 이상치 제거: 중앙값 기준 20% 미만 또는 500% 초과 가격은 부품/악세서리로 간주
    raw_prices = sorted(it["price"] for it in items)
    median_price = raw_prices[len(raw_prices) // 2]
    items = [
        it for it in items
        if median_price * 0.2 <= it["price"] <= median_price * 5
    ]

    if not items:
        return {"available": False, "product_key": product_key, "model_number": model}

    prices = [it["price"] for it in items]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = int(sum(prices) / len(prices))

    # 4. Price Positioning
    brand_prices = [b["avg_price"] for b in by_brand if b.get("avg_price")]

    price_positioning = {
        "premium": [],
        "mid": [],
        "budget": [],
    }

    if brand_prices:
        min_brand_price = min(brand_prices)
        max_brand_price = max(brand_prices)
        gap = max(max_brand_price - min_brand_price, 1)

        for b in by_brand:
            score = (b["avg_price"] - min_brand_price) / gap

            item = {
                "brand": b["brand"],
                "avg_price": b["avg_price"],
                "count": b["count"],
            }

            if score >= 0.66:
                price_positioning["premium"].append(item)
            elif score >= 0.33:
                price_positioning["mid"].append(item)
            else:
                price_positioning["budget"].append(item)

    # 5. DB 스냅샷 저장 (당일 upsert)
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
    except Exception:
        pass

    # 6. 이 제품 히스토리 조회 (최근 30일)
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

    # 7. 구매 신호 계산
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
        reason = f"현재 가격이 평소 수준입니다."

    return {
        "available":      True,
        "product_key":    product_key,
        "model_number":   model,
        "min_price":      min_price,
        "max_price":      max_price,
        "avg_price":      avg_price,
        "hist_avg_price": hist_avg,
        "hist_min_price": hist_min,
        "price_positioning": price_positioning,
        "price_history":  price_history,
        "signal":         signal,
        "signal_type":    signal_type,
        "reason":         reason,
        "snapshot_date":  str(today),
    }


# ── 카테고리 키워드 맵 ──────────────────────────────────────────────
_CATEGORY_MAP = {
    '냉장고': '냉장고', '김치냉장고': '냉장고',
    '세탁기': '세탁기', '건조기': '건조기',
    '에어컨': '에어컨', '시스템에어컨': '에어컨',
    '공기청정기': '공기청정기',
    '로봇청소기': '로봇청소기', '청소기': '청소기',
    '식기세척기': '식기세척기',
    'TV': 'TV', '텔레비전': 'TV', '티비': 'TV',
    '에어프라이어': '에어프라이어',
    '밥솥': '전기밥솥', '전기밥솥': '전기밥솥',
    '전자레인지': '전자레인지',
    '커피머신': '커피머신',
    '가습기': '가습기', '제습기': '제습기',
    '선풍기': '선풍기', '히터': '전기히터',
    '헤어드라이어': '헤어드라이어',
    '사운드바': '사운드바', '스피커': '블루투스 스피커',
}

_POS_WORDS = ['좋', '만족', '추천', '훌륭', '최고', '편리', '깔끔', '빠름', '조용', '완벽', '괜찮', '가성비', '예쁘', '튼튼', '탁월', '우수']
_NEG_WORDS = ['아쉽', '실망', '불만', '문제', '고장', '소음', '느림', '비쌈', '불편', '나쁨', '최악', '반품', '환불', '하자', '불량']
_STOP = {'있어', '이렇게', '그리고', '하지만', '있는', '하는', '있고', '않아', '것이', '수도', '이나', '이제', '이것', '에서', '으로', '부터', '같이', '때문', '이라', '하고', '에도', '까지', '이라고', '이런', '정도', '이상', '라서'}


@app.get("/api/b2b/product-analysis")
async def get_product_analysis(q: str = Query(..., min_length=1)):
    """B2B 전용: 제품 하나에 대한 종합 분석 (가격·트렌드·리뷰·경쟁)."""
    import json as _json
    from collections import Counter
    from app.database import fetchall

    today = date.today()
    model = extract_model_number(q)
    product_key = model if model else re.sub(r'\s+', ' ', q.strip())[:100]
    search_q = model if model else q

    # 카테고리 감지
    detected_category = None
    for kw, cat in _CATEGORY_MAP.items():
        if kw in q:
            detected_category = cat
            break

    # ── 1. 가격 (Naver Shopping) ─────────────────────────────────────
    async def _fetch_price():
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(NAVER_SHOP_URL, headers=NAVER_HEADERS,
                    params={"query": search_q, "display": 50, "sort": "sim"})
            items_raw = resp.json().get("items", []) if resp.status_code == 200 else []
            items = [
                {"mall": strip_html(it.get("mallName", "")), "price": int(it["lprice"]), "link": it.get("link", "")}
                for it in items_raw if it.get("lprice") and int(it["lprice"]) > 0
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
        except Exception:
            return None

    # ── 2. 트렌드 (DataLab 90일 주단위) ──────────────────────────────
    async def _fetch_trend():
        try:
            category_query = category if category else q

            result = await get_datalab(category_query)
            data = result.get("data", [])

            if data:
                return data

            # 그래도 비면 q로 한 번 더 시도
            result = await get_datalab(q)
            return result.get("data", [])

        except Exception as e:
            print("[B2B TREND ERROR]", e)
            return []

    # ── 3. 리뷰 + 감성 (블로그·카페) ─────────────────────────────────
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
                if len(txt) < 30: continue
                reviews.append({"source": "블로그", "title": strip_html(it["title"]),
                                 "review": txt[:200], "link": it.get("link", "")})
            for it in cafe_r.json().get("items", []):
                txt = strip_html(it.get("description", "")).strip()
                if len(txt) < 30: continue
                reviews.append({"source": "카페", "title": strip_html(it["title"]),
                                 "review": txt[:200], "link": it.get("link", "")})
            return reviews[:12]
        except Exception:
            return []

    # ── 4. 경쟁 제품 (카테고리 상위 제품) ───────────────────────────
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
            # 브랜드별 최저가 1개씩
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

    # ── 병렬 실행 ─────────────────────────────────────────────────────
    price_data, trend_data, reviews, competitors = await asyncio.gather(
        _fetch_price(), _fetch_trend(), _fetch_reviews(), _fetch_competitors(),
        return_exceptions=True,
    )
    price_data  = price_data  if not isinstance(price_data,  Exception) else None
    trend_data  = trend_data  if not isinstance(trend_data,  Exception) else []
    reviews     = reviews     if not isinstance(reviews,     Exception) else []
    competitors = competitors if not isinstance(competitors, Exception) else []

    # ── 감성 분석 ─────────────────────────────────────────────────────
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
