"""market_api.py
市場資料調度層：Finnhub、Yahoo Finance、NewsAPI。
"""

from __future__ import annotations

import logging
import re
import io
from datetime import datetime, timedelta
from typing import Any

import feedparser
import numpy as np
import requests
import yfinance as yf

try:
    import finnhub
except Exception:
    finnhub = None

import ai_core
from config import BLS_API_KEY, FINNHUB_KEY, FRED_API_KEY, NEWS_API_KEY
from utils import safe_round, setup_matplotlib_cjk_font

finnhub_client = None
if finnhub and FINNHUB_KEY:
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_KEY)
    except Exception as exc:
        logging.warning("Finnhub 初始化失敗: %s", exc)

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
            group_by="ticker",
            auto_adjust=True,
            prepost=True,
            progress=False,
        )

        if data.empty:
            return {}

        results = {}
        for original_sym, yf_sym in ticker_map.items():
            try:
                if len(target_tickers) > 1:
                    price = data[yf_sym]["Close"].iloc[-1]
                else:
                    price = data["Close"].iloc[-1]

                if not np.isnan(price):
                    results[original_sym] = float(price)
            except Exception:
                continue
        return results
    except Exception as e:
        logging.warning(f"fetch_batch_quotes failed: {e}")
        return {}


def fetch_tech_rss(limit: int = 5) -> list[dict[str, str]]:
    rss_urls = [
        ("CNBC Tech", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("WSJ Tech", "https://feeds.a.dj.com/rss/RSSWSJD.xml"),
    ]

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

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
                content = re.sub(r"<[^>]+>", "", content).strip()

                news_list.append(
                    {
                        "title": entry.get("title", "無標題").strip(),
                        "description": content[:500] + ("..." if len(content) > 500 else ""),
                        "source": source_name,
                        "url": entry.get("link", ""),
                        "publishedAt": entry.get("published", ""),
                        "_timestamp": timestamp,
                    }
                )
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
        except Exception as exc:
            logging.debug("Finnhub quote fallback for %s: %s", symbol_name, exc)
    try:
        return quote_from_yahoo(symbol_name)
    except Exception as exc:
        logging.warning("get_macro_quote failed for %s: %s", symbol_name, exc)
        return {"symbol": symbol_name, "price": "N/A", "diff": 0.0, "pct": 0.0, "volume_note": "N/A"}


def format_quote(q: dict[str, Any]) -> str:
    price = q.get("price", "N/A")
    if not isinstance(price, (int, float)):
        return "N/A"
    symbol = str(q.get("symbol", "") or "").upper()
    diff = float(q.get("diff", 0))
    pct = float(q.get("pct", 0))
    sign = "+" if diff >= 0 else ""
    p_val = safe_round(price, 2)
    d_val = safe_round(diff, 2)
    pct_val = safe_round(pct, 2)
    # VIX 為波動率指數，顯示時不加 USD 單位
    unit = "" if symbol == "VIX" else " USD"
    return f"{p_val:.2f}{unit} ({sign}{d_val:.2f}) ({sign}{pct_val:.2f}%)"


def get_macro_status(symbol_name: str) -> str:
    return format_quote(get_macro_quote(symbol_name))


def get_fear_greed_index() -> dict[str, Any]:
    """取得 CNN Fear & Greed Index；失敗時回傳 N/A。"""
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=8)
        data = r.json()
        fg = data.get("fear_and_greed") or {}
        value = fg.get("score") or fg.get("value")
        rating = fg.get("rating") or fg.get("classification") or "N/A"
        if value is None:
            return {"value": "N/A", "rating": "N/A", "note": "資料暫時無法取得"}
        return {"value": safe_round(float(value), 1), "rating": str(rating), "note": "CNN Fear & Greed"}
    except Exception as exc:
        logging.warning("get_fear_greed_index failed: %s", exc)
        return {"value": "N/A", "rating": "N/A", "note": "資料暫時無法取得"}


def get_options_flow_snapshot(limit: int = 3) -> list[dict[str, str]]:
    """用新聞/公開資訊近似追蹤大額選擇權異動。"""
    queries = [
        "unusual options activity large call put buying stocks",
        "options flow unusual call buying put buying stock market",
    ]
    items: list[dict[str, str]] = []
    for query in queries:
        try:
            items.extend(fetch_news_filtered(query, limit=limit))
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items[:limit]


def get_social_heat_snapshot(limit: int = 3) -> list[dict[str, str]]:
    """用新聞搜尋近似偵測 Reddit WSB / X 熱門討論標的。"""
    queries = [
        "Reddit WallStreetBets trending stocks OR WSB stocks",
        "X Twitter trending stocks retail traders",
    ]
    items: list[dict[str, str]] = []
    for query in queries:
        try:
            items.extend(fetch_news_filtered(query, limit=limit))
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items[:limit]


def get_put_call_ratio(symbols: list[str] | None = None) -> dict[str, Any]:
    """估算大盤 Put/Call Open Interest Ratio（預設 SPY+QQQ）。"""
    targets = symbols or ["SPY", "QQQ"]
    put_oi_total = 0.0
    call_oi_total = 0.0

    for symbol in targets:
        try:
            ticker = yf.Ticker(symbol)
            expirations = list(getattr(ticker, "options", []) or [])
            if not expirations:
                continue
            expiry = expirations[0]
            chain = ticker.option_chain(expiry)
            puts = getattr(chain, "puts", None)
            calls = getattr(chain, "calls", None)
            if puts is None or calls is None:
                continue
            put_oi_total += float(puts.get("openInterest", 0).fillna(0).sum())
            call_oi_total += float(calls.get("openInterest", 0).fillna(0).sum())
        except Exception as exc:
            logging.debug("get_put_call_ratio failed for %s: %s", symbol, exc)

    if call_oi_total <= 0:
        return {"value": "N/A", "puts": 0, "calls": 0, "note": "選擇權資料不足"}

    ratio = put_oi_total / call_oi_total
    return {
        "value": safe_round(ratio, 3),
        "puts": int(put_oi_total),
        "calls": int(call_oi_total),
        "note": "SPY+QQQ 近月 OI 估算",
    }


def get_vix_risk_score(vix_quote: dict[str, Any]) -> int | str:
    """將 VIX 轉換為 1~10 風險分數。"""
    try:
        vix_price = float(vix_quote.get("price", 0) or 0)
    except Exception:
        return "N/A"
    if vix_price <= 0:
        return "N/A"

    score = int(round((vix_price - 10) / 2.5))
    if score < 1:
        score = 1
    if score > 10:
        score = 10
    return score


def get_earnings_calendar(symbols: list[str] | None = None, limit: int = 5) -> list[dict[str, str]]:
    """取得近期財報日曆（優先用 yfinance calendar）。"""
    targets = symbols or ["NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "GOOGL"]
    rows: list[dict[str, str]] = []

    for symbol in targets:
        try:
            ticker = yf.Ticker(symbol)
            cal = getattr(ticker, "calendar", None)
            if cal is None:
                continue

            earning_date = "N/A"
            try:
                # yfinance 新版多為 DataFrame，舊版可能是 dict
                if hasattr(cal, "index") and hasattr(cal, "columns"):
                    if "Earnings Date" in cal.index and len(cal.columns) > 0:
                        raw = cal.loc["Earnings Date"].iloc[0]
                        earning_date = str(raw)[:10]
                elif isinstance(cal, dict):
                    raw = cal.get("Earnings Date")
                    if isinstance(raw, (list, tuple)) and raw:
                        earning_date = str(raw[0])[:10]
                    elif raw:
                        earning_date = str(raw)[:10]
            except Exception:
                pass

            if earning_date != "N/A":
                rows.append({"symbol": symbol, "date": earning_date})
        except Exception as exc:
            logging.debug("get_earnings_calendar failed for %s: %s", symbol, exc)

    rows.sort(key=lambda x: x.get("date", "9999-99-99"))
    return rows[:limit]


FRED_SERIES_MAP = {
    "CPI": "CPIAUCSL",
    "CORE_CPI": "CPILFESL",
    "PCE": "PCEPI",
    "PPI": "PPIACO",
    "RETAIL_SALES": "RSAFS",
    "UNRATE": "UNRATE",
    "US10Y": "GS10",
}

BLS_SERIES_MAP = {
    "NFP": "CES0000000001",  # Total Nonfarm Payrolls
    "AHE": "CES0500000003",  # Avg Hourly Earnings of All Employees: Private
}


def _fetch_fred_latest_with_prev(series_id: str) -> dict[str, Any]:
    if not FRED_API_KEY:
        return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "未設定 FRED_API_KEY"}
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 3,
        }
        r = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10)
        data = r.json()
        obs = data.get("observations") or []
        valid = [o for o in obs if o.get("value") not in {".", None, ""}]
        if len(valid) < 1:
            return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "FRED 無有效資料"}

        latest = float(valid[0]["value"])
        prev = float(valid[1]["value"]) if len(valid) > 1 else latest
        trend = "上升" if latest > prev else "下降" if latest < prev else "持平"
        return {
            "value": safe_round(latest, 2),
            "prev": safe_round(prev, 2),
            "trend": trend,
            "date": valid[0].get("date", "N/A"),
            "note": "FRED",
        }
    except Exception as exc:
        logging.warning("_fetch_fred_latest_with_prev failed for %s: %s", series_id, exc)
        return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "抓取失敗"}


def _fetch_bls_latest_with_prev(series_id: str) -> dict[str, Any]:
    """抓取 BLS 指標最新值與前值；失敗時回傳 N/A。"""
    try:
        end_year = datetime.now().year
        start_year = end_year - 1
        payload: dict[str, Any] = {
            "seriesid": [series_id],
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if BLS_API_KEY:
            payload["registrationkey"] = BLS_API_KEY

        r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json=payload, timeout=12)
        data = r.json()
        results = ((data or {}).get("Results") or {}).get("series") or []
        if not results:
            return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "BLS 無資料"}

        entries = results[0].get("data") or []
        valid = [e for e in entries if e.get("period", "").startswith("M") and e.get("value") not in {None, "", "."}]
        if not valid:
            return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "BLS 無有效資料"}

        latest = float(valid[0]["value"])
        prev = float(valid[1]["value"]) if len(valid) > 1 else latest
        trend = "上升" if latest > prev else "下降" if latest < prev else "持平"
        year = str(valid[0].get("year", "N/A"))
        period = str(valid[0].get("period", ""))
        month = period[1:] if period.startswith("M") else ""
        date = f"{year}-{month}-01" if year != "N/A" and month.isdigit() else "N/A"

        return {
            "value": safe_round(latest, 2),
            "prev": safe_round(prev, 2),
            "trend": trend,
            "date": date,
            "note": "BLS",
        }
    except Exception as exc:
        logging.warning("_fetch_bls_latest_with_prev failed for %s: %s", series_id, exc)
        return {"value": "N/A", "prev": "N/A", "trend": "N/A", "date": "N/A", "note": "抓取失敗"}


def get_macro_core_snapshot() -> dict[str, Any]:
    """宏觀核心資料：通膨/就業/利率與美元。"""
    cpi = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["CPI"])
    core_cpi = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["CORE_CPI"])
    pce = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["PCE"])
    ppi = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["PPI"])
    retail_sales = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["RETAIL_SALES"])
    unrate = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["UNRATE"])
    us10y = _fetch_fred_latest_with_prev(FRED_SERIES_MAP["US10Y"])
    nfp = _fetch_bls_latest_with_prev(BLS_SERIES_MAP["NFP"])
    avg_hourly_earnings = _fetch_bls_latest_with_prev(BLS_SERIES_MAP["AHE"])
    put_call_ratio = get_put_call_ratio(["SPY", "QQQ"])
    fear_greed = get_fear_greed_index()

    dxy_quote = {"symbol": "DXY", "price": "N/A", "diff": 0.0, "pct": 0.0, "volume_note": "N/A"}
    try:
        dxy_hist = yf.Ticker("DX-Y.NYB").history(period="5d")
        if not dxy_hist.empty:
            curr = float(dxy_hist["Close"].iloc[-1])
            prev = float(dxy_hist["Close"].iloc[-2]) if len(dxy_hist) >= 2 else curr
            diff = curr - prev
            pct = (diff / prev * 100) if prev else 0.0
            dxy_quote = {"symbol": "DXY", "price": safe_round(curr, 2), "diff": safe_round(diff, 2), "pct": safe_round(pct, 2), "volume_note": "N/A"}
    except Exception as exc:
        logging.warning("get_macro_core_snapshot DXY failed: %s", exc)

    vix_quote = get_macro_quote("VIX")
    vix_score = get_vix_risk_score(vix_quote)
    earnings_calendar = get_earnings_calendar(limit=5)

    return {
        "cpi": cpi,
        "core_cpi": core_cpi,
        "pce": pce,
        "ppi": ppi,
        "retail_sales": retail_sales,
        "unrate": unrate,
        "nfp": nfp,
        "avg_hourly_earnings": avg_hourly_earnings,
        "us10y": us10y,
        "dxy": dxy_quote,
        "vix": vix_quote,
        "vix_score": vix_score,
        "put_call_ratio": put_call_ratio,
        "fear_greed": fear_greed,
        "earnings_calendar": earnings_calendar,
    }


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
        "range_low_3mo": "N/A",
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
        "pct": safe_round(quote.get("pct", 0)),
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
    elif 1 <= len(normalized_topic) <= 12:  # 擴展代號長度
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
                        if item not in unique_related:
                            unique_related.append(item)
                    target = " OR ".join(unique_related)
                    note = f"已判斷為股票代號 {normalized_topic}，擴展搜尋：{', '.join(related)}。"
        except Exception as exc:
            logging.debug("resolve_news_topic ticker check failed for %s: %s", normalized_topic, exc)

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
    if not info:
        return {}

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
    except Exception as exc:
        logging.debug("quarterly earnings unavailable for %s: %s", symbol, exc)
    return data


def get_recent_quarterly_financials(symbol: str, limit: int = 4) -> list[dict[str, Any]]:
    """取得最近 N 季財報（營收、淨利、淨利率、EPS）資料。"""
    symbol = symbol.upper().strip()
    ticker = yf.Ticker(symbol)
    rows: list[dict[str, Any]] = []
    try:
        q = ticker.quarterly_earnings
        if q is None or getattr(q, "empty", True):
            q = None

        qis = getattr(ticker, "quarterly_income_stmt", None)

        # 優先用 income statement（欄位較完整）
        if qis is not None and not getattr(qis, "empty", True):
            cols = list(qis.columns)[-limit:]
            for c in cols:
                rev = None
                net_income = None
                eps = None
                for key in ["Total Revenue", "Operating Revenue", "Revenue"]:
                    if key in qis.index:
                        v = qis.loc[key, c]
                        if isinstance(v, (int, float)):
                            rev = float(v)
                            break
                for key in ["Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"]:
                    if key in qis.index:
                        v = qis.loc[key, c]
                        if isinstance(v, (int, float)):
                            net_income = float(v)
                            break
                for key in ["Diluted EPS", "Basic EPS", "Normalized EPS"]:
                    if key in qis.index:
                        v = qis.loc[key, c]
                        if isinstance(v, (int, float)):
                            eps = float(v)
                            break
                margin = None
                if isinstance(rev, (int, float)) and rev not in (0, 0.0) and isinstance(net_income, (int, float)):
                    margin = (net_income / rev) * 100.0
                rows.append(
                    {
                        "quarter": str(c)[:10],
                        "revenue": rev,
                        "net_income": net_income,
                        "net_margin": margin,
                        "eps": eps,
                    }
                )

        # 補 EPS：若前面沒抓到且 quarterly_earnings 可用
        if q is not None and not getattr(q, "empty", True):
            q = q.tail(limit)
            q_map: dict[str, float | None] = {}
            for idx, row in q.iterrows():
                e = row.get("Earnings")
                q_map[str(idx)[:10]] = float(e) if isinstance(e, (int, float)) else None

            if rows:
                for r in rows:
                    if r.get("eps") is None:
                        r["eps"] = q_map.get(str(r.get("quarter", ""))[:10])
            else:
                # 最後 fallback：只有 quarterly_earnings
                for idx, row in q.iterrows():
                    revenue = row.get("Revenue")
                    net_income = row.get("Earnings")
                    rev = float(revenue) if isinstance(revenue, (int, float)) else None
                    ni = float(net_income) if isinstance(net_income, (int, float)) else None
                    margin = None
                    if isinstance(rev, (int, float)) and rev not in (0, 0.0) and isinstance(ni, (int, float)):
                        margin = (ni / rev) * 100.0
                    rows.append(
                        {
                            "quarter": str(idx)[:10],
                            "revenue": rev,
                            "net_income": ni,
                            "net_margin": margin,
                            "eps": ni,
                        }
                    )
    except Exception as exc:
        logging.debug("get_recent_quarterly_financials failed for %s: %s", symbol, exc)
        return []
    return rows


def generate_fin_chart_buffer(symbol: str, theme: str = "dark") -> io.BytesIO | None:
    """Generate 1Y quarterly financial chart (Revenue/Net Income/Net Margin + Profit Mix pie)."""
    rows = get_recent_quarterly_financials(symbol, limit=4)
    if len(rows) < 2:
        return None

    try:
        import matplotlib as mpl
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        logging.warning("matplotlib unavailable for fin chart: %s", exc)
        return None

    # 統一中文字型策略（跨圖一致）
    setup_matplotlib_cjk_font(mpl)

    theme_name = (theme or "dark").strip().lower()
    if theme_name not in {"dark", "light"}:
        theme_name = "dark"

    if theme_name == "light":
        fig_facecolor = "#F8FAFC"
        ax_facecolor = "#FFFFFF"
        text_color = "#111827"
        grid_color = "#E5E7EB"
        spine_color = "#D1D5DB"
        pie_text_color = "#000000"
        bar_edge_color = "#6B7280"
        positive_color = "#0F9D58"
        negative_color = "#DB4437"
    else:
        fig_facecolor = "#0B1020"
        ax_facecolor = "#0F172A"
        text_color = "#CBD5E1"
        grid_color = "#2A3248"
        spine_color = "#334155"
        pie_text_color = "#FFFFFF"
        bar_edge_color = "#E5E7EB"
        positive_color = "#7CFC00"
        negative_color = "#FF5C5C"

    labels = [r["quarter"] for r in rows]

    def _safe_num(v: Any, default: float = 0.0) -> float:
        """把 None/NaN/inf 轉成可繪圖安全數值，避免 matplotlib 崩潰。"""
        try:
            n = float(v)
            if np.isnan(n) or np.isinf(n):
                return default
            return n
        except Exception:
            return default

    revs = [_safe_num(r.get("revenue"), 0.0) for r in rows]
    net_income = [_safe_num(r.get("net_income"), 0.0) for r in rows]
    margins = [_safe_num(r.get("net_margin"), 0.0) for r in rows]

    def _pct(curr: float, prev: float) -> str:
        if prev == 0:
            return "N/A"
        p = (curr - prev) / abs(prev) * 100
        return f"{p:+.1f}%"

    rev_pct = ["-"]
    ni_pct = ["-"]
    for i in range(1, len(rows)):
        rev_pct.append(_pct(revs[i], revs[i - 1]))
        ni_pct.append(_pct(net_income[i], net_income[i - 1]))

    x = np.arange(len(labels))
    fig = plt.figure(figsize=(12, 8), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, width_ratios=[2.4, 1.3], height_ratios=[1, 1])
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[:, 1])

    fig.patch.set_facecolor(fig_facecolor)
    for ax in (ax1, ax2, ax3):
        ax.set_facecolor(ax_facecolor)
        if ax in (ax1, ax2):
            ax.tick_params(colors=text_color)
        for spine in ax.spines.values():
            spine.set_color(spine_color)

    # 細版柱狀圖：營收 + 淨利
    width = 0.28
    bars1 = ax1.bar(x - width / 2, revs, width=width, color="#46C2FF", edgecolor=bar_edge_color, linewidth=0.6, label="Revenue")
    bars2 = ax1.bar(x + width / 2, net_income, width=width, color=positive_color, edgecolor=bar_edge_color, linewidth=0.6, label="Net Income")

    ax1.set_title(f"{symbol} 1Y Quarterly: Revenue / Net Income")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.title.set_color(text_color)
    ax1.grid(axis="y", linestyle="--", alpha=0.3, color=grid_color)

    # 繪製 2 季度移動平均線 (MA2)
    def _calc_ma2(data: list[float]) -> list[float]:
        res = []
        for i in range(len(data)):
            if i == 0:
                res.append(data[0])
            else:
                res.append((data[i-1] + data[i]) / 2)
        return res

    ma2_rev = _calc_ma2(revs)
    ma2_ni = _calc_ma2(net_income)

    ax1.plot(x, ma2_rev, color="#A78BFA", marker="o", markersize=4, linestyle="-", linewidth=1.5, label="Rev MA(2Q)")
    ax1.plot(x, ma2_ni, color="#F472B6", marker="o", markersize=4, linestyle="-", linewidth=1.5, label="NI MA(2Q)")

    ax1.legend(facecolor=ax_facecolor, edgecolor=spine_color, labelcolor=text_color, loc="upper left", fontsize=8)

    for i, b in enumerate(bars1):
        pct_color = positive_color if str(rev_pct[i]).startswith("+") else negative_color if str(rev_pct[i]).startswith("-") else text_color
        ax1.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{format_number(revs[i])}\n({rev_pct[i]})",
            ha="center",
            va="bottom",
            fontsize=7,
            color=pct_color,
            weight="bold",
        )
    for i, b in enumerate(bars2):
        pct_color = positive_color if str(ni_pct[i]).startswith("+") else negative_color if str(ni_pct[i]).startswith("-") else text_color
        ax1.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{format_number(net_income[i])}\n({ni_pct[i]})",
            ha="center",
            va="bottom",
            fontsize=7,
            color=pct_color,
            weight="bold",
        )

    # Net Margin Trend Chart
    bars3 = ax2.bar(x, margins, width=0.40, color="#FFD166", edgecolor=bar_edge_color, linewidth=0.6, label="Margin")
    
    # 繪製 Net Margin MA(2Q)
    ma2_margin = _calc_ma2(margins)
    ax2.plot(x, ma2_margin, color="#46C2FF", marker="o", markersize=4, linestyle="-", linewidth=1.5, label="MA(2Q)")
    
    ax2.set_title(f"{symbol} 1Y Quarterly: Net Margin (%)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.title.set_color(text_color)
    ax2.legend(facecolor=ax_facecolor, edgecolor=spine_color, labelcolor=text_color, loc="upper left", fontsize=8)
    ax2.grid(axis="y", linestyle="--", alpha=0.3, color=grid_color)
    for i, b in enumerate(bars3):
        pct_color = positive_color if margins[i] >= 0 else negative_color
        ax2.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{margins[i]:.1f}%",
            ha="center",
            va="bottom",
            fontsize=8,
            color=pct_color,
            weight="bold",
        )

    # Profit Mix Pie Chart: Prioritize latest quarter income statement composition
    latest_qis = getattr(yf.Ticker(symbol.upper().strip()), "quarterly_income_stmt", None)
    pie_labels: list[str] = []
    pie_vals: list[float] = []
    try:
        if latest_qis is not None and not getattr(latest_qis, "empty", True) and len(latest_qis.columns) > 0:
            c = latest_qis.columns[-1]
            candidates = [
                ("Gross Profit", "Gross Profit"),
                ("Operating Income", "Operating Income"),
                ("Net Income", "Net Income"),
            ]
            for key, alias in candidates:
                if key in latest_qis.index:
                    v = latest_qis.loc[key, c]
                    if isinstance(v, (int, float)) and abs(v) > 0:
                        pie_labels.append(alias)
                        pie_vals.append(abs(float(v)))
    except Exception:
        pie_labels, pie_vals = [], []

    # fallback: If components unavailable, use last year revenue proportion
    if not pie_vals:
        pie_labels = labels
        pie_vals = [abs(_safe_num(v, 0.0)) for v in revs]

    total = sum(pie_vals)
    if total <= 0:
        ax3.text(0.5, 0.5, "N/A", ha="center", va="center", color=text_color, fontsize=12)
        ax3.set_title(f"{symbol} Profit Mix", color=text_color)
    else:
        wedges, texts, autotexts = ax3.pie(
            pie_vals,
            labels=pie_labels,
            autopct="%1.1f%%",
            textprops={"color": text_color, "fontsize": 8},
            colors=["#46C2FF", "#7CFC00", "#FFD166", "#A78BFA", "#F472B6"],
            wedgeprops={"edgecolor": fig_facecolor, "linewidth": 0.8},
        )
        
        # 增強圓餅圖內百分比的能見度
        bbox_color = "#000000" if theme_name == "dark" else "#FFFFFF"
        for autotext in autotexts:
            autotext.set_color(pie_text_color)
            autotext.set_weight("bold")
            autotext.set_bbox(dict(facecolor=bbox_color, alpha=0.5, edgecolor="none", pad=1.5))
            
        ax3.set_title(f"{symbol} Profit Mix", color=text_color)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_fin_compare_chart_buffer(symbols: list[str]) -> io.BytesIO | None:
    """Generate /fin compare merged chart (2~3 symbols): Revenue, Net Income, Net Margin."""
    clean_symbols = [str(s).upper().strip() for s in (symbols or []) if str(s).strip()]
    if len(clean_symbols) < 2:
        return None
    clean_symbols = clean_symbols[:3]

    data_map: dict[str, list[dict[str, Any]]] = {}
    for sym in clean_symbols:
        rows = get_recent_quarterly_financials(sym, limit=4)
        if len(rows) >= 2:
            data_map[sym] = rows
    if len(data_map) < 2:
        return None

    try:
        import matplotlib as mpl
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        logging.warning("matplotlib unavailable for fin compare chart: %s", exc)
        return None

    setup_matplotlib_cjk_font(mpl)

    def _avg(values: list[float]) -> float:
        valid = [v for v in values if isinstance(v, (int, float))]
        return float(sum(valid) / len(valid)) if valid else 0.0

    x = np.arange(len(data_map))
    symbols_order = list(data_map.keys())
    rev_vals = []
    ni_vals = []
    margin_vals = []
    for sym in symbols_order:
        rows = data_map[sym]
        rev_vals.append(_avg([float(r.get("revenue") or 0) for r in rows]))
        ni_vals.append(_avg([float(r.get("net_income") or 0) for r in rows]))
        margin_vals.append(_avg([float(r.get("net_margin") or 0) for r in rows]))

    fig, axes = plt.subplots(1, 3, figsize=(14, 5), constrained_layout=True)
    fig.patch.set_facecolor("#0B1020")
    for ax in axes:
        ax.set_facecolor("#0F172A")
        ax.tick_params(colors="#CBD5E1")
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.grid(axis="y", linestyle="--", alpha=0.3, color="#2A3248")

    colors = ["#46C2FF", "#7CFC00", "#FFD166"]
    bars1 = axes[0].bar(x, rev_vals, color=colors[: len(symbols_order)], edgecolor="#E5E7EB", linewidth=0.6)
    bars2 = axes[1].bar(x, ni_vals, color=colors[: len(symbols_order)], edgecolor="#E5E7EB", linewidth=0.6)
    bars3 = axes[2].bar(x, margin_vals, color=colors[: len(symbols_order)], edgecolor="#E5E7EB", linewidth=0.6)

    axes[0].set_title("Avg Revenue (Last 4Q)", color="#F8FAFC")
    axes[1].set_title("Avg Net Income (Last 4Q)", color="#F8FAFC")
    axes[2].set_title("Avg Net Margin % (Last 4Q)", color="#F8FAFC")

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(symbols_order)

    for i, b in enumerate(bars1):
        axes[0].text(b.get_x() + b.get_width() / 2, b.get_height(), format_number(rev_vals[i]), ha="center", va="bottom", fontsize=8, color="#CBD5E1")
    for i, b in enumerate(bars2):
        axes[1].text(b.get_x() + b.get_width() / 2, b.get_height(), format_number(ni_vals[i]), ha="center", va="bottom", fontsize=8, color="#CBD5E1")
    for i, b in enumerate(bars3):
        axes[2].text(b.get_x() + b.get_width() / 2, b.get_height(), f"{margin_vals[i]:.1f}%", ha="center", va="bottom", fontsize=8, color="#CBD5E1")

    fig.suptitle("/fin compare Merged Financial Comparison", color="#F8FAFC", fontsize=13)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


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
            group_by="ticker",
            auto_adjust=True,
            prepost=True,
            progress=False,
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
                        return float(match["Close"].iloc[0])
                    return None

                def get_price_ytd() -> float | None:
                    ytd_date = datetime(datetime.now().year, 1, 1)
                    match = df[df.index >= ytd_date.strftime("%Y-%m-%d")]
                    if not match.empty:
                        return float(match["Close"].iloc[0])
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


def fetch_insider_transactions(symbol: str, limit: int = 15) -> list[dict[str, Any]]:
    """獲取內線交易紀錄 (Form 4)。"""
    if not finnhub_client:
        return []
    try:
        # 獲取最近一年的數據
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        res = finnhub_client.stock_insider_transactions(symbol, _from=start_date, to=end_date)
        data = res.get("data", [])
        # 按日期降序排列
        data.sort(key=lambda x: x.get("filingDate", ""), reverse=True)
        return data[:limit]
    except Exception as exc:
        logging.warning("fetch_insider_transactions failed for %s: %s", symbol, exc)
        return []


def fetch_institutional_ownership(symbol: str, limit: int = 10) -> list[dict[str, Any]]:
    """獲取機構持倉紀錄 (13F)。"""
    if not finnhub_client:
        return []
    try:
        res = finnhub_client.institutional_ownership(symbol)
        data = res.get("data", [])
        # 按持股數量或最新報表日期排序
        data.sort(key=lambda x: x.get("reportDate", ""), reverse=True)
        return data[:limit]
    except Exception as exc:
        logging.warning("fetch_institutional_ownership failed for %s: %s", symbol, exc)
        return []


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
                    news_list.append(
                        {
                            "title": n.get("title") or "",
                            "description": n.get("description") or "",
                            "source": (n.get("source") or {}).get("name", "NewsAPI"),
                            "url": n.get("url") or "",
                            "publishedAt": n.get("publishedAt") or "",
                        }
                    )
        except Exception as exc:
            logging.warning("NewsAPI failed for %s: %s", symbol, exc)

    # 無論 NewsAPI 是否成功，都嘗試從 Yahoo 補充（Yahoo 通常有更及時的個股消息）
    try:
        yf_news = yf.Ticker(symbol).news or []
        for n in yf_news[:limit]:
            # 避免重複 (比對標題)
            if any(n.get("title") == existing.get("title") for existing in news_list):
                continue
            news_list.append(
                {
                    "title": n.get("title", ""),
                    "description": n.get("summary", "") or n.get("publisher", ""),
                    "source": n.get("publisher", "Yahoo Finance"),
                    "url": n.get("link", ""),
                    "publishedAt": n.get("providerPublishTime", ""),
                }
            )
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
                    news_list.append(
                        {
                            "title": n.get("title") or "",
                            "description": n.get("description") or "",
                            "source": (n.get("source") or {}).get("name", "NewsAPI"),
                            "url": n.get("url") or "",
                            "publishedAt": n.get("publishedAt") or "",
                        }
                    )
        except Exception as exc:
            logging.debug("NewsAPI filtered search failed for %s: %s", query, exc)

    # 如果 Domain 限制找不到，或者 NEWS_API_KEY 不存在，走全網/Yahoo 降級搜尋
    if not news_list:
        return fetch_news_multi(query, limit=limit)

    news_list.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return news_list[:limit]
