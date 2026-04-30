"""command.py
所有 Telegram 指令與業務流程核心。
"""
from __future__ import annotations

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
            tactical = ai_core.get_market_tactical_comment("\n".join(q.get("symbol", "") + ": " + market_api.format_quote(q) for q in quotes), portfolio, user_name, user_id=user_id)
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


def cmd_ask(text: str, user_name: str, user_id: int) -> str:
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        return "🤖 用法：/ask [代號] [問題]\n例如：/ask NVDA 現在是否過熱？"
    symbol = parts[1].upper().strip()
    query = parts[2].strip()
    snapshot = market_api.get_stock_snapshot(symbol)
    news = market_api.fetch_news_multi(symbol, limit=3)
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    return "🤖 AI 深度戰術分析：" + symbol + "\n━━━━━━━━━━━━━━\n" + ai_core.ask_ai_investment_advice(
        symbol,
        query,
        snapshot,
        news,
        user_name,
        user_holdings=holdings,
        user_id=user_id,
    )


def cmd_news(text: str, user_name: str, user_id: int) -> list[str]:
    """取得最相關的一則新聞，並以自然對話方式提供最新判斷。"""
    watchlist = database.get_watchlist(user_id)
    holdings = database.get_aggregated_portfolio(user_id)

    parts = text.split()
    if len(parts) >= 2 and parts[1].lower() == "list":
        return [market_api.get_news_source_list()]

    raw_query = " ".join(parts[1:]).strip() if len(parts) >= 2 else ""
    if raw_query == "":
        raw_query = "S&P 500 OR Nasdaq"

    latest_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = raw_query
    note = ""
    if raw_query != "S&P 500 OR Nasdaq":
        target, note = resolve_news_target(raw_query)

    news_items = market_api.fetch_news_filtered(target, limit=1)
    if not news_items and target != raw_query:
        news_items = market_api.fetch_news_filtered(raw_query, limit=1)

    if not news_items and raw_query == "S&P 500 OR Nasdaq":
        fallback_query = "Federal Reserve OR Fed OR US economic data OR GDP OR CPI"
        news_items = market_api.fetch_news_filtered(fallback_query, limit=1)
        if news_items:
            target = fallback_query
            note = "未找到標普500或納斯達克新聞，改查聯準會與美國宏觀經濟數據。"

    if not news_items:
        return [
            f"📌 查詢：{raw_query}\n"
            f"目前找不到相關新聞。\n"
            f"最新時間：{latest_time}"
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
        snapshot = market_api.get_stock_snapshot(symbol)
        ai_prompt = (
            f"請以自然對話形式回答：這則新聞對 {symbol} 的最新影響為何？"
            "請用交易副官口吻說明風險、短中長期觀察，以及價格位置與策略。"
        )
        ai_answer = ai_core.ask_ai_investment_advice(
            symbol,
            ai_prompt,
            snapshot,
            [item],
            user_name,
            user_holdings=holdings,
            user_id=user_id,
        )
        header = f"📰 /news {symbol} 最新回饋"
        market_line = (
            f"現價：{snapshot.get('price', 'N/A')}，"
            f"漲跌：{snapshot.get('diff', 'N/A')}，"
            f"漲幅：{snapshot.get('pct', 'N/A')}%"
        )
    else:
        ai_prompt = (
            f"請以自然對話形式回答：這則新聞對於「{raw_query}」主題的最新市場影響為何？"
            "請用交易副官口吻說明風險、短中長期觀察、以及關鍵判斷。"
        )
        ai_answer = ai_core.summarize_news_with_format(
            "新聞觀點",
            title,
            item,
            user_name,
            watchlist=watchlist,
            user_holdings=holdings,
            user_id=user_id,
        )
        header = f"📰 /news {raw_query} 最新回饋"
        market_line = ""

    message = (
        f"{header}\n"
        f"讀取時間：{latest_time}\n"
        f"查詢目標：{target} {note}\n"
        f"━━━━━━━━━━━━━━\n"
        f"標題：{title}\n"
        f"來源：{source}\n"
        f"發佈時間：{published_text}\n"
        f"原文：{url}\n"
        f"{market_line}\n"
        f"━━━━━━━━━━━━━━\n"
        f"摘要：{outline}\n\n"
        f"AI 回應：\n{ai_answer}"
    )
    return [message]


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
    return frame.status_text(VERSION, brain.get_status_text(user_id), get_system_status(), ok)


def _build_comprehensive_news(user_name: str, user_id: int) -> str:
    """內部輔助：建立綜合新聞摘要。"""
    sections = ["📰 美股顧問綜合情報摘要", "━━━━━━━━━━━━━━"]

    watchlist = database.get_watchlist(user_id)
    holdings = database.get_aggregated_portfolio(user_id)
    macro_targets = ["標普500", "納斯達克", "黃金"]
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("宏觀指數", t, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))
            break

    holdings = database.get_aggregated_portfolio(user_id)
    portfolio = list(holdings.keys())
    if portfolio:
        p_sym = portfolio[0]
        news = market_api.fetch_news_filtered(p_sym, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("持股清單", p_sym, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))

    if watchlist:
        w_sym = watchlist[0]
        news = market_api.fetch_news_filtered(w_sym, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("觀察清單", w_sym, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))

    return "\n\n".join(sections)


def cmd_test(user_name: str = "Kevin", user_id: int | None = None) -> str:
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


def cmd_proactive_news(user_name: str = "Kevin", user_id: int | None = None) -> str:
    # 這裡由 main_bot 的循環邏輯決定發什麼，或者在這裡隨機挑選
    sections = ["⏰ 美股顧問自動情報推播", "━━━━━━━━━━━━━━"]

    # 宏觀 (20 分鐘循環在 main_bot 處理)
    macro_targets = ["標普500", "納斯達克", "黃金", "原油", "比特幣"]
    import random
    watchlist = database.get_watchlist(user_id) if user_id is not None else []
    m_t = random.choice(macro_targets)
    news = market_api.fetch_news_filtered(m_t, limit=1)
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    if news:
        sections.append(ai_core.summarize_news_with_format("宏觀指數", m_t, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))

    # 持股與觀察也隨機推一個
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    portfolio = list(holdings.keys())
    if portfolio:
        p_sym = random.choice(portfolio)
        news = market_api.fetch_news_filtered(p_sym, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("持股清單", p_sym, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))

    if watchlist:
        w_sym = random.choice(watchlist)
        news = market_api.fetch_news_filtered(w_sym, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("觀察清單", w_sym, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))

    if len(sections) <= 2:
        return "💡 自動推播：目前暫無最新新聞或名單為空。"

    return "\n\n".join(sections)


def cmd_pre_market_report(user_name: str = "Kevin", user_id: int | None = None) -> str:
    sections = ["🔔 美股開盤預備匯報 (開盤前 30 分鐘)", "━━━━━━━━━━━━━━"]
    if user_id is not None:
        sections.append(build_now_dashboard(user_name, user_id, with_ai=True))
    else:
        sections.append(build_now_dashboard(user_name, 0, with_ai=True))
    
    # 加上有幫助的新聞
    sections.append("\n🗞️ 開盤焦點新聞：")
    macro_targets = ["標普500", "納斯達克"]
    watchlist = database.get_watchlist(user_id) if user_id is not None else []
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("開盤前瞻", t, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))
    
    return "\n\n".join(sections)


def cmd_post_market_report(user_name: str = "Kevin", user_id: int | None = None) -> str:
    sections = ["🏁 美股收盤結算匯報 (收盤後 30 分鐘)", "━━━━━━━━━━━━━━"]
    if user_id is not None:
        sections.append(cmd_list(user_id)[0]) # 分頁列表的第一頁文字
    else:
        sections.append(cmd_list(0)[0]) # 分頁列表的第一頁文字
    
    # 加上有幫助的新聞
    sections.append("\n🗞️ 今日市場關鍵總結：")
    macro_targets = ["標普500", "納斯達克"]
    watchlist = database.get_watchlist(user_id) if user_id is not None else []
    holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}
    for t in macro_targets:
        news = market_api.fetch_news_filtered(t, limit=1)
        if news:
            sections.append(ai_core.summarize_news_with_format("收盤總結", t, news[0], user_name, watchlist, user_holdings=holdings, user_id=user_id))
            
    return "\n\n".join(sections)


def handle_natural_language(text: str, user_name: str, user_id: int | None = None) -> str:
    syms = STOCK_RE.findall(text or "")
    symbol = syms[0].upper() if syms else None
    snapshot = market_api.get_stock_snapshot(symbol) if symbol else None
    return ai_core.chat_with_kevin(text, user_name, symbol, snapshot, user_id=user_id)
