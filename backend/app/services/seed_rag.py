import asyncio
import httpx
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rag_service import RAGService

_CATEGORIES = [
    "에어컨", "냉장고", "세탁기", "건조기", "공기청정기",
    "로봇청소기", "식기세척기", "에어프라이어", "TV", "전기밥솥",
]

_NAVER_HEADERS: dict = {}


def _init_headers():
    import os
    _NAVER_HEADERS["X-Naver-Client-Id"] = os.getenv("NAVER_CLIENT_ID", "")
    _NAVER_HEADERS["X-Naver-Client-Secret"] = os.getenv("NAVER_CLIENT_SECRET", "")


async def _fetch_news(session: httpx.AsyncClient, category: str) -> list[dict]:
    try:
        resp = await session.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=_NAVER_HEADERS,
            params={"query": f"{category} 트렌드 후기", "display": 8, "sort": "date"},
            timeout=8.0,
        )
        items = resp.json().get("items", [])
        return [
            {
                "text": f"[뉴스] {_strip(it['title'])} - {_strip(it.get('description',''))}",
                "metadata": {"source": "news", "product": category},
            }
            for it in items
            if it.get("title")
        ]
    except Exception:
        return []


async def _fetch_products(session: httpx.AsyncClient, category: str) -> list[dict]:
    try:
        resp = await session.get(
            "https://openapi.naver.com/v1/search/shop.json",
            headers=_NAVER_HEADERS,
            params={"query": category, "display": 10, "sort": "sim"},
            timeout=8.0,
        )
        items = resp.json().get("items", [])
        docs = []
        for it in items:
            title = _strip(it.get("title", ""))
            brand = it.get("brand") or it.get("maker", "")
            price = it.get("lprice", "")
            review = it.get("reviewCount", "")
            score = it.get("reviewScore", "")
            if not title:
                continue
            text = f"[쇼핑] {title}"
            if brand:
                text += f" | 브랜드: {brand}"
            if price:
                text += f" | 가격: {int(price):,}원"
            if score:
                text += f" | 평점: {score}/5 (리뷰 {review}개)"
            docs.append({"text": text, "metadata": {"source": "shop", "product": category}})
        return docs
    except Exception:
        return []


def _strip(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


async def seed(rag: "RAGService") -> None:
    if rag.collection.count() > 0:
        print(f"[RAG] 이미 {rag.collection.count()}개 문서 존재 — 시드 생략")
        return

    print("[RAG] 초기 데이터 시딩 시작...")
    _init_headers()

    async with httpx.AsyncClient() as session:
        for category in _CATEGORIES:
            news_docs, product_docs = await asyncio.gather(
                _fetch_news(session, category),
                _fetch_products(session, category),
            )
            docs = news_docs + product_docs
            if docs:
                await rag.add_documents(docs)
                print(f"[RAG] {category}: {len(docs)}개 추가")
            await asyncio.sleep(0.3)

    print(f"[RAG] 시딩 완료 — 총 {rag.collection.count()}개 문서")
