"""command.py
所有 Telegram 指令與業務流程核心。
"""

from __future__ import annotations

import logging
import math
import random
import re
from datetime import datetime, timedelta
from typing import Any

import psutil
import yfinance as yf

import ai_core
import brain
import database
import frame
import market_api
import tech_indicators
from config import ADMIN_ID, BOT_START_TIME, VERSION
from utils import safe_round

STOCK_RE = re.compile(r"\b[A-Z]{2,5}\b")
FIN_COMPARE_STATE: dict[int, list[str]] = {}
DATA_CLEAR_CONFIRM_STATE: dict[int, datetime] = {}

def _is_admin(user_id: int) -> bool:
    """僅允許 .env ADMIN_ID 使用後台隱藏功能。"""
    if not ADMIN_ID:
        return False
    try:
        return int(user_id) == int(ADMIN_ID)
    except Exception:
        return False


def _clip_text(text: str, limit: int = 700) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…（內容已截斷）"


def _format_admin_user(row: dict) -> str:
    uid = row.get("user_id", "")
    name = row.get("display_name") or "未命名"
    username = row.get("username") or ""
    username_part = f" (@{username})" if username else ""
    last_seen = row.get("last_seen") or "未知"
    return f"• `{uid}`｜{name}{username_part}\n  └ 最後互動：{last_seen}"


def _user_admin_help() -> str:
    return (
        "🔐 後台使用者查詢\n"
        "━━━━━━━━━━━━━━\n"
        "這是隱藏指令，不會出現在 /help 或 Telegram Menu。\n\n"
        "✅ 可用指令：\n"
        "• `/op user list`：顯示所有使用者 ID、名稱、最後互動時間\n"
        "• `/op user log 名稱or id`：查詢該使用者 48 小時內問過的問題與回答/指令紀錄\n\n"
        "📌 範例：\n"
        "• `/op user log 5788908737`\n"
        "• `/op user log Kevin`\n"
        "• `/op user log @username`"
    )


def cmd_user(text: str, user_id: int) -> str:
    """後台使用者查詢。僅 ADMIN_ID 可用，供 /op user 子指令呼叫。"""
    if not _is_admin(user_id):
        return "⛔ 權限不足：僅 ADMIN_ID 可使用 `/op user`。"

    try:
        parts = (text or "").split(maxsplit=3)
        normalized_parts = parts
        if parts and parts[0].lower() == "/op" and len(parts) >= 2 and parts[1].lower() == "user":
            normalized_parts = ["user", *parts[2:]]
        elif parts and parts[0].lower() == "/user":
            normalized_parts = ["user", *parts[1:]]

        if len(normalized_parts) < 2:
            return _user_admin_help()

        sub = normalized_parts[1].lower()
        if sub in {"help", "?", "教學", "說明"}:
            return _user_admin_help()

        if sub == "list":
            users = database.get_all_users()
            if not users:
                return "🔐 使用者清單\n━━━━━━━━━━━━━━\n目前沒有使用者紀錄。"
            lines = ["🔐 使用者清單", "━━━━━━━━━━━━━━", f"共 {len(users)} 位使用者\n"]
            lines.extend(_format_admin_user(row) for row in users[:80])
            if len(users) > 80:
                lines.append(f"\n…另有 {len(users) - 80} 位未顯示。請用 `/op user log 名稱or id` 查詢特定使用者。")
            return "\n".join(lines)

        if sub == "log":
            if len(normalized_parts) < 3 or not normalized_parts[2].strip():
                return (
                    "❌ 缺少查詢目標。\n"
                    "━━━━━━━━━━━━━━\n"
                    "用法：`/op user log 名稱or id`\n"
                    "範例：`/op user log 5788908737`、`/op user log Kevin`、`/op user log @username`"
                )
            identifier = normalized_parts[2].strip()
            target = database.find_user_by_name_or_id(identifier)
            if not target:
                return (
                    f"❌ 找不到使用者：`{identifier}`\n"
                    "━━━━━━━━━━━━━━\n"
                    "請先用 `/op user list` 查看目前已記錄的 ID 與名稱，再用 `/op user log 名稱or id` 查詢。"
                )

            logs = database.get_user_interaction_logs(int(target["user_id"]), limit=20)
            header = ["🔐 使用者問答紀錄", "━━━━━━━━━━━━━━", _format_admin_user(target)]
            if not logs:
                return "\n".join(header + ["\n目前沒有 48 小時內的暫存紀錄。", "\n💡 user.log 是暫存區：bot 重啟會清空，超過 48 小時也會刪除。"])

            body: list[str] = []
            for idx, row in enumerate(logs, start=1):
                answer = str(row.get("answer", "") or "").strip()
                answer_block = f"\nA：{_clip_text(answer, 900)}" if answer else ""
                body.append(
                    f"\n#{idx}｜{row.get('created_at', '')}｜{row.get('source', 'text')}\n"
                    f"Q：{_clip_text(str(row.get('question', '')), 500)}"
                    f"{answer_block}"
                )
            return "\n".join(header + body)

        return (
            f"❌ 未知的 /op user 子指令：`{sub}`\n"
            "━━━━━━━━━━━━━━\n"
            "可用：`/op user list`、`/op user log 名稱or id`\n\n"
            f"{_user_admin_help()}"
        )
    except Exception as exc:
        logging.exception("cmd_user failed")
        return (
            "⚠️ 後台查詢發生錯誤。\n"
            "━━━━━━━━━━━━━━\n"
            f"錯誤內容：`{exc}`\n\n"
            f"{_user_admin_help()}"
        )


def _portfolio_snapshot_from_ledger(ledger: list[dict]) -> dict[str, dict[str, float]]:
    portfolio: dict[str, dict[str, float]] = {}
    for row in ledger:
        symbol = str(row.get("symbol", "")).upper()
        price = float(row.get("buy_price", 0.0) or 0.0)
        qty = float(row.get("quantity", 0.0) or 0.0)
        if not symbol or qty <= 0:
            continue
        item = portfolio.setdefault(symbol, {"shares": 0.0, "total_cost": 0.0})
        item["shares"] += qty
        item["total_cost"] += price * qty
    return portfolio



def cmd_data_clear(text: str, user_id: int) -> str:
    """雙重確認刪除：第一次警告，60秒內再次輸入 data clear 才執行。"""
    normalized = " ".join((text or "").strip().split()).lower()
    if normalized not in {"data clear", "/data clear"}:
        return "🧹 資料清除說明\n" "━━━━━━━━━━━━━━\n" "請輸入：`data clear`\n" "⚠️ 需連續輸入兩次才會真的刪除。"

    now = datetime.now()
    prev = DATA_CLEAR_CONFIRM_STATE.get(user_id)
    if not prev or (now - prev).total_seconds() > 60:
        DATA_CLEAR_CONFIRM_STATE[user_id] = now
        return frame.data_clear_confirm_text()

    DATA_CLEAR_CONFIRM_STATE.pop(user_id, None)
    database.clear_user_all_data(user_id)
    return frame.data_clear_done_text()


def cmd_bc(text: str, user_id: int) -> str:
    parts = (text or "").split()
    active, timer, _ = database.get_bc_settings(user_id)

    if len(parts) == 1:
        return (
            "📘 /bc 指令教學\n"
            "━━━━━━━━━━━━━━\n"
            f"{frame.bc_settings_status(enabled=bool(active), interval=int(timer))}\n\n"
            "✅ 可用操作：\n"
            "• `/bc on`：開啟自動推播\n"
            "• `/bc off`：關閉自動推播\n"
            "• `/bc timer 120`：設定推播間隔（最少 30 分鐘）"
        )

    sub = parts[1].lower()
    if sub == "on":
        database.update_bc_settings(user_id, active=1)
        return "✅ 自動推播已開啟\n" "━━━━━━━━━━━━━━\n" f"{frame.bc_settings_status(enabled=True, interval=int(timer))}"
    if sub == "off":
        database.update_bc_settings(user_id, active=0)
        return "✅ 自動推播已關閉\n" "━━━━━━━━━━━━━━\n" f"{frame.bc_settings_status(enabled=False, interval=int(timer))}"
    if sub == "timer":
        if len(parts) < 3:
            return "❌ 缺少分鐘數\n" "━━━━━━━━━━━━━━\n" "⏱️ 正確用法：`/bc timer 120`\n" "ℹ️ 最少 30 分鐘，預設 120 分鐘。"
        try:
            mins = int(parts[2])
        except Exception:
            return "❌ 分鐘格式錯誤\n" "━━━━━━━━━━━━━━\n" "請輸入有效整數分鐘數，例如：`/bc timer 120`"
        if mins < 30:
            return "❌ 推播間隔最少 30 分鐘。請重新設定，例如：`/bc timer 60`"
        database.update_bc_settings(user_id, timer=mins)
        return f"✅ 推播間隔已更新為 {mins} 分鐘\n" "━━━━━━━━━━━━━━\n" f"{frame.bc_settings_status(enabled=bool(active), interval=mins)}"

    return (
        f"❌ 未知的 /bc 子指令：`{sub}`\n"
        "━━━━━━━━━━━━━━\n"
        "📘 可用指令：`/bc on`、`/bc off`、`/bc timer 120`\n\n"
        f"{frame.bc_settings_status(enabled=bool(active), interval=int(timer))}"
    )


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
    return {
        "total_cost": safe_round(total_cost, 2),
        "total_value": safe_round(total_value, 2),
        "pl_val": safe_round(pl_val, 2),
        "pl_pct": safe_round(pl_pct, 2),
    }



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


def _build_fin_compare_message(symbols: list[str], user_id: int) -> list[str] | str:
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

    report_sections: list[str] = [
        f"📊 **財報比較報告（1/3）：{' vs '.join(symbols)}**",
        "━━━━━━━━━━━━━━",
        "💡 本頁整理估值、營收、EPS、獲利率與近期財報重點。",
    ]
    for symbol in symbols:
        data = fundamentals_map[symbol]
        report_sections.append(
            f"\n🏢 **{symbol}｜{data.get('company_name', data.get('symbol', symbol))}**\n"
            f"├ 💵 現價：`{data.get('current_price', 'N/A')}`｜💎 市值：`{data.get('market_cap', 'N/A')}`\n"
            f"├ 📢 TTM 營收：`{data.get('revenue_ttm', 'N/A')}`｜💰 TTM 淨利：`{data.get('net_income', 'N/A')}`\n"
            f"├ 🧾 EPS：`{data.get('trailing_eps', 'N/A')}` / Forward `{data.get('forward_eps', 'N/A')}`\n"
            f"├ 📐 P/E：`{data.get('trailing_pe', 'N/A')}` / Forward `{data.get('forward_pe', 'N/A')}`\n"
            f"├ 🏭 毛利率：`{data.get('gross_margin', 'N/A')}`｜淨利率：`{data.get('profit_margin', 'N/A')}`\n"
            f"└ 📏 52 週區間：`{data.get('year_low', 'N/A')} - {data.get('year_high', 'N/A')}`\n"
            + (
                f"📅 最新季：`{data.get('latest_quarter')}`｜EPS：`{data.get('latest_quarter_eps', 'N/A')}`｜營收：`{data.get('latest_quarter_revenue', 'N/A')}`\n"
                if data.get("latest_quarter")
                else ""
            )
        )
        if symbol in holdings:
            position = holdings[symbol]
            report_sections.append(f"📦 持股：`{position.get('shares', 0):.2f}` 股｜成本：`${position.get('avg_cost', 0):.2f}`")

    news_sections: list[str] = [
        f"📰 **深度分析素材（3/3）：{' vs '.join(symbols)}**",
        "━━━━━━━━━━━━━━",
        "📌 最新消息與持股背景，用於輔助判斷催化劑與風險。",
    ]
    for symbol in symbols:
        news_sections.append(f"\n🧩 **{symbol} 最新消息**")
        if news_map[symbol]:
            news_lines = []
            for idx, item in enumerate(news_map[symbol], start=1):
                title = item.get("title", "無標題").strip()
                source = item.get("source", "未知")
                url = item.get("url", "")
                news_lines.append(f"{idx}. 🗞️ {title}（{source}）\n   🔗 {url}")
            news_sections.append("\n".join(news_lines))
        else:
            news_sections.append("⚪ 暫無可用新聞。")

    ai_analysis = ai_core.compare_financials(symbols, fundamentals_map, news_map, user_name, holdings, user_id=user_id)
    ai_page = "\n".join(
        [
            f"🤖 **AI 評析（2/3）：{' vs '.join(symbols)}**",
            "━━━━━━━━━━━━━━",
            "🧠 綜合估值、成長性、獲利品質、新聞催化與持股狀態：",
            ai_analysis,
        ]
    )
    return ["\n".join(report_sections), ai_page, "\n".join(news_sections)]


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
        return "📐 斐波那契回徹參考\n━━━━━━━━━━━━━━\nS&P500 斐波位置數據暫時無法取得。"

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

    return "\n".join(
        [
            "⚠️ 當前風險評估",
            "━━━━━━━━━━━━━━",
            *[f"• {note}" for note in signals],
        ]
    )


def _format_news_briefs(items: list[dict[str, str]], empty_text: str) -> str:
    if not items:
        return f"• {empty_text}"
    lines: list[str] = []
    for idx, item in enumerate(items[:3], start=1):
        title = (item.get("title") or "無標題").strip()
        source = item.get("source") or "未知來源"
        lines.append(f"{idx}. {title}（{source}）")
    return "\n".join(lines)


def cmd_risk(user_id: int | None = None, user_name: str = "User") -> str:
    """市場風險儀表板：VIX、指數風險、恐懼貪婪、選擇權與社群熱度。"""
    sp_quote = market_api.get_macro_quote("標普500")
    nasdaq_quote = market_api.get_macro_quote("納斯達克")
    vix_quote = market_api.get_macro_quote("VIX")
    fg = market_api.get_fear_greed_index()
    options_items = market_api.get_options_flow_snapshot(limit=3)
    social_items = market_api.get_social_heat_snapshot(limit=3)

    risk_notes: list[str] = []
    sp_pct = float(sp_quote.get("pct", 0) or 0)
    ndx_pct = float(nasdaq_quote.get("pct", 0) or 0)
    vix_price = vix_quote.get("price")
    vix_diff = float(vix_quote.get("diff", 0) or 0)
    if sp_pct < -1 or ndx_pct < -1:
        risk_notes.append("標普500或納斯達克跌幅超過 1%，短線風險升溫。")
    if isinstance(vix_price, (int, float)):
        if vix_price >= 25:
            risk_notes.append("VIX 高於 25，市場進入高波動/恐慌區，倉位宜保守。")
        elif vix_price >= 18:
            risk_notes.append("VIX 位於警戒區，留意避險需求升溫。")
        else:
            risk_notes.append("VIX 仍在相對溫和區，系統性恐慌尚未明顯擴散。")
        if vix_diff > 0:
            risk_notes.append("VIX 日內上升，代表避險情緒正在增強。")
    if fg.get("value") != "N/A":
        try:
            fg_val = float(fg.get("value"))
            if fg_val <= 25:
                risk_notes.append("Fear & Greed 偏恐懼，容易出現去槓桿但也可能接近情緒低點。")
            elif fg_val >= 75:
                risk_notes.append("Fear & Greed 偏貪婪，追高風險提高。")
        except Exception:
            pass
    if not risk_notes:
        risk_notes.append("目前風險訊號中性，仍需觀察指數與波動率是否同步轉弱。")

    return (
        "🛡️ 市場風險雷達 /risk\n"
        "━━━━━━━━━━━━━━\n"
        "📊 指數風險\n"
        f"• 標普500：{market_api.format_quote(sp_quote)}\n"
        f"• 納斯達克：{market_api.format_quote(nasdaq_quote)}\n"
        f"• VIX：{market_api.format_quote(vix_quote)}\n\n"
        "😨 恐懼與貪婪指數\n"
        f"• Fear & Greed：`{fg.get('value', 'N/A')}`｜{fg.get('rating', 'N/A')}（{fg.get('note', 'N/A')}）\n\n"
        "📈 期權選擇權異動（Options Flow 近似追蹤）\n"
        f"{_format_news_briefs(options_items, '暫無可用的大額 Call/Put 異動新聞。')}\n\n"
        "🔥 社交媒體熱度（Reddit WSB / X 近似追蹤）\n"
        f"{_format_news_briefs(social_items, '暫無可用的社群熱度暴增資料。')}\n\n"
        "⚠️ 風險判讀\n"
        + "\n".join(f"• {note}" for note in risk_notes)
    )


def _macro_trend_text(item: dict[str, Any], unit: str = "") -> str:
    value = item.get("value", "N/A")
    prev = item.get("prev", "N/A")
    trend = item.get("trend", "N/A")
    date = item.get("date", "N/A")
    suffix = unit if isinstance(value, (int, float)) else ""
    return f"{value}{suffix}｜前值 {prev}{suffix}｜{trend}｜{date}"


def cmd_marco(user_id: int | None = None, user_name: str = "User") -> list[str]:
    """宏觀指令：第1頁即時數據，第2頁指標教學與高低影響。"""
    snap = market_api.get_macro_core_snapshot()
    cpi = snap.get("cpi", {})
    unrate = snap.get("unrate", {})
    us10y = snap.get("us10y", {})
    dxy = snap.get("dxy", {})

    dxy_text = market_api.format_quote(dxy) if isinstance(dxy, dict) else "N/A"
    page1 = (
        "📊 宏觀雷達 /marco (1/2)\n"
        "━━━━━━━━━━━━━━\n"
        "A. 通膨類 (Inflation)\n"
        f"• CPI (CPIAUCSL)：{_macro_trend_text(cpi)}\n"
        "• PCE：本版未串接（可後續加上 PCEPI）\n\n"
        "B. 就業類 (Employment)\n"
        f"• 失業率 (UNRATE)：{_macro_trend_text(unrate, '%')}\n"
        "• NFP / 平均時薪：本版未串接（可加 BLS API）\n\n"
        "C. 利率與美元 (Rates & Dollar)\n"
        f"• US10Y (GS10)：{_macro_trend_text(us10y, '%')}\n"
        f"• DXY (DX-Y.NYB)：{dxy_text}\n\n"
        "💡 趨勢說明：上升/下降為相較前一期（通常前月）變化。"
    )

    page2 = (
        "📘 宏觀指標教學 /marco (2/2)\n"
        "━━━━━━━━━━━━━━\n"
        "【A. 通膨類】\n"
        "• CPI / Core CPI / PCE：越高代表通膨壓力大，市場會擔心降息延後。\n"
        "• 一般來說：通膨高於預期 → 美債殖利率與美元易走強 → 成長股壓力增加。\n\n"
        "【B. 就業類】\n"
        "• NFP、失業率、平均時薪是景氣與薪資通膨風向球。\n"
        "• 就業過熱且時薪過快上升，通膨較難降，風險資產估值容易被壓縮。\n\n"
        "【C. 利率與美元】\n"
        "• FOMC 利率：偏鷹通常壓估值；偏鴿通常支撐風險資產。\n"
        "• DXY：美元太強常壓抑股市表現。\n"
        "• US10Y：殖利率急升時，科技成長股（如 NVDA）通常壓力較大。\n\n"
        "⚠️ 常用判讀\n"
        "• CPI/PCE 高 + US10Y 升 + DXY 升：偏 Bearish\n"
        "• CPI/PCE 降 + US10Y 穩/降 + DXY 回落：偏 Bullish"
    )
    return [page1, page2]


def build_now_dashboard(user_name: str, user_id: int, with_ai: bool = True) -> list[str]:
    targets = ["標普500", "納斯達克", "黃金", "原油", "比特幣"]
    quotes = [market_api.get_macro_quote(t) for t in targets]
    portfolio = build_portfolio_summary(user_id)

    macro_section = build_macro_section(quotes)
    fib_section = build_fibonacci_section()

    tactical = "暫時無法產生 AI 戰術建議。"
    if with_ai:
        try:
            model_pref = database.get_user_model_preference(user_id)
            # /now 指令也嘗試套用 SMC 風格
            tactical = ai_core.ask_model(
                f"根據以下宏觀數據與損益狀況給出副官戰術點評：\n{macro_section}\n\n斐波位置：\n{fib_section}\n\n損益狀況：{portfolio}",
                user_name,
                model=model_pref,
                user_id=user_id,
                temperature=0.35,
                max_output_tokens=3000,
            )
        except Exception as exc:
            logging.warning("AI tactical failed: %s", exc)

    ai_section = "🤖 AI 交易副官結語\n━━━━━━━━━━━━━━\n" + tactical
    return [macro_section, fib_section, ai_section]


def cmd_now(user_id: int, user_name: str):
    return build_now_dashboard(user_name, user_id, with_ai=True)


def cmd_list(user_id: int, page: int = 1) -> tuple[str, int]:
    """獲取分頁後的持股列表。回傳 (文字內容, 總頁數)。"""
    portfolio = database.get_aggregated_portfolio(user_id)
    all_symbols = sorted(list(portfolio.keys()))

    # 獲取全域損益摘要（不論分頁，確保底部署名正確）
    summary = build_portfolio_summary(user_id)
    summary["realized_profit"] = database.get_realized_profit(user_id)

    total_items = len(all_symbols)
    page_size = 4
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_symbols = all_symbols[start_idx:end_idx]

    rows = []
    for symbol in page_symbols:
        item = portfolio[symbol]
        quote = market_api.get_macro_quote(symbol)
        rows.append(
            {
                "symbol": symbol,
                "quantity": item["shares"],
                "avg_cost": item["avg_cost"],
                "current_price": quote.get("price", "N/A"),
                "day_diff": quote.get("diff", 0.0),
                "day_pct": quote.get("pct", 0.0),
            }
        )

    text = frame.portfolio_list(rows, summary, page, total_pages)
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


def cmd_sweep(text: str, user_id: int) -> str:
    """處理 /sweep 指令。"""
    parts = text.split()
    if len(parts) < 2:
        return "📘 /sweep 指令教學\n" "━━━━━━━━━━━━━━\n" f"{frame.sweep_guide()}"

    action = parts[1].lower()

    if action == "list":
        return "📋 /sweep 監控清單\n" "━━━━━━━━━━━━━━\n" f"{frame.sweep_list(database.get_sniper_list(user_id))}"

    if action == "clear":
        database.clear_sniper_list(user_id)
        return "✅ 狙擊監控清單已全數清空。\n" "💡 你可以使用 `/sweep add NVDA` 重新建立監控。"

    if action in {"add", "del"}:
        if len(parts) < 3:
            return f"❌ 請提供標的代號。例如：`/sweep {action} NVDA`"

        symbols = [p.upper() for p in parts[2:] if p.strip()]
        symbols = [s for s in symbols if re.fullmatch(r"[A-Z0-9\.\-]{1,6}", s)]
        if not symbols:
            return "❌ 請提供有效的標的代號。\n" "可用格式：`/sweep add NVDA TSLA`"

        for s in symbols:
            if action == "add":
                database.add_sniper(user_id, s)
            else:
                database.del_sniper(user_id, s)

        action_name = "新增" if action == "add" else "移除"
        return f"✅ 狙擊監控已{action_name}：{', '.join(symbols)}\n" "💡 可用 `/sweep list` 查看當前監控清單。"

    return f"❌ 未知的子指令：`{action}`\n\n" f"{frame.sweep_guide()}"


def cmd_ask(text: str, user_name: str, user_id: int) -> list[str] | str:
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        return "🤖 用法：/ask [代號] [問題]\n例如：/ask NVDA 現在是否過熱？"
    symbol = parts[1].upper().strip()
    query = parts[2].strip()

    # 使用完整的量化分析作為快照
    snapshot = tech_indicators.calculate_indicators(symbol)
    if "error" in snapshot:
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
        f"當前價位：{snapshot.get('last_price', snapshot.get('price', 'N/A'))}\n"
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

    # 1. 嘗試高品質過濾搜尋 (NewsAPI + Domains)
    news_items = market_api.fetch_news_filtered(target, limit=1)

    # 2. 如果沒結果，且有擴展過搜尋詞，嘗試原始輸入的過濾搜尋
    if not news_items and target != raw_query:
        news_items = market_api.fetch_news_filtered(raw_query, limit=1)

    # 3. 如果還是沒結果，走最後底線：強制直接抓取 Yahoo Finance 個股新聞 (不經過 NewsAPI 與過濾)
    if not news_items and _is_stock_symbol(raw_query):
        try:
            symbol = raw_query.strip().upper()
            news_items = market_api.fetch_news_multi(symbol, limit=1)
            if news_items:
                note = "NewsAPI 暫無結果，已由 Yahoo Finance 取得即時消息。"
        except Exception:
            pass

    # 4. 宏觀兜底
    if not news_items:
        fallback_query = "Federal Reserve OR Fed OR US economic data"
        news_items = market_api.fetch_news_filtered(fallback_query, limit=1)
        if news_items:
            target = fallback_query
            note = "未找到原始目標新聞，改查聯準會與美國宏觀經濟數據。"

    if not news_items:
        return [f"📌 查詢：{raw_query}\n" f"目前找不到相關新聞，可能是該標的近期無重大消息。\n" f"🕒 讀取時間：{current_time_str}"]

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
        market_line = f"現價：{snapshot.get('price', 'N/A')}，" f"漲跌：{snapshot.get('diff', 'N/A')}，" f"漲幅：{snapshot.get('pct', 'N/A')}%"
    else:
        ai_prompt = (
            f"請以副官身分針對此新聞主題「{raw_query}」進行 SMC 結構影響分析。"
            "使用者要求：輸出精煉且具備戰術價值的內容，細節要講清楚，嚴格遵守副官人格與標籤規範。"
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

    page1 = (
        f"📰 **{header}** (1/2)\n"
        f"━━━━━━━━━━━━━━\n"
        f"🗞️ **{title}**\n"
        f"📅 {published_text} | 🏢 {source}\n\n"
        f"📝 **摘要：**\n{outline}\n\n"
        f"🎯 **目標：** {target} {note}\n"
        f"🕒 **更新：** {current_time_str}\n" + (f"\n📈 **市場快照：**\n{market_line}" if market_line else "") + f"\n\n🔗 [點擊閱讀原文]({url})"
    )

    page2 = f"🤖 **AI 深度分析與戰術決策** (2/2)\n" f"━━━━━━━━━━━━━━\n" f"{ai_answer}"

    return [page1, page2]


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
    theme_news = [n for n in rss_news if matched_key.lower() in n["title"].lower() or matched_key.lower() in n["description"].lower()]

    # 如果 RSS 沒抓到，改抓 NewsAPI
    if len(theme_news) < 2:
        api_news = market_api.fetch_news_filtered(query, limit=5)
        theme_news.extend(api_news)

    if not theme_news:
        return f"⚠️ 目前找不到關於【{matched_key}】的最新市場情報。"

    news_text = "\n".join([f"- {n['title']}: {n['description']}" for n in theme_news[:3]])
    prompt = f"""
請根據以下最新新聞，為 {user_name} 撰寫一份【{matched_key} 產業趨勢速報】。
你必須套用副官人格，並評估該趨勢對 SMC 大級別結構的潛在影響。

要求：
1. 評估該產業目前的總體情緒（1-10分）。
2. 分析技術突破對產業護城河的影響。
3. 輸出必須完整，細節講透徹，絕對禁止斷句。

新聞素材：
{news_text}
"""

    model_pref = database.get_user_model_preference(user_id)
    report = ai_core.ask_model(prompt, user_name, model=model_pref, user_id=user_id, temperature=0.4, max_output_tokens=2500)

    return f"🚀 【{matched_key} 未來趨勢速報】\n━━━━━━━━━━━━━━\n{report}"


def cmd_news_help() -> str:
    return frame.news_help_text()


def cmd_whale(text: str, user_id: int) -> str:
    """處理 /whale 指令：大鯨魚/內部人情報追蹤。"""
    parts = text.split()
    if len(parts) < 2:
        return "🐋 **「大鯨魚/內部人」情報追蹤**\n━━━━━━━━━━━━━━\n用法：`/whale [股票代號]`\n範例：`/whale NVDA`\n\n內容包含：\n• SEC Form 4：追蹤公司內部人 (CEO/CFO 等) 買賣動態\n• 13F 報告：大機構 (橋水、文藝復興等) 持倉變動\n• AI 判斷：結合量價與籌碼的「真情報」判定"

    symbol = parts[1].strip().upper()
    if not re.fullmatch(r"[A-Z0-9\.\-]{1,6}", symbol):
        return f"❌ 錯誤的代號格式：{symbol}。請輸入正確的美股代號。"

    # 獲取內線與機構數據
    insider_data = market_api.fetch_insider_transactions(symbol)
    institutional_data = market_api.fetch_institutional_ownership(symbol)

    user_name = database.get_user_display_name(user_id)
    model_pref = database.get_user_model_preference(user_id)

    def _build_whale_focus_summary(insiders: list[dict[str, Any]], insts: list[dict[str, Any]]) -> str:
        insider_buy = 0
        insider_sell = 0
        for item in insiders[:20]:
            chg = float(item.get("change", 0) or 0)
            if chg > 0:
                insider_buy += 1
            elif chg < 0:
                insider_sell += 1

        inst_add = 0
        inst_reduce = 0
        for item in insts[:20]:
            chg = float(item.get("change", 0) or 0)
            if chg > 0:
                inst_add += 1
            elif chg < 0:
                inst_reduce += 1

        insider_bias = "偏多" if insider_buy > insider_sell else "偏空" if insider_sell > insider_buy else "中性"
        inst_bias = "偏多" if inst_add > inst_reduce else "偏空" if inst_reduce > inst_add else "中性"

        return (
            "🎯 **大戶與內部人重點（系統摘要）**\n"
            f"• 內部人方向：{insider_bias}（買入 {insider_buy} / 賣出 {insider_sell}）\n"
            f"• 機構方向：{inst_bias}（加倉 {inst_add} / 減倉 {inst_reduce}）\n"
            "• 註：以上為最近資料筆數統計，AI 解讀需以名單細節為準。"
        )

    # AI 分析
    ai_analysis = ai_core.analyze_whale_insider(
        symbol, insider_data, institutional_data, user_name, model=model_pref, user_id=user_id
    )
    summary_text = _build_whale_focus_summary(insider_data, institutional_data)

    return frame.whale_report(symbol, len(insider_data), len(institutional_data), ai_analysis, summary_text=summary_text)


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
            return f"📊 已暫存 {combined[0]}，請再輸入第二支代碼，或使用 /fin compare [第二支代號] 進行比較。"

        if len(combined) > 3:
            FIN_COMPARE_STATE[user_id] = combined[:3]
            combined = combined[:3]
            return f"📊 比較最多支援 3 支股票，目前已取前三支：{', '.join(combined)}。\n" f"請重新使用 /fin compare {' '.join(combined)} 進行比較。"

        FIN_COMPARE_STATE.pop(user_id, None)
        return _build_fin_compare_message(combined, user_id)

    symbol = parts[1].strip().upper()
    fundamentals = market_api.get_stock_fundamentals(symbol)
    if not fundamentals:
        return f"❌ 無法取得 {symbol} 的財務資料，請確認代號是否正確。"
    base_report = frame.fin_report(fundamentals)
    user_name = database.get_user_display_name(user_id)
    model_pref = database.get_user_model_preference(user_id)
    fin_news = market_api.fetch_news_multi(symbol, limit=2)
    ai_fin = ai_core.analyze_financial_snapshot(
        symbol,
        fundamentals,
        fin_news,
        user_name,
        user_id=user_id,
        model=model_pref,
    )
    return f"{base_report}\n\n🧠 **AI 財報重點解讀**\n━━━━━━━━━━━━━━\n{ai_fin}"


def cmd_status(user_id: int) -> list[str]:
    try:
        ok = brain.ping(user_id)
    except Exception:
        ok = False

    # 429/配額耗盡不等於核心斷線：改為「連線正常但資源受限」
    last_error = str(getattr(brain.stats, "last_error", "") or "")
    quota_limited = brain.is_quota_exhausted_error(last_error)
    if (not ok) and quota_limited:
        ok = True

    brain_status = brain.get_status_text(user_id)
    if quota_limited:
        brain_status += "\n\n• ⚠️ 狀態補充：目前為 API 配額受限（429），核心可用但暫時無法生成新回覆。"

    model_pref = database.get_user_model_preference(user_id)
    bc_active, bc_timer, _ = database.get_bc_settings(user_id)
    sweep_count = len(database.get_sniper_list(user_id))
    watch_count = len(database.get_watchlist(user_id))
    brain_status = (
        f"{brain_status}\n\n"
        f"• 🤖 模型偏好：`{model_pref}`\n"
        f"  (⚡ Flash: 快速問答 | 🧠 Pro: 深度推理)\n\n"
        f"• 📢 自動推播：{'✅ 開啟' if bc_active else '❌ 關閉'} (每 {bc_timer} 分)\n"
        f"• 👀 雷達監控數：`{watch_count}`\n"
        f"• 🎯 狙擊監控數：`{sweep_count}`\n\n"
        f"💡 提示：使用 `/op model pro` 切換模型，使用 `/bc on` 開啟推播。"
    )
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
    """處理隱藏指令 /op。"""
    logging.info(f"cmd_op called: text='{text}', user_id={user_id}")

    if not _is_admin(user_id):
        return "⛔ 權限不足：僅 ADMIN_ID 可使用 `/op` 隱藏指令。"

    parts = text.split()
    current_model = database.get_user_model_preference(user_id)

    if len(parts) == 1:
        return frame.hidden_op_text(current_model)

    sub = parts[1].lower()
    if sub == "help":
        return frame.hidden_op_text(current_model)

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
        if len(parts) > 2 and parts[2].lower() == "clear":
            try:
                import os

                from config import GEMINI_AUDIT_LOG_PATH

                if os.path.exists(GEMINI_AUDIT_LOG_PATH):
                    os.remove(GEMINI_AUDIT_LOG_PATH)
                    return "🧹 系統審計日誌已成功清除。"
                return "ℹ️ 系統日誌檔案不存在。"
            except Exception as e:
                return f"❌ 清除日誌失敗：{e}"
        return "__TRIGGER_LOG__"

    if sub == "user":
        return cmd_user(text, user_id)

    return f"❓ 未知的隱藏指令：`{sub}`\n\n" f"請使用 `/op help` 查看完整的隱藏功能清單。"


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


def cmd_tech(text: str, user_id: int) -> str:
    """處理 /tech 指令，產出專業量化指標儀表板或對比報告。"""
    parts = text.split()
    if len(parts) < 2:
        return frame.tech_help_text()

    # 子指令判斷
    subcmd = parts[1].upper()

    if subcmd == "HELP":
        return frame.tech_help_text()

    if subcmd == "COMPARE":
        symbols = [s.strip().upper() for s in parts[2:5]]  # 上限 3 隻
        if not symbols:
            return "❌ 請輸入要比較的股票代號，例如：`/tech compare AAPL NVDA`"

        data_list = []
        for sym in symbols:
            data = tech_indicators.calculate_indicators(sym)
            data_list.append(data)

        # AI 戰術分析整合
        user_name = database.get_user_display_name(user_id)
        report = frame.tech_compare_report(data_list)
        ai_insight = ai_core.analyze_tech_comparison(data_list, user_name, user_id=user_id)

        return f"{report}\n\n🤖 AI 戰術評析：\n{ai_insight}"

    # 處理批量查詢 (最多 3 隻)
    symbols = [s.strip().upper() for s in parts[1:4]]

    # 如果只有一隻，走詳細報告
    if len(symbols) == 1:
        symbol = symbols[0]
        if not re.fullmatch(r"[A-Z0-9\.\-]{1,6}", symbol):
            return f"❌ 錯誤的代號格式：{symbol}。請輸入正確的美股代號。"

        data = tech_indicators.calculate_indicators(symbol)
        if "error" in data:
            return f"❌ 分析失敗 ({symbol})：{data['error']}\n請檢查代號是否正確或稍後再試。"

        return frame.tech_report(data)

    # 如果有多隻，收集所有分頁並回傳 list
    reports = []
    for sym in symbols:
        data = tech_indicators.calculate_indicators(sym)
        if "error" in data:
            reports.append(f"❌ 分析失敗 ({sym})：{data['error']}")
        else:
            reports.extend(frame.tech_report(data))

    return reports


def cmd_help() -> list[str]:
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
        sections.append(cmd_list(user_id)[0])  # 分頁列表的第一頁文字
    else:
        sections.append(cmd_list(0)[0])  # 分頁列表的第一頁文字

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
        # 偵測關鍵字，決定是否切換到 /whale 模式
        whale_keywords = ["大鯨魚", "內部人", "內線", "13F", "whale", "insider", "機構持倉", "CEO買", "CEO賣"]
        if any(kw in text.lower() for kw in whale_keywords):
            return cmd_whale(f"/whale {symbol}", user_id)

        # 偵測到代號，自動切換為股票深度分析模式
        # 使用量化分析作為快照
        snapshot = tech_indicators.calculate_indicators(symbol)
        if "error" in snapshot:
            snapshot = market_api.get_stock_snapshot(symbol)

        model_pref = database.get_user_model_preference(user_id) if user_id is not None else None

        # 抓取最新新聞
        news = market_api.fetch_news_multi(symbol, limit=3)
        holdings = database.get_aggregated_portfolio(user_id) if user_id is not None else {}

        # 自然對話採「初步分析模式」：短、準、先給方向
        return ai_core.ask_stock_brief(
            symbol,
            text,
            snapshot,
            news,
            user_name,
            user_id=user_id,
            model=model_pref,
        )

    # 一般日常對話
    model_pref = database.get_user_model_preference(user_id) if user_id is not None else None
    return ai_core.chat_with_user(text, user_name, None, None, user_id=user_id, model=model_pref)
