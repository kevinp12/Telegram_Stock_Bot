"""frame.py
所有 Telegram 顯示格式集中管理。
"""
from __future__ import annotations

import html
from typing import Any
from utils import safe_round


def escape_html(text: Any) -> str:
    return html.escape(str(text), quote=False)


def help_text() -> list[str]:
    part1 = (
        "🎯 美股顧問 指揮手冊 (1/2)\n"
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
        "💬 自然語言\n"
        "• 直接輸入 NVDA 今天怎麼看 - 自動偵測代號並分析"
    )
    part2 = (
        "🎯 美股顧問 指揮手冊 (2/2)\n"
        "━━━━━━━━━━━━━━\n"
        "🚀 報告與分析\n"
        "【新聞速報】\n"
        "• /news - 立即執行完整市場報告與新聞摘要\n"
        "• /news [代號|關鍵詞] - 獲取指定標的或主題的即時新聞分析\n"
        "• /news list - 顯示可搜尋的新聞來源與縮寫\n"
        "• /theme [主題] - 產生產業趨勢深度速報 (如: AI, 核能)\n\n"
        "【財務基本面】\n"
        "• /fin [代號] - 查詢個股財報、EPS、營收、估值與關鍵數字\n"
        "• /fin compare [股票A] [股票B] - 比較 2 到 3 支股票的財務健康與最新消息。\n\n"
        "【技術量化面】\n"
        "• /tech [代號] - 產出專業量化指標儀表板與戰術策略\n"
        "• /tech compare [代號1] [代號2] - 量化數據橫向對比\n\n"
        "【其他】\n"
        "• /ask [代號] [問題] - 啟動 Pro 深度戰術分析\n"
        "• /status - 驗證 Gemini 配額與連線"
    )
    return [part1, part2]


def tech_help_text() -> str:
    return (
        "📊 **量化指標儀表板指南 (/tech)**\n"
        "━━━━━━━━━━━━━━\n"
        "本功能結合多重趨勢系統與動能指標，為您提供專業級的量化分析報告。\n\n"
        "**指令用法：**\n"
        "• `/tech [股票代號]`：分析單一股票，例如 `/tech NVDA`。\n"
        "• `/tech [代號1] [代號2] [代號3]`：同時分析多隻股票 (上限 3 隻)。\n"
        "• `/tech compare [代號1] [代號2]`：橫向對比多隻股票的量化數據。\n\n"
        "**📊 指標深度解析：**\n"
        "1. **核心評級 (Attack Gauge)**：\n"
        "   - 綜合 EMA、MACD、RSI、VWAP 的多空力道。\n"
        "   - `大買`：強勢多頭；`觀察`：趨勢不明；`大賣`：強勢空頭。\n"
        "2. **主力籌碼 (Whale Tracking)**：\n"
        "   - 觀察成交量相對於 20 日均量的倍率。\n"
        "   - 爆量且收紅為主力建倉；爆量且收黑為大戶撤離。\n"
        "3. **趨勢結構 (EMA System)**：\n"
        "   - 使用 21/60/200 EMA 判斷。均線多頭排列 (21>60>200) 為最強趨勢。\n"
        "4. **VWAP (成交量加權平均價)**：\n"
        "   - 當日機構的平均持有成本。價在 VWAP 之上偏多，之下偏空。\n"
        "5. **ATR (真實波動幅度)**：\n"
        "   - 衡量股價波動劇烈程度，數值越高表示風險/波動越大，常用於設定停損。\n"
        "6. **斐波那契擴展 (Fibonacci Targets)**：\n"
        "   - 基於 3 個月高低點計算。1.0 與 1.618 為常見的獲利了結或強壓力位。\n"
        "7. **TD9 序列 (TD Sequential)**：\n"
        "   - 連續 9 根 K 線的價格衰竭偵測。TD9 出現通常預示短期趨勢可能反轉。\n\n"
        "💡 **實戰提示：**\n"
        "建議結合 `/fin` 財報數據與 `/news` 即時消息，達到量價與基本面共振的最高勝率。"
    )


def tech_report(data: dict[str, Any]) -> str:
    symbol = data.get("symbol", "N/A")
    price = data.get("last_price", 0)
    atr = data.get("atr", 0)
    vwap = data.get("vwap", 0)
    attack = data.get("attack_status", "觀察")
    whale = data.get("whale_status", "中立")
    vol_ratio = data.get("vol_ratio", 1.0)
    macd = data.get("macd_status", "N/A")
    rsi = data.get("rsi", "N/A")
    td = data.get("td_status", "N/A")
    ema = data.get("ema_status", "N/A")
    sup = data.get("support", "N/A")
    res = data.get("resistance", "N/A")
    target_1 = data.get("target_1", "N/A")
    target_1618 = data.get("target_1618", "N/A")
    
    # 動態圖示
    def get_status_icon(status: str) -> str:
        if "大買" in status: return "🔥"
        if "中買" in status or "小買" in status: return "✅"
        if "大賣" in status: return "💀"
        if "中賣" in status or "小賣" in status: return "⚠️"
        return "⚪"

    attack_icon = get_status_icon(attack)
    whale_icon = "🐋" if "買" in whale else ("🦈" if "賣" in whale else "⚪")
    
    # 策略總結生成
    strategy_title = "💡 戰術執行建議"
    strategy_body = "指標顯示趨勢不明，建議空手觀望，等待方向表態。"
    
    if "買" in attack:
        stop_loss_1 = safe_round(price - 1.5 * atr, 2)
        strategy_body = (
            f"進攻指標顯示 {attack}，且主力籌碼 {whale}。\n"
            f"🎯 **建倉位**：建議於 VWAP ({vwap}) 附近分批佈局。\n"
            f"🛡️ **防守位**：設於 {stop_loss_1} (現價 - 1.5 ATR)。"
        )
    elif "賣" in attack:
        strategy_body = (
            f"進攻指標顯示 {attack}，技術面顯著轉弱。\n"
            f"📉 **減碼位**：建議分批減碼或嚴格執行停損。\n"
            f"🔭 **觀察位**：防守觀察位設於 {vwap}。"
        )

    return (
        f"📊 **【量化作戰儀表板：{symbol}】**\n"
        f"━━━━━━━━━━━━━━\n"
        f"現價：`{price}`\n"
        f"⚔️ **核心評級**：{attack_icon} `{attack}`\n"
        f"🌊 **主力籌碼**：{whale_icon} `{whale}` (爆量 {vol_ratio}x)\n"
        f"🧬 **趨勢結構**：{ema}\n\n"
        f"📐 **關鍵點位參考**\n"
        f"• 錨定成本 (VWAP)：`{vwap}`\n"
        f"• 預估目標 (Fib 1.0) ：`{target_1}`\n"
        f"• 預估目標 (Fib 1.6) ：`{target_1618}`\n"
        f"• 建議停損參考 ：`{safe_round(price - 2*atr, 2)}` - `{safe_round(price - 1.5*atr, 2)}`\n"
        f"• 支撐 / 壓力位 ：`{sup}` / `{res}`\n\n"
        f"🌪️ **動能與背離**\n"
        f"• MACD 狀態：{macd}\n"
        f"• RSI 強弱 ：{rsi}\n"
        f"• TD9 序列 ：{td}\n\n"
        f"**{strategy_title}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"{strategy_body}"
    )


def tech_compare_report(data_list: list[dict[str, Any]]) -> str:
    sections = ["📊 **【多維度技術面對比】**\n━━━━━━━━━━━━━━"]
    
    for data in data_list:
        if "error" in data:
            sections.append(f"❌ {data.get('symbol', 'Unknown')}: 分析失敗")
            continue
            
        symbol = data['symbol']
        price = data['last_price']
        attack = data['attack_status']
        td = data['td_status']
        rsi = data['rsi']
        ema = "多頭" if "多頭" in data['ema_status'] else ("空頭" if "空頭" in data['ema_status'] else "盤整")
        
        sections.append(
            f"**{symbol}** (${price})\n"
            f"├ 評級: `{attack}` | 趨勢: `{ema}`\n"
            f"└ RSI: `{rsi}` | TD: `{td}`"
        )
    
    sections.append("\n💡 提示：輸入 `/tech [代號]` 查看詳細點位。")
    return "\n".join(sections)


def news_help_text() -> str:
    return (
        "📰 新聞功能指南\n"
        "━━━━━━━━━━━━━━\n"
        "提供即時市場新聞、個股相關新聞及 AI 深度解析。\n\n"
        "**指令用法：**\n"
        "• `/news`：預設查詢美股整體市場新聞，包含標普 500、納斯達克；若未找到同類新聞，會自動改查聯準會、經濟數據與美股宏觀動向。\n"
        "• `/news [股票代號]`：查詢指定股票的即時新聞，例如 `/news TSLA`。\n"
        "  會自動判斷股票代號，並回傳最新一則新聞、即時行情與自然對話式的 AI 交易回饋。\n"
        "• `/news [關鍵詞]`：搜尋特定主題新聞，例如 `/news AI 晶片`。\n"
        "  會回傳最相關一則新聞，並附上 AI 對該主題的市場分析與判斷。\n"
        "• `/news list`：查看所有可用的新聞來源清單。\n"
        "• `/news help` 或 `/news_help`：顯示本新聞功能指南。\n\n"
        "**新聞結果：**\n"
        "系統將直接發送最相關的一則新聞，附上原文網址、讀取時間、最新時間與完整 AI 回饋。\n"
        "若指定股票，會同時展示最新行情、支撐壓力與成本考量（若已持有）。\n"
        "已優化為單則精選回應，避免過長內容傳送不完全。\n\n"
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
    p_val = safe_round(price, 2)
    return f"✅ 已記錄買入\n{symbol.upper()} | {qty:g} 股 | 成本 ${p_val:.2f}"


def sell_success(symbol: str, price: float, qty: float, profit: float, rem: float) -> str:
    p_val = safe_round(profit, 2)
    pr_val = safe_round(price, 2)
    sign = "+" if p_val >= 0 else ""
    msg = f"✅ 已記錄賣出\n{symbol.upper()} | {qty - rem:g} 股 | 賣出 ${pr_val:.2f}\n已實現損益：{sign}${p_val:.2f} USD"
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
            market_value = safe_round(float(curr) * qty, 2)
            profit = safe_round((float(curr) - avg_cost) * qty, 2)
            pct = safe_round((profit / (avg_cost * qty) * 100), 2) if avg_cost * qty else 0.0
            sign = "+" if profit >= 0 else ""
            total_value += market_value
            total_profit += profit
            lines.append(
                f"{symbol} (${safe_round(float(curr), 2):.2f}) | {qty:g} 股 | 市值 ${market_value:,.2f}\n"
                f"成本：${safe_round(avg_cost, 2):.2f} | 獲利：{sign}${profit:,.2f} ({sign}{pct:.2f}%)\n"
            )
        else:
            lines.append(f"{symbol} | {qty:g} 股\n成本：${safe_round(avg_cost, 2):.2f} | 現價：N/A\n")
    
    total_profit = safe_round(total_profit, 2)
    realized_profit = safe_round(realized_profit, 2)
    sign_total = "+" if total_profit >= 0 else ""
    sign_realized = "+" if realized_profit >= 0 else ""
    lines.append("━━━━━━━━━━━━━━")
    if total_pages == 1 or page == total_pages:
        lines.append(f"未實現損益：{sign_total}${total_profit:,.2f} USD")
        lines.append(f"已實現損益：{sign_realized}${realized_profit:,.2f} USD")
    
    return "\n".join(lines)


def fin_report(data: dict[str, Any]) -> str:
    rev_growth = data.get("revenue_growth_qoq", "N/A")
    eps_growth = data.get("eps_growth_qoq", "N/A")
    
    growth_section = ""
    if rev_growth != "N/A" or eps_growth != "N/A":
        growth_section = f"📊 **季度增長 (QoQ)**\n• 營收增長：{rev_growth}\n• EPS 增長 ：{eps_growth}\n\n"

    return (
        f"📊 個股財報快照：{data.get('company_name', data.get('symbol', 'N/A'))}\n"
        "━━━━━━━━━━━━━━\n"
        f"代號：{data.get('symbol', 'N/A')}\n"
        f"現價：{data.get('current_price', 'N/A')}\n"
        f"產業：{data.get('sector', 'N/A')} / {data.get('industry', 'N/A')}\n"
        f"市值：{data.get('market_cap', 'N/A')}\n"
        f"TTM 營收：{data.get('revenue_ttm', 'N/A')}\n"
        f"TTM 淨利：{data.get('net_income', 'N/A')}\n"
        f"EPS (TTM)：{data.get('trailing_eps', 'N/A')}\n\n"
        f"{growth_section}"
        f"📐 **估值與範圍**\n"
        f"• 本益比 (TTM)：{data.get('trailing_pe', 'N/A')} / 預期：{data.get('forward_pe', 'N/A')}\n"
        f"• 毛利率：{data.get('gross_margin', 'N/A')} / 淨利率：{data.get('profit_margin', 'N/A')}\n"
        f"• 52 週：{data.get('year_low', 'N/A')} - {data.get('year_high', 'N/A')}\n"
        + (
            f"\n📅 **最新季報 ({data.get('latest_quarter')})**\n"
            f"• EPS：{data.get('latest_quarter_eps', 'N/A')}\n"
            f"• 營收：{data.get('latest_quarter_revenue', 'N/A')}"
            if data.get("latest_quarter")
            else ""
        )
    )


def news_help_text() -> str:
    return (
        "📰 新聞功能指南\n"
        "━━━━━━━━━━━━━━\n"
        "提供即時市場新聞、個股相關新聞及 AI 深度解析。\n\n"
        "**指令用法：**\n"
        "• `/news`：預設查詢美股整體市場新聞，包含標普 500、納斯達克；若未找到同類新聞，會自動改查聯準會、經濟數據與美股宏觀動向。\n"
        "• `/news [股票代號]`：查詢指定股票的即時新聞，例如 `/news TSLA`。\n"
        "  會自動判斷股票代號，並回傳最新一則新聞、即時行情與自然對話式的 AI 交易回饋。\n"
        "• `/news [關鍵詞]`：搜尋特定主題新聞，例如 `/news AI 晶片`。\n"
        "  會回傳最相關一則新聞，並附上 AI 對該主題的市場分析與判斷。\n"
        "• `/news list`：查看所有可用的新聞來源清單。\n"
        "• `/news help` 或 `/news_help`：顯示本新聞功能指南。\n\n"
        "**新聞結果：**\n"
        "系統將直接發送最相關的一則新聞，附上原文網址、讀取時間、最新時間與完整 AI 回饋。\n"
        "若指定股票，會同時展示最新行情、支撐壓力與成本考量（若已持有）。\n"
        "已優化為單則精選回應，避免過長內容傳送不完全。\n\n"
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
    p_val = safe_round(price, 2)
    return f"✅ 已記錄買入\n{symbol.upper()} | {qty:g} 股 | 成本 ${p_val:.2f}"


def sell_success(symbol: str, price: float, qty: float, profit: float, rem: float) -> str:
    p_val = safe_round(profit, 2)
    pr_val = safe_round(price, 2)
    sign = "+" if p_val >= 0 else ""
    msg = f"✅ 已記錄賣出\n{symbol.upper()} | {qty - rem:g} 股 | 賣出 ${pr_val:.2f}\n已實現損益：{sign}${p_val:.2f} USD"
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
            market_value = safe_round(float(curr) * qty, 2)
            profit = safe_round((float(curr) - avg_cost) * qty, 2)
            pct = safe_round((profit / (avg_cost * qty) * 100), 2) if avg_cost * qty else 0.0
            sign = "+" if profit >= 0 else ""
            total_value += market_value
            total_profit += profit
            lines.append(
                f"{symbol} | {qty:g} 股 | 市值 ${market_value:,.2f}\n"
                f"成本：${safe_round(avg_cost, 2):.2f} | 現價：${safe_round(float(curr), 2):.2f}\n"
                f"獲利：{sign}${profit:,.2f} ({sign}{pct:.2f}%)\n"
            )
        else:
            lines.append(f"{symbol} | {qty:g} 股\n成本：${safe_round(avg_cost, 2):.2f} | 現價：N/A\n")
    
    total_profit = safe_round(total_profit, 2)
    realized_profit = safe_round(realized_profit, 2)
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


def hidden_op_text(current_model: str) -> str:
    return (
        "🕵️ 隱藏功能指令集 (Hidden Features)\n"
        "━━━━━━━━━━━━━━\n"
        "這些指令專為進階玩家設計，不會出現在選單中。\n\n"
        f"• 當前 AI 核心：`{current_model}`\n\n"
        "📌 指令清單與說明：\n"
        "• `/op model flash` - 切換至 Gemini Flash\n"
        "  (反應極快，適合日常行情與簡單分析)\n\n"
        "• `/op model pro` - 切換至 Gemini Pro\n"
        "  (具備最強算力，適合深度戰術與複雜比較)\n\n"
        "• `/op log` - 查看系統運行實時日誌\n"
        "  (直接將伺服器最近 40 筆審計日誌傳送到此)\n\n"
        "• `/op quota` - 查詢今日 API 配額進度\n"
        "  (視覺化展示 Token 剩餘空間與使用比例)\n"
        "━━━━━━━━━━━━━━\n"
        "💡 提示：指令需完整輸入，例如 `/op model pro`。\n"
        "若只輸入 `/op model` 系統會給予詳細切換教學。"
    )


def quota_text(used: int, limit: int, percent: float) -> str:
    # 建立進度條
    bar_length = 10
    filled_length = int(bar_length * percent / 100)
    if filled_length > bar_length: filled_length = bar_length
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    
    return (
        "💎 Gemini 配額使用報告\n"
        "━━━━━━━━━━━━━━\n"
        f"今日已使用 Token：{used:,}\n"
        f"每日配額上限：{limit:,}\n"
        f"目前進度：{percent:.2f}%\n"
        f"使用狀態：[{bar}]\n\n"
        "💡 提示：配額於每日台灣時間上午 8 點（或 GCP 設定時間）重置。"
    )
