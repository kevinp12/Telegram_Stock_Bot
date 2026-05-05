"""market_api.py
市場資料調度層：Finnhub、Yahoo Finance、NewsAPI。
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests
import yfinance as yf
import feedparser
import numpy as np

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

# 全局 Session 偽裝，避免被 yfinance/yahoo 封鎖
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

def fetch_batch_quotes(symbols: list[str]) -> dict[str, float]:
    """
    批次打包請求：一次下載所有標的報價，大幅降低 API 被封鎖機率。
    """
    if not symbols:
        return {}
    
    ticker_map = {s: get_ticker_mapping(s, "yahoo") for s in symbols}
    target_tickers = list(ticker_map.values())
    
    try:
        data = yf.download(
            tickers=" ".join(target_tickers),
            period="1d",
            interval="1m",
            group_by='ticker',
            auto_adjust=True,
            prepost=True,
            session=session,
            progress=False
        )
        
        if data.empty:
            return {}
            
        results = {}
        for original_sym, yf_sym in ticker_map.items():
            try:
                if len(target_tickers) > 1:
                    price = data[yf_sym]['Close'].iloc[-1]
                else:
                    price = data['Close'].iloc[-1]
                
                if not np.isnan(price):
                    results[original_sym] = float(price)
            except Exception:
                continue
        return results
    except Exception as e:
        logging.warning(f"fetch_batch_quotes failed: {e}")
        return {}

# 擴充的科技與未來趨勢主題池
TECH_THEMES = {
    "AI": "Artificial Intelligence OR Nvidia OR OpenAI",
    "半導體": "Semiconductor OR TSMC OR AMD",
    "電動車": "EV OR Tesla OR Autonomous Driving",
    "機器人": "Robotics OR Optimus OR Humanoid",
    "火箭": "SpaceX OR Rocket Lab OR Aerospace OR Space Exploration",
    "光電": "Solar Energy OR Optoelectronics OR Enphase OR First Solar",
    "未來APP": "Web3 OR Decentralized App OR Spatial Computing OR AR VR",
    "能源": "Renewable Energy OR Clean Energy OR Grid Storage",
    "核能": "Nuclear Energy OR Uranium OR SMR OR Constellation Energy",
    "資安": "Cybersecurity OR Palo Alto Networks OR CrowdStrike OR Fortinet"
}


def fetch_tech_rss(limit: int = 5) -> list[dict[str, str]]:
    rss_urls = [
        ("CNBC Tech", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("WSJ Tech", "https://feeds.a.dj.com/rss/RSSWSJD.xml")
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    news_list = []
    import time
    
    for source_name, url in rss_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                continue

            for entry in feed.entries[:limit]:
                published_time = entry.get("published_parsed") or entry.get("updated_parsed")
                timestamp = time.mktime(published_time) if published_time else 0
                content = entry.get("summary") or entry.get("description") or ""
                content = re.sub(r'<[^>]+>', '', content).strip()

                news_list.append({
                    "title": entry.get("title", "無標題").strip(),
                    "description": content[:500] + ("..." if len(content) > 500 else ""),
                    "source": source_name,
                    "url": entry.get("link", ""),
                    "publishedAt": entry.get("published", ""),
                    "_timestamp": timestamp
                })
        except Exception as e:
            logging.warning(f"RSS 讀取失敗 {source_name}: {e}")
            
    news_list.sort(key=lambda x: x.get("_timestamp", 0), reverse=True)
    for n in news_list:
        n.pop("_timestamp", None)
    return news_list[:limit]


def get_ticker_mapping(symbol_name: str, source: str = "finnhub") -> str:
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
    return mapping.get(symbol_name, symbol_name.upper())


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
    "TSLA": ["SpaceX", "Starlink", "XAI", "Elon Musk"],
    "NVDA": ["NVIDIA", "AI", "H100", "Data Center", "Jensen Huang"],
    "AAPL": ["Apple", "iPhone", "Mac", "Apple Watch", "Tim Cook"],
    "GOOGL": ["Alphabet", "Google", "DeepMind", "Waymo", "Sundar Pichai"],
    "MSFT": ["Microsoft", "Azure", "OpenAI", "Satya Nadella"],
    "AMZN": ["Amazon", "AWS", "Blue Origin", "Jeff Bezos"],
    "META": ["Facebook", "Instagram", "WhatsApp", "Metaverse", "Mark Zuckerberg"],
    "TSM": ["TSMC", "Semiconductor", "Foundry", "Chipmaking"],
    "ASML": ["Lithography", "EUV", "Semiconductor Equipment"],
    "AMD": ["Advanced Micro Devices", "CPU", "GPU", "Semiconductor"],
    "INTC": ["Intel", "CPU", "Semiconductor", "Foundry"],
    "NFLX": ["Netflix", "Streaming", "Original Series"],
    "DIS": ["Disney", "Marvel", "Star Wars", "Disney Plus"],
    "PLTR": ["Palantir", "Big Data", "Analytics", "Defense Tech"],
    "ARM": ["ARM Holdings", "Semiconductor Architecture", "SoftBank"],
    "RKLB": ["Rocket Lab", "Space", "Aerospace"],
    "SMR": ["NuScale Power", "Nuclear", "SMR"],
    "VRT": ["Vertiv", "Data Center Infrastructure"],
    "MSTR": ["MicroStrategy", "Bitcoin", "Saylor"],
    "S": ["SentinelOne", "Cybersecurity"],
    "NET": ["Cloudflare", "CDN", "Edge Computing"],
    "SNOW": ["Snowflake", "Data Warehouse", "Cloud Data"],
    "ENPH": ["Enphase Energy", "Solar", "Microinverter"],
    "AVGO": ["Broadcom", "Semiconductor", "Networking"],
    "ASTS": ["AST Spacemobile", "Satellite", "Telecom"],
    "AMSC": ["American Superconductor", "Power Grid"],
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
    p_val = safe_round(price, 2)
    d_val = safe_round(diff, 2)
    pct_val = safe_round(pct, 2)
    return f"{p_val:.2f} USD ({sign}{d_val:.2f}) ({sign}{pct_val:.2f}%)"


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


from utils import safe_round


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
        out["price"] = safe_round(close.iloc[-1])
        out["support"] = safe_round(close.tail(20).min())
        out["resistance"] = safe_round(close.tail(20).max())
        out["range_high_3mo"] = safe_round(hist["High"].max())
        out["range_low_3mo"] = safe_round(hist["Low"].min())

        ma5 = float(close.tail(5).mean())
        ma20 = float(close.tail(20).mean())
        curr_price = out["price"] if isinstance(out["price"], (int, float)) else 0
        if curr_price > ma5 > ma20:
            out["trend_note"] = "短線偏多排列"
        elif curr_price < ma5 < ma20:
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
    return {
        **history, 
        "price": safe_round(quote.get("price", history.get("price"))), 
        "diff": safe_round(quote.get("diff", 0)), 
        "pct": safe_round(quote.get("pct", 0))
    }


def format_number(value: Any) -> str:
    if value is None or value == "N/A":
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    abs_num = abs(num)
    if abs_num >= 1_000_000_000_000:
        val = safe_round(num / 1_000_000_000_000, 2)
        return f"${val:.2f}T"
    if abs_num >= 1_000_000_000:
        val = safe_round(num / 1_000_000_000, 2)
        return f"${val:.2f}B"
    if abs_num >= 1_000_000:
        val = safe_round(num / 1_000_000, 2)
        return f"${val:.2f}M"
    val = safe_round(num, 2)
    return f"${val:,.2f}"


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
    # 支援代號包含數字與點 (e.g. 2330.TW, BTC-USD)
    normalized_topic = topic_text.upper().replace(" ", "")
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
    elif any(k in topic_text.upper() for k in ["原油", "OIL", "CRUDE"]):
        target = "原油"
    elif any(k in topic_text.upper() for k in ["比特", "BTC", "BITCOIN"]):
        target = "比特幣"
    elif 1 <= len(normalized_topic) <= 12: # 擴展代號長度
        try:
            # 檢查是否像股票代號
            ticker = yf.Ticker(normalized_topic)
            info = getattr(ticker, "info", {}) or {}
            # yfinance info 有時會拋錯或為空，這裡做簡單驗證
            if info.get("regularMarketPrice") is not None or info.get("symbol"):
                target = normalized_topic
                note = f"已判斷為股票代號 {normalized_topic}。"
                related = RELATED_NEWS_TOPICS.get(normalized_topic, [])
                if not related and normalized_topic.isalpha():
                    related = ai_core.infer_related_news_terms(normalized_topic, "User")
                if related:
                    unique_related = []
                    for item in [normalized_topic] + related:
                        if item not in unique_related: unique_related.append(item)
                    target = " OR ".join(unique_related)
                    note = f"已判斷為股票代號 {normalized_topic}，擴展搜尋：{', '.join(related)}。"
        except Exception:
            pass

    if source_tokens:
        target = f"({target}) {' '.join(source_tokens)}"
        note = f"{note} 同時搜尋來源：{', '.join(source_tokens)}。"
    return {"target": target, "note": note}


def get_stock_fundamentals(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    ticker = yf.Ticker(symbol)
    try:
        info = getattr(ticker, "info", {}) or {}
    except Exception:
        info = {}
    if not info: return {}

    data: dict[str, Any] = {
        "symbol": symbol,
        "company_name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "country": info.get("country", "N/A"),
        "current_price": safe_round(info.get("regularMarketPrice") or info.get("previousClose")),
        "trailing_eps": safe_round(info.get("trailingEps")),
        "forward_eps": safe_round(info.get("forwardEps")),
        "trailing_pe": safe_round(info.get("trailingPE")),
        "forward_pe": safe_round(info.get("forwardPE")),
        "market_cap": format_number(info.get("marketCap")),
        "revenue_ttm": format_number(info.get("totalRevenue") or info.get("revenueTTM")),
        "net_income": format_number(info.get("netIncomeToCommon")),
        "profit_margin": f"{safe_round(info.get('profitMargins', 0)*100, 2)}%" if isinstance(info.get("profitMargins"), (int, float)) else "N/A",
        "gross_margin": f"{safe_round(info.get('grossMargins', 0)*100, 2)}%" if isinstance(info.get("grossMargins"), (int, float)) else "N/A",
        "year_high": safe_round(info.get("fiftyTwoWeekHigh")),
        "year_low": safe_round(info.get("fiftyTwoWeekLow")),
    }

    try:
        quarterly_earnings = ticker.quarterly_earnings
        if hasattr(quarterly_earnings, "empty") and not quarterly_earnings.empty and len(quarterly_earnings) >= 2:
            last_row = quarterly_earnings.iloc[-1]
            prev_row = quarterly_earnings.iloc[-2]
            data["latest_quarter"] = str(last_row.name)
            data["latest_quarter_eps"] = safe_round(last_row.get("Earnings"))
            data["latest_quarter_revenue"] = format_number(last_row.get("Revenue", "N/A"))
            last_rev = last_row.get("Revenue")
            prev_rev = prev_row.get("Revenue")
            if isinstance(last_rev, (int, float)) and isinstance(prev_rev, (int, float)) and prev_rev != 0:
                growth = (last_rev - prev_rev) / prev_rev * 100
                data["revenue_growth_qoq"] = f"{'+' if growth >= 0 else ''}{safe_round(growth, 2)}%"
    except Exception: pass
    return data


def fetch_portfolio_history(symbols: list[str]) -> dict[str, dict[str, float]]:
    """
    獲取多個標的在不同時間點的歷史價格。
    回傳：{ symbol: { "7d": price, "1mo": price, ... } }
    """
    if not symbols:
        return {}
    
    ticker_map = {s: get_ticker_mapping(s, "yahoo") for s in symbols}
    target_tickers = list(ticker_map.values())
    
    try:
        # 下載過去一年的日 K 線
        data = yf.download(
            tickers=" ".join(target_tickers),
            period="1y",
            interval="1d",
            group_by='ticker',
            auto_adjust=True,
            prepost=True,
            session=session,
            progress=False
        )
        
        if data.empty:
            return {}
            
        results = {}
        for original_sym, yf_sym in ticker_map.items():
            try:
                if len(target_tickers) > 1:
                    df = data[yf_sym].dropna()
                else:
                    df = data.dropna()
                
                if df.empty:
                    continue
                
                # 獲取不同偏移量的價格
                # 如果該日期沒開盤，則取最接近的後一個交易日
                hist_prices = {}
                
                def get_price_at(offset_days: int) -> float | None:
                    target_date = datetime.now() - timedelta(days=offset_days)
                    # 尋找大於等於目標日期的第一筆資料
                    match = df[df.index >= target_date.strftime("%Y-%m-%d")]
                    if not match.empty:
                        return float(match['Close'].iloc[0])
                    return None

                def get_price_ytd() -> float | None:
                    ytd_date = datetime(datetime.now().year, 1, 1)
                    match = df[df.index >= ytd_date.strftime("%Y-%m-%d")]
                    if not match.empty:
                        return float(match['Close'].iloc[0])
                    return None

                hist_prices["7d"] = get_price_at(7)
                hist_prices["1mo"] = get_price_at(30)
                hist_prices["6mo"] = get_price_at(180)
                hist_prices["ytd"] = get_price_ytd()
                hist_prices["1y"] = get_price_at(365)
                
                results[original_sym] = hist_prices
            except Exception:
                continue
        return results
    except Exception as e:
        logging.warning(f"fetch_portfolio_history failed: {e}")
        return {}


def fetch_news_multi(symbol: str, limit: int = 3) -> list[dict[str, str]]:
    symbol = symbol.upper()
    news_list: list[dict[str, str]] = []

    if NEWS_API_KEY:
        try:
            # 移除 language="en" 限制，增加搜尋廣度
            params = {"q": symbol, "sortBy": "publishedAt", "apiKey": NEWS_API_KEY, "pageSize": limit}
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

    # 無論 NewsAPI 是否成功，都嘗試從 Yahoo 補充（Yahoo 通常有更及時的個股消息）
    try:
        yf_news = yf.Ticker(symbol).news or []
        for n in yf_news[:limit]:
            # 避免重複 (比對標題)
            if any(n.get("title") == existing.get("title") for existing in news_list): continue
            news_list.append({
                "title": n.get("title", ""),
                "description": n.get("summary", "") or n.get("publisher", ""),
                "source": n.get("publisher", "Yahoo Finance"),
                "url": n.get("link", ""),
                "publishedAt": n.get("providerPublishTime", ""),
            })
    except Exception as exc:
        logging.warning("Yahoo news failed for %s: %s", symbol, exc)

    news_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return news_list[:limit]


def get_news_source_list() -> str:
    sources = ["Reuters", "Bloomberg", "WSJ", "Seeking Alpha", "TradingView", "MarketWatch", "金十"]
    return "📌 可搜尋新聞來源清單：\n" + "━━━━━━━━━━━━━━\n" + "\n".join([f"• {s}" for s in sources])


def fetch_news_filtered(query: str, limit: int = 5) -> list[dict[str, str]]:
    """從指定來源抓取新聞，若無結果則自動降級搜尋"""
    domains = ",".join(NEWS_SEARCH_SOURCES)
    news_list: list[dict[str, str]] = []

    if NEWS_API_KEY:
        try:
            # 優先搜尋高品質 Domain
            params = {"q": query, "domains": domains, "sortBy": "publishedAt", "apiKey": NEWS_API_KEY, "pageSize": limit}
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
        except Exception: pass

    # 如果 Domain 限制找不到，或者 NEWS_API_KEY 不存在，走全網/Yahoo 降級搜尋
    if not news_list:
        return fetch_news_multi(query, limit=limit)

    news_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return news_list[:limit]
