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
import sec_api
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
    """全面切換至 SEC API 獲取財報資料。"""
    df = sec_api.fetch_sec_financials(symbol)
    if df is None or df.empty:
        return []
    
    # 轉換為舊有 list[dict] 格式以維持相容性，但數據來源已更新
    latest_df = df.tail(limit)
    result = []
    for _, row in latest_df.iterrows():
        result.append({
            "quarter": row['end'].strftime('%Y-%m-%d'),
            "revenue": row['revenue'],
            "net_income": row['net_income'],
            "net_margin": (row['net_income'] / row['revenue'] * 100) if row['revenue'] else 0,
            "eps": row['eps'],
            "gross_profit": row.get('gross_profit'),
            "op_income": row.get('op_income')
        })
    return result


def generate_professional_chart(df: pd.DataFrame, symbol: str, theme: str = "dark") -> io.BytesIO | None:
    """生成專業級三面板財報圖表：甜甜圈圖、Combo 圖與 EPS 長條圖。"""
    if df is None or df.empty or len(df) < 2:
        return None

    try:
        import matplotlib as mpl
        mpl.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except Exception:
        return None

    setup_matplotlib_cjk_font(mpl)
    is_light = str(theme).lower() == "light"
    plt.style.use('default' if is_light else 'dark_background')

    # 高級配色池 (鮮豔版)
    COLOR_REV = '#26C6DA'     # 深松石綠
    COLOR_NI = '#EC407A'      # 質感粉紅
    COLOR_MARGIN = '#FFB300'  # 琥珀金
    COLOR_EPS = '#7CFF4D'     # 亮螢光綠
    DONUT_COLORS = ["#409FE4", "#C03BD8", "#50CD54", "#E7EA3B"]
    
    bg_color = '#F8FAFC' if is_light else '#0B0E14'
    fg_color = '#0F172A' if is_light else '#F8FAFC'
    badge_bg = '#FFFFFF' if is_light else 'black'
    badge_alpha = 0.78 if is_light else 0.5

    # 建立 3x1 垂直佈局
    fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(12, 18), facecolor=bg_color, gridspec_kw={'height_ratios': [1, 1, 1]})
    mpl.rcParams.update({
        'axes.titlesize': 22,
        'axes.labelsize': 17,
        'xtick.labelsize': 15,
        'ytick.labelsize': 15,
        'legend.fontsize': 14,
    })
    
    def format_money(y, pos):
        """自適應金額格式化，移除科學記號"""
        abs_y = abs(y)
        if abs_y >= 1e9: return f'${y*1e-9:.1f}B'
        if abs_y >= 1e6: return f'${y*1e-6:.1f}M'
        return f'${y:,.1f}'

    money_fmt = FuncFormatter(format_money)
    plot_df = df.tail(5).copy()
    plot_df['quarter'] = plot_df['end'].dt.strftime('%y-Q%q')
    plot_df['margin'] = (plot_df['net_income'] / plot_df['revenue'] * 100).fillna(0)
    
    # 1. 甜甜圈圖 (Donut Chart) - 收入與利潤組成
    latest = plot_df.iloc[-1]
    rev_val = float(latest['revenue'])

    if symbol.upper() == 'NVDA':
        vals = [rev_val * 0.78, rev_val * 0.22]
        labs = ['運算與網路', '圖形']
    else:
        gp = latest.get('gross_profit', rev_val * 0.6)
        ni = latest.get('net_income', 0)
        vals = [max(0, rev_val - gp), max(0, gp - float(ni)), max(0, float(ni))]
        labs = ['營業成本', '營運/稅費', '淨利']

    # 環形圖高對比鮮豔配色
    colors = DONUT_COLORS
    wedges, texts, autotexts = ax0.pie(vals, autopct='%1.1f%%', startangle=140, 
                                     colors=colors[:len(vals)], pctdistance=0.8,
                                     wedgeprops={'width': 0.45, 'edgecolor': '#0B0E14', 'linewidth': 3})

    for t in autotexts:
        t.set_fontsize(15)
        t.set_fontweight("bold")
        t.set_color(fg_color)
        t.set_bbox(dict(facecolor=badge_bg, alpha=badge_alpha, edgecolor='none', boxstyle='round,pad=0.25'))
    for t in texts:
        t.set_fontsize(15)
        t.set_fontweight('bold')
        t.set_color(fg_color)
        t.set_bbox(dict(facecolor=badge_bg, alpha=(0.72 if is_light else 0.45), edgecolor='none', boxstyle='round,pad=0.2'))

    ax0.set_title(f"{symbol} 營收結構拆解", fontsize=23, fontweight='bold', pad=18, color=fg_color)
    ax0.text(
        0,
        0,
        f"總營收\n{format_money(rev_val, 0)}",
        ha='center',
        va='center',
        fontsize=20,
        fontweight='bold',
        color=fg_color,
        bbox=dict(facecolor=badge_bg, alpha=badge_alpha, edgecolor='none', boxstyle='round,pad=0.35')
    )
    ax0.legend(wedges, labs, loc="lower center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False, fontsize=14, labelcolor=fg_color)

    # 2. Combo 圖 - 營收與獲利成長 (雙Y軸)
    x = np.arange(len(plot_df))
    width = 0.35
    ax1.bar(x - width/2, plot_df['revenue'], width, label='營收', color=COLOR_REV, alpha=0.88)
    ax1.bar(x + width/2, plot_df['net_income'], width, label='淨利', color=COLOR_NI, alpha=0.9)
    ax1.yaxis.set_major_formatter(money_fmt)
    
    ax1_r = ax1.twinx()
    ax1_r.plot(x, plot_df['margin'], color=COLOR_MARGIN, marker='o', label='淨利率 %', linewidth=3.0)
    ax1_r.yaxis.set_major_formatter(FuncFormatter(lambda y, p: f'{y:.1f}%'))
    
    margin_max = plot_df['margin'].max()
    ax1_r.set_ylim(0, max(margin_max * 1.3, 20)) # 至少給 20% 空間避免畫面太擠
    
    ax1.set_title(f"{symbol} 營收與獲利趨勢", fontsize=23, fontweight='bold', pad=16, color=fg_color)
    ax1.set_xticks(x)
    ax1.set_xticklabels(plot_df['quarter'])
    
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax1_r.get_legend_handles_labels()
    ax1.tick_params(colors=fg_color)
    ax1_r.tick_params(colors=fg_color)
    ax1.legend(h1+h2, l1+l2, loc='upper left', fontsize=14)

    # 3. EPS 長條圖 + 移動平均線
    eps_bars = ax2.bar(x, plot_df['eps'], color=COLOR_EPS, alpha=0.82, width=0.5, label='每股盈餘 EPS')
    eps_ma = plot_df['eps'].rolling(window=3, min_periods=1).mean()
    ax2.plot(x, eps_ma, color=('#334155' if is_light else '#FFFFFF'), linewidth=2.8, marker='o', markersize=6, label='EPS 移動平均(3季)')
    ax2.bar_label(eps_bars, fmt='$%.2f', padding=5, color=fg_color, fontweight='bold', fontsize=14)
    ax2.set_title(f"{symbol} 每股盈餘（EPS）", fontsize=23, fontweight='bold', pad=16, color=fg_color)
    ax2.set_ylabel('EPS（美元）', fontsize=17, color=fg_color)
    ax2.set_xticks(x)
    ax2.set_xticklabels(plot_df['quarter'])
    ax2.set_ylim(0, max(plot_df['eps']) * 1.25)
    ax2.tick_params(colors=fg_color)
    ax2.legend(loc='upper left', fontsize=14)

    for ax in (ax0, ax1, ax2, ax1_r):
        ax.set_facecolor(bg_color)

    plt.tight_layout(pad=4.0)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_fin_chart_buffer(symbol: str, theme: str = "dark") -> io.BytesIO | None:
    """相容舊介面，但內部使用全新的 SEC 數據源與專業圖表邏輯。"""
    df = sec_api.fetch_sec_financials(symbol)
    return generate_professional_chart(df, symbol.upper(), theme=theme)


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
        mpl.use('Agg') # 確保使用非互動式後端
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
