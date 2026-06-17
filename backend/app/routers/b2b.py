import asyncio
import re
from collections import Counter
from datetime import date, timedelta, datetime

import httpx
from fastapi import APIRouter, Query

from app.config import NAVER_HEADERS, NAVER_SHOP_URL, _CATEGORY_MAP, _POS_WORDS, _NEG_WORDS, _STOP
from app.utils.helpers import strip_html, extract_model_number, fmt_price_label
from app.routers.naver import search_products, get_datalab

router = APIRouter(prefix="/api/b2b", tags=["b2b"])


@router.get("/dashboard")
async def get_b2b_dashboard(category: str = Query(..., min_length=1), period: str = "3m"):
    import os
    from groq import AsyncGroq
    from app.dependencies import get_rag_optional
    rag = get_rag_optional()
    from app.routers.analysis import get_trend

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
        trend = await get_trend(category=category)
        items = trend.get("items", [])
        kws: list[str] = []
        seen: set[str] = set()

        def add(w: str):
            w = w.strip()
            if w and w not in seen and w != category:
                seen.add(w)
                kws.append(w)

        for it in items:
            for tag in (it.get("tag") or "").split(","):
                add(tag)
        for it in items:
            add(it.get("brand") or "")

        STOP = {"미포함", "포함", "수도권", "설치비포함", "설치비별도", "방문설치",
                "무료설치", "무료", "별도", "이하", "이상", "할인", "택배", "직접",
                "기사", "배송", "셀프", "자가설치", "원룸", "평", "인치"}

        for it in items:
            title = re.sub(r'[^\w가-힣]', ' ', it.get("title") or "")
            for tok in title.split():
                if (len(tok) >= 2 and not any(c.isdigit() for c in tok)
                        and tok not in seen and tok not in STOP):
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
    risk     = "낮음" if growth > -15 else ("중간" if growth > -30 else "높음")

    summary = f"{category} 시장의 최근 {period} 트렌드 데이터를 분석한 결과입니다."
    try:
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        top3 = ", ".join(f"{b['brand']} {b['pct']}%" for b in brand_data[:3]) or "데이터 부족"
        top_age = max(age_dist, key=lambda x: x["value"])["label"] if age_dist else "30대"

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
        "period":   period,
        "trend":    trend_data,
        "brands":   brand_data,
        "age_distribution": age_dist,
        "keywords": keywords,
        "market_report": {
            "trend_score": current,
            "avg_score":   avg_val,
            "growth_rate": growth,
            "risk":        risk,
            "summary":     summary,
        },
    }


@router.get("/price")
async def get_price_intelligence(category: str = Query(..., min_length=1)):
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

    top_deals = sorted(items, key=lambda x: x["price"])[:10]

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
    }


@router.get("/product-price")
async def get_product_price(title: str = Query(..., min_length=1)):
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
    except Exception:
        pass

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
async def get_product_analysis(q: str = Query(..., min_length=1)):
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
        except Exception:
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
        except Exception:
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
