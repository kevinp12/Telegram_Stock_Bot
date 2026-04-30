"""frame.py
所有 Telegram 顯示格式集中管理。
"""
from __future__ import annotations

import html
from typing import Any


def escape_html(text: Any) -> str:
    return html.escape(str(text), quote=False)


def help_text() -> str:
    return (
        "🎯 美股顧問 指揮手冊\n"
        "━━━━━━━━━━━━━━\n"
        "⚡ 行情與損益\n"
        "• /now - 宏觀數據、帳戶總盈虧、AI 戰術短評\n\n"
        "📋 資產明細\n"
        "• /list - 詳細股數、平均成本與獲利\n"
        "• /buy [代號] [價格] [股數] - 記錄買入\n"
        "• /sell [代號] [價格] [股數] - 記錄賣出\n\n"
        "👀 雷達監控\n"
        "• /watch add NVDA TSLA - 批量新增標的\n"
        "• /watch del AAPL - 批量移除標的\n"
        "• /watch list - 查看當前名單\n"
        "• /watch clear - 清空雷達名單\n\n"
        "🚀 報告與分析\n"
        "• /news - 立即執行完整市場報告與新聞摘要\n"
        "• /news list - 顯示可搜尋的新聞來源與縮寫\n"
        "• /news [代號|關鍵詞] - 獲取指定標的或主題的即時新聞分析\n"
        "• /fin [代號] - 查詢個股財報、EPS、營收、估值與關鍵數字\n"
        "• /fin compare [代號1] [代號2] - 比較 2 到 3 支股票的財務健康與最新消息。\n"
        "• /ask [代號] [問題] - 啟動 Pro 深度戰術分析\n"
        "• /status - 驗證 Gemini 配額與連線\n\n"
        "💬 自然語言\n"
        "• 直接輸入 NVDA 今天怎麼看 - 自動偵測代號並分析\n"
    )


def news_help_text() -> str:
    return (
        "📰 新聞功能指南\n"
        "━━━━━━━━━━━━━━\n"
        "提供即時市場新聞、個股相關新聞及 AI 深度解析。\n\n"
        "**指令用法：**\n"
        "• `/news`：預設查詢美股整體市場新聞，包含標普 500、納斯達克；若未找到同類新聞，會自動改查聯準會、經濟數據與美股宏觀動向。\n"
        "• `/news [股票代號]`：查詢指定股票的即時新聞，例如 `/news TSLA`。\n"
        "• `/news [關鍵詞]`：搜尋特定主題新聞，例如 `/news AI 晶片`。\n"
        "• `/news list`：查看所有可用的新聞來源清單。\n"
        "• `/news help` 或 `/news_help`：顯示本新聞功能指南。\n\n"
        "**新聞結果：**\n"
        "系統將直接發送三條相關新聞，每條新聞都附上原文網址與完整 AI 觀點。\n"
        "不再使用新聞目錄與按鈕，直接送出完整結果。\n\n"
        "**AI 深度解析：**\n"
        "每篇新聞的詳情頁面都將包含 AI 總結的\n**重要程度評級**、**新聞大綱**、**內文整理**、**專業觀點**以及**可能影響標的**，幫助您快速掌握核心資訊。\n\n"
        "⚠️ 如果看不到新聞，請先確認 `NEWS_API_KEY` 是否已正確設定，系統會使用 NewsAPI 與 Yahoo Finance 兩種來源備援抓取。\n\n"
        "📊 祝您投資順利！"
    )


def menu_registered_text() -> str:
    return "✅ Telegram Menu 指令已註冊完成"


def status_text(version: str, brain_status: str, system_status: str, ping_ok: bool) -> str:
    icon = "🟢" if ping_ok else "🔴"
    return (
        f"🔍 顧問系統狀態報告 ({version})\n"
        "━━━━━━━━━━━━━━\n"
        f"核心連線：{icon} {'運行中' if ping_ok else '連線異常'}\n\n"
        "📊 伺服器資源：\n"
        f"{system_status}\n\n"
        "🧠 AI 模型與配額：\n"
        f"{brain_status}"
    )


def watch_guide() -> str:
    return (
        "👀 雷達管理教學\n"
        "━━━━━━━━━━━━━━\n"
        "✅ 批量新增：/watch add TSLA NVDA\n"
        "❌ 批量移除：/watch del AAPL\n"
        "📋 查看清單：/watch list\n"
        "🧹 清空清單：/watch clear"
    )


def watch_list(symbols: list[str]) -> str:
    if not symbols:
        return "👀 雷達清單：空"
    return "👀 雷達清單：\n" + ", ".join(symbols)


def buy_success(symbol: str, price: float, qty: float) -> str:
    return f"✅ 已記錄買入\n{symbol.upper()} | {qty:g} 股 | 成本 ${price:.2f}"


def sell_success(symbol: str, price: float, qty: float, profit: float, rem: float) -> str:
    sign = "+" if profit >= 0 else ""
    msg = f"✅ 已記錄賣出\n{symbol.upper()} | {qty - rem:g} 股 | 賣出 ${price:.2f}\n已實現損益：{sign}${profit:.2f} USD"
    if rem > 0:
        msg += f"\n⚠️ 庫存不足，尚有 {rem:g} 股未能賣出。"
    return msg


def portfolio_list(rows: list[dict[str, Any]], realized_profit: float = 0.0, page: int = 1, total_pages: int = 1) -> str:
    if not rows:
        return "目前無庫存資料。"
    
    lines = [f"📋 持股詳細明細 (第 {page}/{total_pages} 頁)", "━━━━━━━━━━━━━━"]
    total_value = 0.0
    total_profit = 0.0
    
    # 注意：這裡傳入的 rows 應該是已經分頁過的
    for r in rows:
        symbol = r["symbol"]
        qty = float(r["quantity"])
        avg_cost = float(r["avg_cost"])
        curr = r.get("current_price", "N/A")
        if isinstance(curr, (int, float)):
            market_value = float(curr) * qty
            profit = (float(curr) - avg_cost) * qty
            pct = (profit / (avg_cost * qty) * 100) if avg_cost * qty else 0.0
            sign = "+" if profit >= 0 else ""
            total_value += market_value
            total_profit += profit
            lines.append(
                f"{symbol} | {qty:g} 股 | 市值 ${market_value:,.2f}\n"
                f"成本：${avg_cost:.2f} | 現價：${float(curr):.2f}\n"
                f"獲利：{sign}${profit:,.2f} ({sign}{pct:.2f}%)\n"
            )
        else:
            lines.append(f"{symbol} | {qty:g} 股\n成本：${avg_cost:.2f} | 現價：N/A\n")
    
    sign_total = "+" if total_profit >= 0 else ""
    sign_realized = "+" if realized_profit >= 0 else ""
    lines.append("━━━━━━━━━━━━━━")
    if total_pages == 1 or page == total_pages:
        lines.append(f"未實現損益：{sign_total}${total_profit:,.2f} USD")
        lines.append(f"已實現損益：{sign_realized}${realized_profit:,.2f} USD")
    
    return "\n".join(lines)


def fin_report(data: dict[str, Any]) -> str:
    return (
        f"📊 個股財報快照：{data.get('company_name', data.get('symbol', 'N/A'))}\n"
        "━━━━━━━━━━━━━━\n"
        f"代號：{data.get('symbol', 'N/A')}\n"
        f"產業：{data.get('sector', 'N/A')} / {data.get('industry', 'N/A')}\n"
        f"國家：{data.get('country', 'N/A')}\n"
        f"現價：{data.get('current_price', 'N/A')}\n"
        f"市值：{data.get('market_cap', 'N/A')}\n"
        f"TTM 營收：{data.get('revenue_ttm', 'N/A')}\n"
        f"TTM 淨利：{data.get('net_income', 'N/A')}\n"
        f"EPS (TTM)：{data.get('trailing_eps', 'N/A')}\n"
        f"EPS (預期)：{data.get('forward_eps', 'N/A')}\n"
        f"本益比 (TTM)：{data.get('trailing_pe', 'N/A')} / 預期：{data.get('forward_pe', 'N/A')}\n"
        f"毛利率：{data.get('gross_margin', 'N/A')} / 淨利率：{data.get('profit_margin', 'N/A')}\n"
        f"52 週：{data.get('year_low', 'N/A')} - {data.get('year_high', 'N/A')}\n"
        + (
            f"最新季：{data.get('latest_quarter')}，EPS：{data.get('latest_quarter_eps', 'N/A')}，營收：{data.get('latest_quarter_revenue', 'N/A')}"
            if data.get("latest_quarter")
            else ""
        )
    )


def news_list_page(news_items: list[str], page: int, total_pages: int) -> str:
    sections = [f"📰 美股顧問情報摘要 (第 {page}/{total_pages} 頁)", "━━━━━━━━━━━━━━"]
    sections.extend(news_items)
    return "\n\n".join(sections)


def now_dashboard(macro_lines: list[str], pl_pct: float, pl_val: float, tactical: str) -> str:
    sign = "+" if pl_val >= 0 else ""
    return (
        "🌍 市場即時全景\n"
        "━━━━━━━━━━━━━━\n"
        + "\n".join(macro_lines)
        + "\n\n"
        + f"💰 帳戶總損益: {sign}{pl_pct:.2f}% ({sign}${pl_val:,.2f} USD)\n\n"
        + "🤖 AI 顧問戰術評語\n"
        + f"> {tactical}"
    )
