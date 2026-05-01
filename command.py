"""command.py
所有 Telegram 指令與業務流程核心。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
import math
import random
import logging
import re
from datetime import datetime
import math
from typing import Any

import psutil

import ai_core
import brain
import database
import frame
import market_api
from config import BOT_START_TIME, VERSION

STOCK_RE = re.compile(r"\b[A-Z]{2,5}\b")
FIN_COMPARE_STATE: dict[int, list[str]] = {}


def get_system_status() -> str:
    """獲取伺服器資源狀態與運行時間。"""
    try:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        # 計算運行時間
        uptime = datetime.now() - BOT_START_TIME
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}天 {hours}小時 {minutes}分" if days > 0 else f"{hours}小時 {minutes}分 {seconds}秒"

        return (
            f"• CPU 使用率: {cpu_pct}%\n"
            f"• RAM 使用率: {ram.percent}% ({ram.used // 1024 // 1024}MB / {ram.total // 1024 // 1024}MB)\n"
            f"• 硬碟空間: {disk.percent}% ({disk.free // 1024 // 1024 // 1024}GB 剩餘)\n"
            f"• 系統已運行: {uptime_str}"
        )
    except Exception as exc:
        logging.warning("get_system_status failed: %s", exc)
        return "• 系統資源資訊暫時無法取得"


def build_portfolio_summary(user_id: int) -> dict[str, float]:
    portfolio = database.get_aggregated_portfolio(user_id)
    total_cost = 0.0
    total_value = 0.0
    for symbol, item in portfolio.items():
        curr = market_api.get_fast_price(symbol)
        shares = float(item["shares"])
        total_cost += float(item["total_cost"])
        if isinstance(curr, (int, float)):
            total_value += float(curr) * shares
    pl_val = total_value - total_cost
    pl_pct = (pl_val / total_cost * 100) if total_cost > 0 else 0.0
    return {"total_cost": total_cost, "total_value": total_value, "pl_val": pl_val, "pl_pct": pl_pct}


def resolve_news_target(query: str) -> tuple[str, str]:
    resolved = market_api.resolve_news_topic(query)
    return resolved.get("target", query), resolved.get("note", "")


def _normalize_symbols(symbol_text: str) -> list[str]:
    tokens = re.split(r"[\s,;]+", symbol_text.strip())
    symbols: list[str] = []
    for token in tokens:
        token = token.strip().upper()
        if not token:
            continue
        token = re.sub(r"[^A-Z0-9\.\-]", "", token)
        if 1 <= len(token) <= 6:
            symbols.append(token)
    return symbols


def _is_stock_symbol(query: str) -> bool:
    if not query:
        return False
    symbol = query.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", symbol):
        return False
    snapshot = market_api.get_stock_snapshot(symbol)
    return isinstance(snapshot.get("price"), (int, float)) and snapshot.get("price") != 0


def _build_fin_compare_message(symbols: list[str], user_id: int) -> str:
    user_name = database.get_user_display_name(user_id)
    holdings = database.get_aggregated_portfolio(user_id)
    fundamentals_map: dict[str, dict[str, Any]] = {}
    news_map: dict[str, list[dict[str, str]]] = {}
    missing: list[str] = []

    for symbol in symbols:
        fundamentals = market_api.get_stock_fundamentals(symbol)
        if not fundamentals:
            missing.append(symbol)
            continue
        fundamentals_map[symbol] = fundamentals
        news_map[symbol] = market_api.fetch_news_multi(symbol, limit=2)

    if missing:
        return f"❌ 無法取得以下代號的財務資料：{', '.join(missing)}。請確認代號是否正確。"

    sections: list[str] = [f"📊 財務比較：{' vs '.join(symbols)}", "━━━━━━━━━━━━━━"]
    for symbol in symbols:
        data = fundamentals_map[symbol]
        sections.append(
            f"【{symbol}】\n"
            f"公司：{data.get('company_name', data.get('symbol', symbol))}\n"
            f"現價：{data.get('current_price', 'N/A')} | 市值：{data.get('market_cap', 'N/A')}\n"
            f"TTM 營收：{data.get('revenue_ttm', 'N/A')} | TTM 淨利：{data.get('net_income', 'N/A')}\n"
            f"EPS：{data.get('trailing_eps', 'N/A')} / {data.get('forward_eps', 'N/A')}\n"
            f"P/E：{data.get('trailing_pe', 'N/A')} / {data.get('forward_pe', 'N/A')}\n"
            f"毛利率：{data.get('gross_margin', 'N/A')} | 淨利率：{data.get('profit_margin', 'N/A')}\n"
            f"52 週：{data.get('year_low', 'N/A')} - {data.get('year_high', 'N/A')}\n"
            + (
                f"最新季：{data.get('latest_quarter')}，EPS：{data.get('latest_quarter_eps', 'N/A')}，營收：{data.get('latest_quarter_revenue', 'N/A')}\n"
                if data.get('latest_quarter')
                else ""
            )
        )
        if symbol in holdings:
            position = holdings[symbol]
            sections.append(
                f"持股：{position.get('shares', 0):.2f} 股，成本 ${position.get('avg_cost', 0):.2f}\n"
            )
        if news_map[symbol]:
            news_lines = []
            for idx, item in enumerate(news_map[symbol], start=1):
                title = item.get('title', '無標題').strip()
                source = item.get('source', '未知')
                url = item.get('url', '')
                news_lines.append(f"{idx}. {title} ({source})\n   {url}")
            sections.append("最新消息：\n" + "\n".join(news_lines))
        sections.append("━━━━━━━━━━━━━━")

    ai_analysis = ai_core.compare_financials(symbols, fundamentals_map, news_map, user_name, holdings, user_id=user_id)
    sections.append("AI 評析：")
    sections.append(ai_analysis)
    return "\n".join(sections)


def get_price_volume_signal(quote: dict[str, Any]) -> str:
    vol = quote.get("volume_note", "N/A")
    diff = float(quote.get("diff", 0) or 0)
    if vol == "放量":
        if diff > 0:
            return "放量上漲"
        if diff < 0:
            return "放量下跌"
        return "放量震盪"
    if vol == "量縮":
        if diff > 0:
            return "量縮價漲"
        if diff < 0:
            return "量縮價跌"
        return "量縮盤整"
    if vol == "量能持平":
        if diff > 0:
            return "價漲量平"
        if diff < 0:
            return "價跌量平"
        return "價量震盪"
    return "量價訊號不明"


def build_macro_section(quotes: list[dict[str, Any]]) -> str:
    lines: list[str] = ["🌍 宏觀即時觀測", "━━━━━━━━━━━━━━"]
    signal_summary: list[str] = []
    for quote in quotes:
        symbol = quote.get("symbol", "N/A")
        status = market_api.format_quote(quote)
        signal = get_price_volume_signal(quote)
        lines.append(f"• {symbol}：{status}｜{signal}")
        signal_summary.append(signal)

    summary_notes: list[str] = []
    if any("放量上漲" == s for s in signal_summary):
        summary_notes.append("局部呈放量上漲，短線趨勢偏多。")
    if any("放量下跌" == s for s in signal_summary):
        summary_notes.append("放量下跌訊號出現，風險偏高。")
    if any("量縮價跌" == s for s in signal_summary):
        summary_notes.append("量縮價跌，可能是回檔整理或買盤不足。")
    if not summary_notes:
        summary_notes.append("目前量價訊號尚未出現明顯偏多偏空結論。")

    lines.append("")
    lines.append("• 量價核心判斷：" + " ".join(summary_notes))
    return "\n".join(lines)


def build_fibonacci_section() -> str:
    summary = market_api.get_stock_history_summary("^GSPC")
    high = summary.get("range_high_3mo")
    low = summary.get("range_low_3mo")
    current = summary.get("price")
    if not isinstance(high, (int, float)) or not isinstance(low, (int, float)) or not isinstance(current, (int, float)):
        return "📐 斐波那契回撤參考\n━━━━━━━━━━━━━━\nS&P500 斐波位置數據暫時無法取得。"

    diff = high - low
    levels = {
        0.382: high - diff * 0.382,
        0.618: high - diff * 0.618,
        1.618: high + diff * 0.618,
    }
    lines = ["📐 斐波那契位置參考", "━━━━━━━━━━━━━━"]
    lines.append(f"S&P500 3個月區間：{low:.2f} - {high:.2f}")
    lines.append(f"當前價：{current:.2f}")
    lines.append("• 0.382 / 0.618 為核心回撤支撐；1.618 為延伸目標。")
    for ratio, value in levels.items():
        lines.append(f"• {ratio:.3f} 位置：{value:.2f}")
    return "\n".join(lines)


def build_risk_section(quotes: list[dict[str, Any]]) -> str:
    sp_quote = next((q for q in quotes if q.get("symbol") == "標普500"), None)
    vix_quote = next((q for q in quotes if q.get("symbol") == "VIX"), None)
    signals: list[str] = ["目前評估量價風險。"]

    if sp_quote:
        sp_signal = get_price_volume_signal(sp_quote)
        if sp_signal == "放量上漲":
            signals.append("標普500 放量上漲，若估值仍延伸，需警覺回檔壓力。")
        elif sp_signal == "放量下跌":
            signals.append("標普500 放量下跌，風險明顯提高，空方壓力較大。")
        elif sp_signal == "量縮價跌":
            signals.append("量縮價跌表示賣壓尚在，短線應先觀察。")
        elif sp_signal == "量縮價漲":
            signals.append("量縮價漲為弱勢反彈，成交量尚未放大。")
        else:
            signals.append(f"標普500 量價訊號：{sp_signal}。")

    if vix_quote and isinstance(vix_quote.get("price"), (int, float)):
        vix_diff = float(vix_quote.get("diff", 0) or 0)
        vix_status = market_api.format_quote(vix_quote)
        direction = "上升" if vix_diff > 0 else "下降" if vix_diff < 0 else "橫盤"
        signals.append(f"VIX {vix_status}，風險指標{direction}。")

    return "\n".join([
        "⚠️ 當前風險評估",
        "━━━━━━━━━━━━━━",
        *[f"• {note}" for note in signals],
    ])


def build_now_dashboard(user_name: str, user_id: int, with_ai: bool = True) -> list[str]:
    targets = ["標普500", "納斯達克", "黃金", "原油", "比特幣", "VIX"]
    quotes = [market_api.get_macro_quote(t) for t in targets]
    portfolio = build_portfolio_summary(user_id)

    macro_section = build_macro_section(quotes)
    fib_section = build_fibonacci_section()
    risk_section = build_risk_section(quotes)

    tactical = "暫時無法產生 AI 戰術建議。"
    if with_ai:
        try:
            model_pref = database.get_user_model_preference(user_id)
            tactical = ai_core.get_market_tactical_comment(
                "\n".join(q.get("symbol", "") + ": " + market_api.format_quote(q) for q in quotes),
                portfolio,
                user_name,
                user_id=user_id,
                model=model_pref,
            )
        except Exception as exc:
            logging.warning("AI tactical failed: %s", exc)

    ai_section = "🤖 AI 交易副官結語\n━━━━━━━━━━━━━━\n" + tactical
    return [macro_section, fib_section, risk_section, ai_section]


def cmd_now(user_id: int, user_name: str):
    return build_now_dashboard(user_name, user_id, with_ai=True)


def cmd_list(user_id: int, page: int = 1) -> tuple[str, int]:
    """獲取分頁後的持股列表。回傳 (文字內容, 總頁數)。"""
    portfolio = database.get_aggregated_portfolio(user_id)
    all_symbols = sorted(list(portfolio.keys()))
    total_items = len(all_symbols)
    page_size = 10
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1
    
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_symbols = all_symbols[start_idx:end_idx]
    
    rows = []
    for symbol in page_symbols:
        item = portfolio[symbol]
        rows.append({
            "symbol": symbol,
            "quantity": item["shares"],
            "avg_cost": item["avg_cost"],
            "current_price": market_api.get_fast_price(symbol),
        })
    
    text = frame.portfolio_list(rows, database.get_realized_profit(user_id), page, total_pages)
    return text, total_pages


def cmd_buy(text: str, user_id: int) -> str:
    parts = text.split()
    if len(parts) != 4:
        return "用法：/buy [代號] [價格] [股數]\n例如：/buy NVDA 130 10"
    try:
        symbol = parts[1].upper()
        price = float(parts[2])
        qty = float(parts[3])
        if price <= 0 or qty <= 0:
            return "價格與股數必須大於 0。"
        database.save_trade(user_id, symbol, price, qty)
        return frame.buy_success(symbol, price, qty)
    except Exception as exc:
        return f"❌ 買入記錄失敗：{exc}"


def cmd_sell(text: str, user_id: int) -> str:
    parts = text.split()
    if len(parts) != 4:
        return "用法：/sell [代號] [賣出價格] [股數]\n例如：/sell NVDA 150 5"
    try:
        symbol = parts[1].upper()
        price = float(parts[2])
        qty = float(parts[3])
        if price <= 0 or qty <= 0:
            return "價格與股數必須大於 0。"
        profit, rem = database.delete_trade(user_id, symbol, price, qty)
        return frame.sell_success(symbol, price, qty, profit, rem)
    except Exception as exc:
        return f"❌ 賣出記錄失敗：{exc}"


def cmd_watch(text: str, user_id: int) -> str:
    parts = text.split()
    if len(parts) < 2:
        return frame.watch_guide()
    action = parts[1].lower()
    if action == "list":
        return frame.watch_list(database.get_watchlist(user_id))
    if action == "clear":
        database.clear_watchlist_db(user_id)
        return "🧹 雷達監控清單已全數清空。"
    if action in {"add", "del"} and len(parts) > 2:
        symbols = [p.upper() for p in parts[2:] if p.strip()]
        for s in symbols:
            if action == "add":
                database.add_watchlist(user_id, s)
            else:
                database.del_watchlist(user_id, s)
        return f"✅ 已批次{'新增' if action == 'add' else '移除'}：{', '.join(symbols)}"
    return frame.watch_guide()


def cmd_ask(text: str, user_name: str, user_id: int) -> list[str] | str:
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        return "🤖 用法：/ask [代號] [問題]\n例如：/ask NVDA 現在是否過熱？"
    symbol = parts[1].upper().strip()
    query = parts[2].strip()
    snapshot = market_api.get_stock_snapshot(symbol)
    news = market_api.fetch_news_multi(symbol, limit=3)
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}

    model_pref = database.get_user_model_preference(user_id)
    ai_answer = ai_core.ask_ai_investment_advice(
        symbol,
        query,
        snapshot,
        news,
        user_name,
        user_holdings=holdings,
        user_id=user_id,
        model=model_pref,
    )

    header = (
        f"🤖 AI 深度戰術分析：{symbol}\n"
        f"━━━━━━━━━━━━━━\n"
        f"問題：{query}\n"
        f"當前價位：{snapshot.get('price', 'N/A')}，"
        f"漲跌：{snapshot.get('diff', 'N/A')}，"
        f"漲幅：{snapshot.get('pct', 'N/A')}%\n"
        f"新聞摘要：{news[0].get('description','暫無新聞摘要。') if news else '暫無新聞摘要。'}\n"
        f"━━━━━━━━━━━━━━"
    )
    return [header, ai_answer]


def process_news_item_smart(symbol: str, news_item: dict[str, Any], user_name: str, user_id: int) -> str:
    """
    智慧新聞路由器：取代原本單一的 summarizer。
    自動偵測新聞內容是否包含財報關鍵字，若是則切換為財報快訊模式。
    """
    title = news_item.get("title", "").lower()
    desc = news_item.get("description", "").lower()
    model_pref = database.get_user_model_preference(user_id)
    
    # 財報季關鍵字池
    earnings_keywords = ["earnings", "q1", "q2", "q3", "q4", "財報", "業績", "guidance", "revenue", "eps", "財測"]
    
    if any(keyword in title or keyword in desc for keyword in earnings_keywords):
        return ai_core.summarize_earnings_report(symbol, news_item, user_name, model=model_pref, user_id=user_id)
    else:
        return ai_core.summarize_tech_news(symbol, news_item, user_name, model=model_pref, user_id=user_id)

def cmd_news(text: str, user_name: str, user_id: int) -> list[str]:
    """取得最相關的新聞，並以智慧模式詳細結構化回饋。支持隨機推播優先級：持股 > 監控 > 宏觀。"""

    watchlist = database.get_watchlist(user_id)
    holdings = database.get_aggregated_portfolio(user_id)
    portfolio_symbols = list(holdings.keys())
    macro_targets = ["S&P 500", "Nasdaq", "Gold", "Oil", "Bitcoin", "NVDA", "AAPL", "TSLA"]
    current_time_str = ai_core.get_current_time_str()

    parts = text.split()
    if len(parts) >= 2 and parts[1].lower() == "list":
        return [market_api.get_news_source_list()]

    raw_query = " ".join(parts[1:]).strip() if len(parts) >= 2 else ""
    
    is_random = False
    if raw_query == "":
        is_random = True
        # 優先級：持股 > 監控 > 宏觀
        if portfolio_symbols:
            raw_query = random.choice(portfolio_symbols)
        elif watchlist:
            raw_query = random.choice(watchlist)
        else:
            raw_query = random.choice(macro_targets)

    target, note = resolve_news_target(raw_query)

    news_items = market_api.fetch_news_filtered(target, limit=1)
    if not news_items and target != raw_query:
        news_items = market_api.fetch_news_filtered(raw_query, limit=1)

    if not news_items:
        fallback_query = "Federal Reserve OR Fed OR US economic data"
        news_items = market_api.fetch_news_filtered(fallback_query, limit=1)
        if news_items:
            target = fallback_query
            note = "未找到原始目標新聞，改查聯準會與美國宏觀經濟數據。"

    if not news_items:
        return [
            f"📌 查詢：{raw_query}\n"
            f"目前找不到相關新聞，可能是該標的近期無重大消息。\n"
            f"🕒 讀取時間：{current_time_str}"
        ]

    item = news_items[0]
    title = item.get("title", "無標題")
    source = item.get("source", "未知")
    published = item.get("publishedAt", "")
    published_text = published.replace("T", " ")[:19] if published else "未知時間"
    url = item.get("url", "")
    outline = item.get("description") or item.get("summary") or "暫無摘要。"
    outline = outline.strip().replace("\n", " ")

    if _is_stock_symbol(raw_query):
        symbol = raw_query.strip().upper()
        ai_answer = process_news_item_smart(symbol, item, user_name, user_id)
        header = f"📰 /news {symbol} 智慧解讀" + (" (隨機推播)" if is_random else "")
        snapshot = market_api.get_stock_snapshot(symbol)
        market_line = (
            f"現價：{snapshot.get('price', 'N/A')}，"
            f"漲跌：{snapshot.get('diff', 'N/A')}，"
            f"漲幅：{snapshot.get('pct', 'N/A')}%"
        )
    else:
        ai_prompt = (
            f"請以 /now 類似的『極度詳細』回饋模式，針對此新聞主題「{raw_query}」進行極度深度的宏觀分析。"
            "使用者要求：輸出長串、完整且結構化的內容，細節要講清楚，絕對不要斷句。分析應包含：\n"
            "1. 新聞大綱與核心觀點深度拆解。\n"
            "2. 對市場情緒、大盤走勢與各產業資產的短中長期影響判斷。\n"
            "3. 宏觀指標解讀（如利率、通膨、地緣政治等相關連動）。\n"
            "4. 具體的投資操作思路與後續關鍵觀察指標。"
        )
        model_pref = database.get_user_model_preference(user_id)
        ai_answer = ai_core.ask_model(
            ai_prompt,
            user_name,
            model=model_pref,
            user_id=user_id,
            temperature=0.35,
            max_output_tokens=3500,
        )
        header = f"📰 /news {raw_query} 詳細回饋" + (" (隨機推播)" if is_random else "")
        market_line = ""

    header_message = (
        f"{header}\n"
        f"🕒 讀取時間：{current_time_str}\n"
        f"🎯 查詢目標：{target} {note}\n"
        f"━━━━━━━━━━━━━━\n"
        f"標題：{title}\n"
        f"來源：{source}\n"
        f"發佈時間：{published_text}\n"
        f"原文：{url}\n"
        f"{market_line}\n"
        f"━━━━━━━━━━━━━━\n"
        f"摘要：{outline}\n"
        f"━━━━━━━━━━━━━━"
    )
    ai_message = f"🤖 AI 智慧戰術分析：\n{ai_answer}"
    return [header_message, ai_message]


def cmd_theme(text: str, user_name: str, user_id: int) -> str:
    """處理 /theme 指令，生成指定產業的深度速報"""
    parts = text.split()
    available_themes = list(market_api.TECH_THEMES.keys())
    
    if len(parts) < 2:
        return f"🤖 用法：/theme [主題]\n目前支援的主題：{', '.join(available_themes)}\n例如：/theme 核能"
    
    theme_input = parts[1].strip()
    # 模糊匹配
    matched_key = next((k for k in available_themes if k.upper() == theme_input.upper() or k == theme_input), None)
    
    if not matched_key:
        return f"❌ 未知的趨勢主題。目前支援：{', '.join(available_themes)}"
        
    query = market_api.TECH_THEMES[matched_key]
    # 先抓 RSS 看看有沒有相關的
    rss_news = market_api.fetch_tech_rss(limit=10)
    theme_news = [n for n in rss_news if matched_key.lower() in n['title'].lower() or matched_key.lower() in n['description'].lower()]
    
    # 如果 RSS 沒抓到，改抓 NewsAPI
    if len(theme_news) < 2:
        api_news = market_api.fetch_news_filtered(query, limit=5)
        theme_news.extend(api_news)
    
    if not theme_news:
        return f"⚠️ 目前找不到關於【{matched_key}】的最新市場情報。"
        
    news_text = "\n".join([f"- {n['title']}: {n['description']}" for n in theme_news[:3]])
    prompt = f"""
請根據以下最新新聞，為 {user_name} 撰寫一份【{matched_key} 產業趨勢速報】。
這是一份具備「最大算力」支持的深度報告，請務必詳盡分析。

要求：
1. 評估該產業目前的總體情緒（1-10分）。
2. 點出領頭羊公司的最新動態或技術突破。
3. 分析潛在的投資機會與供應鏈風險。
4. 提供具體的技術觀察方向與關鍵觀察指標。
5. 輸出必須長串且完整，細節講透徹，絕對禁止斷句。

新聞素材：
{news_text}
"""
    
    model_pref = database.get_user_model_preference(user_id)
    report = ai_core.ask_model(prompt, user_name, model=model_pref, user_id=user_id, temperature=0.4, max_output_tokens=2500)
    
    return f"🚀 【{matched_key} 未來趨勢速報】\n━━━━━━━━━━━━━━\n{report}"


def cmd_news_help() -> str:
    return frame.news_help_text()

def cmd_fin(text: str, user_id: int) -> str:
    parts = text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].strip():
        return "📊 用法：/fin [代號] 或 /fin compare [代號1] [代號2]。"

    if parts[1].lower() == "compare":
        symbols = _normalize_symbols(parts[2] if len(parts) > 2 else "")
        pending = FIN_COMPARE_STATE.get(user_id, [])
        combined = list(dict.fromkeys(pending + symbols))

        if not combined:
            return (
                "📊 /fin compare 用法：\n"
                "• 直接輸入：/fin compare NVDA TSLA\n"
                "• 或分次輸入：/fin compare NVDA，接著 /fin compare TSLA\n"
                "請輸入 2 到 3 個股票代號。"
            )

        if len(combined) == 1:
            FIN_COMPARE_STATE[user_id] = combined
            return (
                f"📊 已暫存 {combined[0]}，請再輸入第二支代碼，或使用 /fin compare [第二支代號] 進行比較。"
            )

        if len(combined) > 3:
            FIN_COMPARE_STATE[user_id] = combined[:3]
            combined = combined[:3]
            return (
                f"📊 比較最多支援 3 支股票，目前已取前三支：{', '.join(combined)}。\n"
                f"請重新使用 /fin compare {' '.join(combined)} 進行比較。"
            )

        FIN_COMPARE_STATE.pop(user_id, None)
        return _build_fin_compare_message(combined, user_id)

    symbol = parts[1].strip().upper()
    fundamentals = market_api.get_stock_fundamentals(symbol)
    if not fundamentals:
        return f"❌ 無法取得 {symbol} 的財務資料，請確認代號是否正確。"
    return frame.fin_report(fundamentals)


def cmd_status(user_id: int) -> str:
    try:
        ok = brain.ping(user_id)
    except Exception:
        ok = False
    brain_status = brain.get_status_text(user_id)
    model_pref = database.get_user_model_preference(user_id)
    brain_status = f"{brain_status}\n• 模型偏好：{model_pref}"
    return frame.status_text(VERSION, brain_status, get_system_status(), ok)


def cmd_set_model(text: str, user_id: int) -> str:
    parts = text.split()
    if len(parts) == 1:
        current = database.get_user_model_preference(user_id)
        return f"目前回覆模型：{current}\n使用 /model flash 或 /model pro 來切換。"

    choice = parts[1].strip().lower()
    if choice not in {"flash", "pro"}:
        return "可設定模型：flash 或 pro。範例：/model pro"
    database.set_user_model_preference(user_id, choice)
    return f"✅ 已將回覆模型切換為：{choice}"


def cmd_op(text: str, user_id: int) -> str:
    """處理管理者指令 /op。"""
    logging.info(f"cmd_op called: text='{text}', user_id={user_id}")
    parts = text.split()
    current_model = database.get_user_model_preference(user_id)
    
    if len(parts) == 1:
        return frame.admin_op_text(current_model)
    
    sub = parts[1].lower()
    if sub == "help":
        return frame.admin_op_text(current_model)

    if sub == "model":
        if len(parts) < 3:
            return (
                f"🤖 AI 模型切換教學\n"
                f"━━━━━━━━━━━━━━\n"
                f"當前模型：`{current_model}`\n\n"
                f"用法：`/op model [flash|pro]`\n"
                f"• `flash`：反應速度快，適合日常查詢與初步分析。\n"
                f"• `pro`：分析深度高，適合複雜市場情境與戰術研究。"
            )
        choice = parts[2].lower()
        if choice not in {"flash", "pro"}:
            return "❌ 錯誤：模型僅支援 `flash` 或 `pro`。範例：`/op model pro`"
        database.set_user_model_preference(user_id, choice)
        return f"✅ 核心模型已更新為：`{choice}`\n即刻起所有 AI 分析將採用新模型。"
    
    if sub == "log":
        return "__TRIGGER_LOG__"
    
    if sub == "quota":
        return cmd_quota(user_id)
        
    return (
        f"❓ 未知的管理指令：`{sub}`\n\n"
        f"請使用 `/op help` 查看完整的管理者指令清單。"
    )


def cmd_quota(user_id: int) -> str:
    """獲取 Token 配額使用情況。"""
    used_today, _ = database.get_daily_tokens(user_id)
    from config import DAILY_TOKEN_LIMIT
    percent = (used_today / DAILY_TOKEN_LIMIT) * 100
    return frame.quota_text(used_today, DAILY_TOKEN_LIMIT, percent)


def _build_comprehensive_news(user_name: str, user_id: int) -> str:
    """內部輔助：建立綜合新聞摘要。"""
    sections = ["📰 美股顧問綜合情報摘要", "━━━━━━━━━━━━━━"]

    # 加入 RSS 科技新聞
    rss_news = market_api.fetch_tech_rss(limit=1)
    if rss_news:
        sections.append("【🌐 全球科技即時速報】\n" + ai_core.summarize_tech_news("Global Tech", rss_news[0], user_name, user_id=user_id))

    watchlist = database.get_watchlist(user_id)
    holdings = database.get_aggregated_portfolio(user_id)
    macro_targets = ["標普500", "納斯達克", "黃金"]
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(process_news_item_smart(t, news[0], user_name, user_id))
            break

    holdings = database.get_aggregated_portfolio(user_id)
    portfolio = list(holdings.keys())
    if portfolio:
        p_sym = portfolio[0]
        news = market_api.fetch_news_filtered(p_sym, limit=1)
        if news:
            sections.append(process_news_item_smart(p_sym, news[0], user_name, user_id))

    if watchlist:
        w_sym = watchlist[0]
        news = market_api.fetch_news_filtered(w_sym, limit=1)
        if news:
            sections.append(process_news_item_smart(w_sym, news[0], user_name, user_id))

    return "\n\n".join(sections)


def cmd_test(user_name: str = "User", user_id: int | None = None) -> str:
    """立即執行包含新聞與即時盤勢的完整市場報告。"""
    sections = ["🚀 美股顧問：完整市場報告", "━━━━━━━━━━━━━━"]
    
    # 1. 系統檢查
    sections.append("【核心狀態】")
    try:
        if brain.ping():
            sections.append(f"✅ AI 核心連線正常 ({brain.stats.last_model})")
        else:
            sections.append("❌ AI 核心連線異常")
    except Exception:
        sections.append("❌ AI 核心連線失敗")
    
    # 2. 即時盤勢 (Dashboard)
    sections.append("\n【即時盤勢摘要】")
    if user_id is not None:
        sections.append(build_now_dashboard(user_name, user_id, with_ai=True))
    else:
        sections.append(build_now_dashboard(user_name, 0, with_ai=True))
    
    # 3. 綜合新聞
    sections.append("\n【關鍵情報摘要】")
    if user_id is not None:
        sections.append(_build_comprehensive_news(user_name, user_id))
    else:
        sections.append(_build_comprehensive_news(user_name, 0))
    
    return "\n".join(sections)


def cmd_help() -> str:
    return frame.help_text()


def cmd_proactive_news(user_name: str = "User", user_id: int | None = None) -> str:
    # 這裡由 main_bot 的循環邏輯決定發什麼，或者在這裡隨機挑選
    sections = ["⏰ 美股顧問自動情報推播", "━━━━━━━━━━━━━━"]

    # 宏觀 (20 分鐘循環在 main_bot 處理)
    macro_targets = ["標普500", "納斯達克", "黃金", "原油", "比特幣"]
    watchlist = database.get_watchlist(user_id) if user_id is not None else []
    m_t = random.choice(macro_targets)
    news = market_api.fetch_news_filtered(m_t, limit=1)
    if news:
        sections.append(process_news_item_smart(m_t, news[0], user_name, user_id or 0))

    # 持股與觀察也隨機推一個
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    portfolio = list(holdings.keys())
    if portfolio:
        p_sym = random.choice(portfolio)
        news = market_api.fetch_news_filtered(p_sym, limit=1)
        if news:
            sections.append(process_news_item_smart(p_sym, news[0], user_name, user_id or 0))

    if watchlist:
        w_sym = random.choice(watchlist)
        news = market_api.fetch_news_filtered(w_sym, limit=1)
        if news:
            sections.append(process_news_item_smart(w_sym, news[0], user_name, user_id or 0))

    if len(sections) <= 2:
        return "💡 自動推播：目前暫無最新新聞或名單為空。"

    return "\n\n".join(sections)


def cmd_pre_market_report(user_name: str = "User", user_id: int | None = None) -> str:
    sections = ["🔔 美股開盤預備匯報 (開盤前 30 分鐘)", "━━━━━━━━━━━━━━"]
    if user_id is not None:
        sections.append(build_now_dashboard(user_name, user_id, with_ai=True))
    else:
        sections.append(build_now_dashboard(user_name, 0, with_ai=True))
    
    # 加上有幫助的新聞
    sections.append("\n🗞️ 開盤焦點新聞：")
    macro_targets = ["標普500", "納斯達克"]
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(process_news_item_smart(t, news[0], user_name, user_id or 0))
    
    return "\n\n".join(sections)


def cmd_post_market_report(user_name: str = "User", user_id: int | None = None) -> str:
    sections = ["🏁 美股收盤結算匯報 (收盤後 30 分鐘)", "━━━━━━━━━━━━━━"]
    if user_id is not None:
        sections.append(cmd_list(user_id)[0]) # 分頁列表的第一頁文字
    else:
        sections.append(cmd_list(0)[0]) # 分頁列表的第一頁文字
    
    # 加上有幫助的新聞
    sections.append("\n🗞️ 今日市場關鍵總結：")
    macro_targets = ["標普500", "納斯達克"]
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(process_news_item_smart(t, news[0], user_name, user_id or 0))
            
    return "\n\n".join(sections)


def handle_natural_language(text: str, user_name: str, user_id: int | None = None) -> str:
    syms = STOCK_RE.findall(text or "")
    symbol = syms[0].upper() if syms else None
    
    if symbol:
        # 偵測到代號，自動切換為股票深度分析模式
        snapshot = market_api.get_stock_snapshot(symbol)
        model_pref = database.get_user_model_preference(user_id) if user_id is not None else None
        
        # 抓取最新新聞
        news = market_api.fetch_news_multi(symbol, limit=3)
        holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
        
        prompt = f"""
{user_name} 提到股票代號：{symbol}。
原文內容：{text}

請以「頂尖交易副官」人格，針對該標的進行自動化深度分析。
這是一份具備「最大算力」支持的報告。

分析應包含：
1. 市場快照：現價、漲跌幅、成交量狀態。
2. 技術面解讀：裸 K 結構、支撐壓力位、斐波那契回撤判斷 (0.382, 0.618, 1.618)。
3. 近期催化劑：根據提供的最新新聞與行情，點出關鍵利多/利空。
4. 持倉評估：若使用者已持股（成本：{holdings.get(symbol, {}).get('avg_cost', '未知')}），給出具體戰術建議。
5. 長中短期展望與觀察點。

絕對禁止斷句，請完整將細節講完。
"""
        return ai_core.ask_model(prompt, user_name, model=model_pref, user_id=user_id, temperature=0.35, max_output_tokens=3000)

    # 一般日常對話
    model_pref = database.get_user_model_preference(user_id) if user_id is not None else None
    return ai_core.chat_with_user(text, user_name, None, None, user_id=user_id, model=model_pref)
