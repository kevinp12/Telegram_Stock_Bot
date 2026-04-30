"""market_api.py
市場資料調度層：Finnhub、Yahoo Finance、NewsAPI。
"""
from __future__ import annotations

import logging
from typing import Any

import requests
import yfinance as yf

try:
    import finnhub
except Exception:
    finnhub = None

import ai_core
from config import FINNHUB_KEY, NEWS_API_KEY


finnhub_client = None
if finnhub and FINNHUB_KEY:
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_KEY)
    except Exception as exc:
        logging.warning("Finnhub 初始化失敗: %s", exc)

# 新增 NewsAPI 金鑰檢查
if not NEWS_API_KEY:
    logging.warning("NEWS_API_KEY 未設定。部分新聞功能可能無法正常運作。請檢查 .env 檔案。")

# 新增 NewsAPI 金鑰檢查
if not NEWS_API_KEY:
    logging.warning("NEWS_API_KEY 未設定。部分新聞功能可能無法正常運作。請檢查 .env 檔案。")

def get_ticker_mapping(name: str, source: str = "finnhub") -> str:
    if source == "yahoo":
        mapping = {
            "標普500": "^GSPC",
            "納斯達克": "^NDX",
            "黃金": "GC=F",
            "原油": "BZ=F",
            "比特幣": "BTC-USD",
            "VIX": "^VIX",
        }
    else:
        mapping = {
            "標普500": "OANDA:SPX500_USD",
            "納斯達克": "OANDA:NAS100_USD",
            "黃金": "OANDA:XAU_USD",
            "原油": "OANDA:BCO_USD",
            "比特幣": "BINANCE:BTCUSDT",
            "VIX": "VIX",
        }
    return mapping.get(name, name.upper())


SPECIAL_NEWS_TOPICS = {
    "GOLD": "黃金",
    "黄金": "黃金",
    "OIL": "原油",
    "CRUDE": "原油",
    "BRENT": "原油",
    "WTI": "原油",
    "BTC": "比特幣",
    "BITCOIN": "比特幣",
    "SP500": "標普500",
    "S&P500": "標普500",
    "NASDAQ": "納斯達克",
    "VIX": "VIX",
}

NEWS_SEARCH_SOURCES = [
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "seekingalpha.com",
    "tradingview.com",
    "marketwatch.com",
    "jin10.com",
]

NEWS_SOURCE_ALIASES = {
    "TV": "TradingView",
    "TRADINGVIEW": "TradingView",
    "TW": "TradingView",
    "REUTERS": "Reuters",
    "BLOOMBERG": "Bloomberg",
    "WSJ": "WSJ",
    "MARKETWATCH": "MarketWatch",
    "SEEKINGALPHA": "SeekingAlpha",
    "SA": "SeekingAlpha",
    "JIN10": "金十",
}

RELATED_NEWS_TOPICS = {
    "TSLA": ["SpaceX", "Starlink", "XAI"],
    "TESLA": ["SpaceX", "Starlink", "XAI"],
    "AAPL": ["Apple", "iPhone", "Mac", "Apple Watch"],
    "APPLE": ["iPhone", "Mac", "Apple Watch", "App Store"],
    "NVDA": ["NVIDIA", "AI", "H100", "Data Center"],
    "GOOG": ["Alphabet", "DeepMind", "Waymo"],
    "MSFT": ["Microsoft", "Azure", "OpenAI"],
    "AMZN": ["Amazon", "AWS", "Prime"],
}


def quote_from_yahoo(symbol: str) -> dict[str, Any]:
    yf_symbol = get_ticker_mapping(symbol, "yahoo")
    hist = yf.Ticker(yf_symbol).history(period="5d")
    if hist.empty:
        return {"symbol": symbol, "price": "N/A", "diff": 0.0, "pct": 0.0, "volume_note": "N/A"}

    curr = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else curr
    diff = curr - prev
    pct = (diff / prev * 100) if prev else 0.0

    volume_note = "N/A"
    try:
        vol = float(hist["Volume"].iloc[-1])
        avg_vol = float(hist["Volume"].tail(min(5, len(hist))).mean())
        if avg_vol > 0:
            volume_note = "放量" if vol > avg_vol * 1.15 else "量縮" if vol < avg_vol * 0.85 else "量能持平"
    except Exception:
        pass

    return {"symbol": symbol, "price": curr, "diff": diff, "pct": pct, "volume_note": volume_note}


def get_macro_quote(symbol_name: str) -> dict[str, Any]:
    # 1. Finnhub first
    if finnhub_client:
        try:
            target = get_ticker_mapping(symbol_name, "finnhub")
            res = finnhub_client.quote(target)
            if res and float(res.get("c", 0)) > 0:
                return {
                    "symbol": symbol_name,
                    "price": float(res.get("c", 0)),
                    "diff": float(res.get("d", 0)),
                    "pct": float(res.get("dp", 0)),
                    "volume_note": "N/A",
                }
        except Exception:
            pass

    # 2. Yahoo fallback
    try:
        return quote_from_yahoo(symbol_name)
    except Exception as exc:
        logging.warning("get_macro_quote failed for %s: %s", symbol_name, exc)
        return {"symbol": symbol_name, "price": "N/A", "diff": 0.0, "pct": 0.0, "volume_note": "N/A"}


def format_quote(q: dict[str, Any]) -> str:
    price = q.get("price", "N/A")
    if not isinstance(price, (int, float)):
        return "N/A"
    diff = float(q.get("diff", 0))
    pct = float(q.get("pct", 0))
    sign = "+" if diff >= 0 else ""
    return f"{price:.2f} USD ({sign}{diff:.2f}) ({sign}{pct:.2f}%)"


def get_macro_status(symbol_name: str) -> str:
    return format_quote(get_macro_quote(symbol_name))


def get_fast_price(symbol_name: str):
    try:
        q = quote_from_yahoo(symbol_name.upper())
        return q["price"]
    except Exception:
        status = get_macro_status(symbol_name)
        try:
            return float(status.split()[0])
        except Exception:
            return "N/A"


def get_stock_history_summary(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    out = {
        "symbol": symbol, 
        "price": "N/A", 
        "volume_note": "N/A", 
        "trend_note": "N/A", 
        "support": "N/A", 
        "resistance": "N/A",
        "range_high_3mo": "N/A",
        "range_low_3mo": "N/A"
    }
    try:
        hist = yf.Ticker(symbol).history(period="3mo", interval="1d")
        if hist.empty:
            return out
        close = hist["Close"]
        out["price"] = float(close.iloc[-1])
        out["support"] = round(float(close.tail(20).min()), 2)
        out["resistance"] = round(float(close.tail(20).max()), 2)
        
        # 斐波那契回撤需要的區間高低點
        out["range_high_3mo"] = round(float(hist["High"].max()), 2)
        out["range_low_3mo"] = round(float(hist["Low"].min()), 2)

        ma5 = float(close.tail(5).mean())
        ma20 = float(close.tail(20).mean())
        if out["price"] > ma5 > ma20:
            out["trend_note"] = "短線偏多排列"
        elif out["price"] < ma5 < ma20:
            out["trend_note"] = "短線偏空排列"
        else:
            out["trend_note"] = "震盪整理"

        vol = float(hist["Volume"].iloc[-1])
        avg_vol = float(hist["Volume"].tail(20).mean())
        if avg_vol > 0:
            out["volume_note"] = "放量" if vol > avg_vol * 1.2 else "量縮" if vol < avg_vol * 0.8 else "量能持平"
    except Exception as exc:
        logging.warning("get_stock_history_summary failed for %s: %s", symbol, exc)
    return out


def get_stock_snapshot(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    quote = quote_from_yahoo(symbol)
    history = get_stock_history_summary(symbol)
    return {**history, "price": quote.get("price", history.get("price")), "diff": quote.get("diff", 0), "pct": quote.get("pct", 0)}


def format_number(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    abs_num = abs(num)
    if abs_num >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    if abs_num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    if abs_num >= 1_000_000:
        return f"${num / 1_000_000:.2f}M"
    return f"${num:,.0f}"


def resolve_news_topic(query: str) -> dict[str, str]:
    raw = (query or "").strip()
    if not raw:
        return {"target": "US Stock Market", "note": "預設查詢美股市況。"}

    tokens = [t for t in raw.replace("/", " ").split() if t]
    source_tokens: list[str] = []
    topic_tokens: list[str] = []

    for token in tokens:
        key = token.upper()
        if key in NEWS_SOURCE_ALIASES:
            source_tokens.append(NEWS_SOURCE_ALIASES[key])
        else:
            topic_tokens.append(token)

    topic_text = " ".join(topic_tokens).strip()
    normalized_topic = "".join(ch for ch in topic_text.upper() if ch.isalnum())
    target = raw
    note = "使用原始查詢字詞進行新聞搜尋。"

    if topic_text == "":
        target = "S&P 500 OR Nasdaq"
        note = "預設查詢標普500與納斯達克市場新聞。"
    elif normalized_topic in SPECIAL_NEWS_TOPICS:
        target = SPECIAL_NEWS_TOPICS[normalized_topic]
        note = f"自動判斷為 {target}。"
    elif any(k in topic_text.upper() for k in ["黃金", "GOLD"]):
        target = "黃金"
        note = "自動判斷為 黃金 商品新聞。"
    elif any(k in topic_text.upper() for k in ["原油", "OIL", "CRUDE"]):
        target = "原油"
        note = "自動判斷為 原油 商品新聞。"
    elif any(k in topic_text.upper() for k in ["比特", "BTC", "BITCOIN"]):
        target = "比特幣"
        note = "自動判斷為 比特幣 市場新聞。"
    elif normalized_topic.isalpha() and len(normalized_topic) <= 5:
        try:
            ticker = yf.Ticker(normalized_topic)
            info = getattr(ticker, "info", {}) or {}
            if info.get("regularMarketPrice") is not None or info.get("longName"):
                target = normalized_topic
                note = f"已判斷為股票代號 {normalized_topic}。"
                related = RELATED_NEWS_TOPICS.get(normalized_topic, [])
                if not related:
                    related = ai_core.infer_related_news_terms(normalized_topic, "Kevin")
                if related:
                    unique_related = []
                    for item in [normalized_topic] + related:
                        if item not in unique_related:
                            unique_related.append(item)
                    target = " OR ".join(unique_related)
                    note = f"已判斷為股票代號 {normalized_topic}，同時擴展相關搜尋：{', '.join(related)}。"
            else:
                target = topic_text
                note = "使用原始查詢字詞進行新聞搜尋。"
        except Exception:
            target = topic_text
            note = "使用原始查詢字詞進行新聞搜尋。"
    else:
        target = topic_text
        note = "使用原始查詢字詞進行新聞搜尋。"

    if source_tokens:
        target = f"{target} {' '.join(source_tokens)}"
        note = f"{note} 同時搜尋來源：{', '.join(source_tokens)}。"

    return {"target": target, "note": note}


def get_stock_fundamentals(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    ticker = yf.Ticker(symbol)
    info = {}
    try:
        info = getattr(ticker, "info", {}) or {}
    except Exception:
        info = {}

    if not info:
        return {}

    data: dict[str, Any] = {
        "symbol": symbol,
        "company_name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "country": info.get("country", "N/A"),
        "current_price": info.get("regularMarketPrice") or info.get("previousClose") or "N/A",
        "trailing_eps": info.get("trailingEps", "N/A"),
        "forward_eps": info.get("forwardEps", "N/A"),
        "trailing_pe": info.get("trailingPE", "N/A"),
        "forward_pe": info.get("forwardPE", "N/A"),
        "market_cap": format_number(info.get("marketCap")),
        "revenue_ttm": format_number(info.get("totalRevenue") or info.get("revenueTTM")),
        "net_income": format_number(info.get("netIncomeToCommon")),
        "profit_margin": f"{info.get('profitMargins', 'N/A'):.2%}" if isinstance(info.get("profitMargins"), (int, float)) else "N/A",
        "gross_margin": f"{info.get('grossMargins', 'N/A'):.2%}" if isinstance(info.get("grossMargins"), (int, float)) else "N/A",
        "year_high": info.get("fiftyTwoWeekHigh", "N/A"),
        "year_low": info.get("fiftyTwoWeekLow", "N/A"),
    }

    try:
        quarterly_earnings = ticker.quarterly_earnings
        if hasattr(quarterly_earnings, "empty") and not quarterly_earnings.empty:
            last_row = quarterly_earnings.iloc[-1]
            data["latest_quarter"] = str(last_row.name)
            data["latest_quarter_eps"] = last_row.get("Earnings", "N/A")
            data["latest_quarter_revenue"] = format_number(last_row.get("Revenue", "N/A"))
    except Exception:
        pass

    try:
        qfin = ticker.quarterly_financials
        if hasattr(qfin, "empty") and not qfin.empty and "Total Revenue" in qfin.index:
            data["quarterly_financial_revenue"] = format_number(qfin.loc["Total Revenue"].iloc[0])
    except Exception:
        pass

    return data


def fetch_news_multi(symbol: str, limit: int = 3) -> list[dict[str, str]]:
    symbol = symbol.upper()
    news_list: list[dict[str, str]] = []

    if NEWS_API_KEY:
        try:
            params = {
                "q": symbol,
                "sortBy": "publishedAt",
                "language": "en",
                "apiKey": NEWS_API_KEY,
                "pageSize": limit,
            }
            r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=8)
            data = r.json()
            if data.get("status") == "ok":
                for n in data.get("articles", [])[:limit]:
                    news_list.append({
                        "title": n.get("title") or "",
                        "description": n.get("description") or "",
                        "source": (n.get("source") or {}).get("name", "NewsAPI"),
                        "url": n.get("url") or "",
                        "publishedAt": n.get("publishedAt") or "",
                    })
        except Exception as exc:
            logging.warning("NewsAPI failed for %s: %s", symbol, exc)

    if not news_list:
        try:
            yf_news = yf.Ticker(symbol).news or []
            for n in yf_news[:limit]:
                news_list.append({
                    "title": n.get("title", ""),
                    "description": n.get("summary", "") or n.get("publisher", ""),
                    "source": n.get("publisher", "Yahoo Finance"),
                    "url": n.get("link", ""),
                    "publishedAt": n.get("providerPublishTime", ""),
                })
        except Exception as exc:
            logging.warning("Yahoo news failed for %s: %s", symbol, exc)

    # 優先時間排序，最新的優先
    news_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return news_list


def get_news_source_list() -> str:
    sources = [
        "Reuters（路透）",
        "Bloomberg（彭博）",
        "WSJ（華爾街日報）",
        "Seeking Alpha",
        "TradingView",
        "MarketWatch",
        "金十（jin10）",
    ]
    return (
        "📌 可搜尋新聞來源清單：\n"
        + "━━━━━━━━━━━━━━\n"
        + "\n".join([f"• {s}" for s in sources])
        + "\n\n可用縮寫：tv=TradingView, reuters=bloomberg, wsj=WSJ, sa=SeekingAlpha, jin10=金十。"
    )


def fetch_news_filtered(query: str, limit: int = 5) -> list[dict[str, str]]:
    """從指定來源抓取新聞 (金十, Reuters, Bloomberg, WSJ, Seeking Alpha, TradingView, MarketWatch)"""
    domains = ",".join(NEWS_SEARCH_SOURCES)
    news_list: list[dict[str, str]] = []

    if NEWS_API_KEY:
        try:
            params = {
                "q": query,
                "domains": domains,
                "sortBy": "publishedAt",
                "language": "en",
                "apiKey": NEWS_API_KEY,
                "pageSize": limit,
            }
            r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
            data = r.json()
            if data.get("status") == "ok":
                for n in data.get("articles", []):
                    news_list.append({
                        "title": n.get("title") or "",
                        "description": n.get("description") or "",
                        "source": (n.get("source") or {}).get("name", "NewsAPI"),
                        "url": n.get("url") or "",
                        "publishedAt": n.get("publishedAt") or "",
                    })
        except Exception as exc:
            logging.warning("fetch_news_filtered NewsAPI failed for %s: %s", query, exc)

    if not news_list and NEWS_API_KEY:
        try:
            params = {
                "q": query,
                "sortBy": "publishedAt",
                "language": "en",
                "apiKey": NEWS_API_KEY,
                "pageSize": max(limit * 2, limit),
            }
            r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
            data = r.json()
            if data.get("status") == "ok":
                for n in data.get("articles", []):
                    news_list.append({
                        "title": n.get("title") or "",
                        "description": n.get("description") or "",
                        "source": (n.get("source") or {}).get("name", "NewsAPI"),
                        "url": n.get("url") or "",
                        "publishedAt": n.get("publishedAt") or "",
                    })
        except Exception as exc:
            logging.warning("fetch_news_filtered NewsAPI fallback failed for %s: %s", query, exc)

    if news_list:
        news_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
        return news_list[:limit]

    # Fallback to general search if filtered search yields nothing
    return fetch_news_multi(query, limit=limit)
