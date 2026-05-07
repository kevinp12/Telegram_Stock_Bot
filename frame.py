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
        "🎯 **美股顧問 指揮手冊 (1/2)**\n"
        "━━━━━━━━━━━━━━\n"
        "⚡ **行情與損益**\n"
        "• /now - 宏觀數據、帳戶總盈虧、AI 戰術短評\n\n"
        "• /total - 總資產損益（含 7d/1mo/6mo/ytd/1y/max）\n\n"
        "📋 **資產明細**\n"
        "• /list - 詳細股數、平均成本與獲利\n"
        "• /buy [代號] [價格] [股數] - 記錄買入\n"
        "• /sell [代號] [價格] [股數] - 記錄賣出\n\n"
        "👀 **雷達監控**\n"
        "• /watch add NVDA TSLA - 批量新增標的\n"
        "• /watch del AAPL - 批量移除標的\n"
        "• /watch list - 查看當前名單\n"
        "• /watch clear - 清空雷達名單\n"
        "• data clear - 雙重確認後清除你的資產資料\n\n"
        "💬 **自然語言**\n"
        "• 直接輸入 `NVDA 今天怎麼看` - 自動偵測代號並分析"
    )
    part2 = (
        "🎯 **美股顧問 指揮手冊 (2/2)**\n"
        "━━━━━━━━━━━━━━\n"
        "🚀 **報告與分析**\n"
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
        "【狙擊監控】\n"
        "• /sweep add NVDA - 啟動價格掃蕩與 FVG 監控\n"
        "• /sweep del TSLA - 停止監控該標的\n"
        "• /sweep list - 查看當前監控清單\n\n"
        "【其他】\n"
        "• /ask [代號] [問題] - 啟動 Pro 深度戰術分析\n"
        "• /bc on|off|timer - 個人化自動推播設定\n"
        "• /status - 驗證 Gemini 配額與連線"
    )
    return [part1, part2]


def tech_help_text() -> list[str]:
    part1 = (
        "📊 **量化指標儀表板指南（1/2）：指令用法**\n"
        "━━━━━━━━━━━━━━\n"
        "本功能結合多重趨勢系統與動能指標，提供專業級量化分析報告。\n\n"
        "🧭 **常用指令**\n"
        "• `/tech [股票代號]`：分析單一股票，例如 `/tech NVDA`。\n"
        "• `/tech [代號1] [代號2] [代號3]`：同時分析多隻股票，上限 3 隻。\n"
        "• `/tech compare [代號1] [代號2]`：橫向對比量化數據。\n\n"
        "💡 **搭配建議**\n"
        "• `/fin [代號]`：確認財報與估值。\n"
        "• `/news [代號]`：追蹤最新催化劑。\n"
        "• `/sweep add [代號]`：加入 FVG/Sweep 狙擊監控。"
    )
    part2 = (
        "📚 **量化指標儀表板指南（2/2）：指標深度解析**\n"
        "━━━━━━━━━━━━━━\n"
        "1. ⚔️ **核心評級 (Attack Gauge)**：整合 EMA、MACD、RSI、VWAP 的多空力道。\n"
        "2. 🐋 **主力籌碼 (Whale Tracking)**：觀察成交量倍率，辨識建倉或撤離。\n"
        "3. 🧬 **趨勢結構 (EMA System)**：21/60/200 EMA 判斷多空排列。\n"
        "4. 🧲 **VWAP**：機構平均持有成本，判斷價格強弱位置。\n"
        "5. 🛡️ **ATR**：波動與停損參考，避免停損過緊或過鬆。\n"
        "6. 📐 **Fibonacci Targets**：以 3 個月高低點估算延伸目標。\n"
        "7. ⏳ **TD9 序列**：偵測短期衰竭與可能反轉。\n\n"
        "🎯 **實戰提示**：量化訊號不是單點答案，建議與 `/fin`、`/news`、`/now` 綜合判斷。"
    )
    return [part1, part2]


def tech_report(data: dict[str, Any]) -> list[str]:
    symbol = data.get("symbol", "N/A")
    price = data.get("last_price", 0)
    atr = data.get("atr", 0)
    vwap = data.get("vwap", 0)
    poc = data.get("poc", 0)
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
    tp = data.get("tp_targets", {})
    fvg = data.get("fvg", {})
    sweep = data.get("sweep", "無")
    ma_filter = data.get("ma_filter", {}) or {}
    tdst = data.get("tdst", {}) or {}
    signal = data.get("confluence_payload") or data.get("confluence_signal", {}) or {}

    def get_status_icon(status: str) -> str:
        if "大買" in status:
            return "🔥"
        if "中買" in status or "小買" in status:
            return "✅"
        if "大賣" in status:
            return "💀"
        if "中賣" in status or "小賣" in status:
            return "⚠️"
        return "⚪"

    attack_icon = get_status_icon(attack)
    whale_icon = "🐋" if "買" in whale else ("🦈" if "賣" in whale else "⚪")

    # 第一頁：基礎技術量化
    page1 = (
        f"📊 **量化作戰儀表板：{symbol} (1/2)**\n"
        f"━━━━━━━━━━━━━━\n"
        f"現價：`{price}` | **ATR**：`{atr}`\n\n"
        f"⚔️ **核心動能**\n"
        f"• 綜合評級：{attack_icon} `{attack}`\n"
        f"• 主力籌碼：{whale_icon} `{whale}` (量能倍數：{vol_ratio}x)\n"
        f"• 趨勢結構：`{ema}`\n\n"
        f"🌪️ **擺盪與衰竭**\n"
        f"• MACD：{macd}\n"
        f"• RSI：{rsi}\n"
        f"• TD9：{td}\n\n"
        f"📐 **關鍵點位參考**\n"
        f"• 壓力位：`{res}`\n"
        f"• 錨定成本 (VWAP)：`{vwap}`\n"
        f"• 支撐位：`{sup}`\n\n"
        f"💰 **獲利目標測算 (Take Profit)**\n"
        f"• 短線 (2x ATR)：`{tp.get('tp1', 'N/A')}`\n"
        f"• 波段 (Fib Ext)：`{tp.get('tp_fib', 'N/A')}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"💡 下一頁：SMC 結構與共振狙擊訊號"
    )

    # 第二頁：SMC 結構與戰術
    fvg_text = f"{fvg.get('type', 'N/A')} ({fvg.get('range', 'N/A')})"
    support_line = tdst.get("support") or {}
    resistance_line = tdst.get("resistance") or {}
    signal_type = signal.get("signal_type", "NONE")
    signal_icon = "🟢" if signal_type == "STRONG_LONG" else "🔴" if signal_type == "STRONG_SHORT" else "⚪"
    entry_zone = signal.get("entry_zone") or {}
    signal_reasons = signal.get("reasons") or []
    signal_reason_text = "\n".join([f"  • {reason}" for reason in signal_reasons[:3]]) or "  • 尚無訊號。"
    entry_zone_text = signal.get("entry_zone_text") or entry_zone.get("text", "N/A")

    strategy_body = "指標未顯示強烈共振，建議於關鍵點位觀望。"
    if "買" in attack:
        stop_loss_1 = safe_round(price - 1.5 * atr, 2)
        strategy_body = f"多方動能佔優。🎯 建議進場點：VWAP ({vwap}) 或 POC ({poc}) 附近。\n" f"🛡️ 防守位：{stop_loss_1} (-1.5 ATR)。"
    elif "賣" in attack:
        strategy_body = f"空方動能佔優。📉 建議分批減碼。\n" f"🔭 觀察防禦位：VWAP ({vwap})。"

    page2 = (
        f"🎯 **SMC 狙擊戰術：{symbol} (2/2)**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🧲 **流動性與失衡區**\n"
        f"• FVG 缺口：{fvg_text}\n"
        f"• 流動性掃蕩：{sweep}\n"
        f"• POC 籌碼密集區：`{poc}`\n\n"
        f"⚡ **共振狙擊訊號**\n"
        f"• 狀態：{signal_icon} `{signal_type}`\n"
        f"• MA 濾網：`{ma_filter.get('status', 'N/A')}`\n"
        f"• TDST 區間：`{support_line.get('price', 'N/A')}` ~ `{resistance_line.get('price', 'N/A')}`\n"
        f"• 進場區間：`{entry_zone_text}`\n"
        f"• 訊號條件：\n{signal_reason_text}\n\n"
        f"💡 **戰術執行**\n"
        f"{strategy_body}"
    )

    return [page1, page2]


def tech_compare_report(data_list: list[dict[str, Any]]) -> str:
    sections = ["📊 **【多維度技術面對比】**\n━━━━━━━━━━━━━━"]

    for data in data_list:
        if "error" in data:
            sections.append(f"❌ {data.get('symbol', 'Unknown')}: 分析失敗")
            continue

        symbol = data["symbol"]
        price = data["last_price"]
        attack = data["attack_status"]
        td = data["td_status"]
        rsi = data["rsi"]
        ema = "多頭" if "多頭" in data["ema_status"] else ("空頭" if "空頭" in data["ema_status"] else "盤整")

        sections.append(f"**{symbol}** (${price})\n" f"├ 評級: `{attack}` | 趨勢: `{ema}`\n" f"└ RSI: `{rsi}` | TD: `{td}`")

    sections.append("\n💡 提示：輸入 `/tech [代號]` 查看詳細點位。")
    return "\n".join(sections)


def menu_registered_text() -> str:
    return "✅ Telegram Menu 指令已註冊完成"


def status_text(version: str, brain_status: str, system_status: str, ping_ok: bool) -> list[str]:
    icon = "🟢" if ping_ok else "🔴"
    page1 = (
        f"🔍 **顧問系統狀態報告 (1/2)**\n"
        f"━━━━━━━━━━━━━━\n"
        f"版本：{version}\n"
        f"🧠 核心連線：{icon} {'運行中' if ping_ok else '連線異常'}\n\n"
        f"🖥️ **伺服器資源狀況**\n"
        f"{system_status}"
    )

    page2 = f"🤖 **個人化 AI 與推播設定 (2/2)**\n" f"━━━━━━━━━━━━━━\n" f"{brain_status}"

    return [page1, page2]


def watch_guide() -> str:
    return (
        "👀 **雷達管理教學**\n"
        "━━━━━━━━━━━━━━\n"
        "✅ 批量新增：`/watch add TSLA NVDA`\n"
        "❌ 批量移除：`/watch del AAPL`\n"
        "📋 查看清單：`/watch list`\n"
        "🧹 清空清單：`/watch clear`"
    )


def watch_list(symbols: list[str]) -> str:
    if not symbols:
        return "👀 雷達清單：目前為空 🈳"
    return "👀 **當前雷達名單：**\n" + ", ".join([f"`{s}`" for s in symbols])


def sweep_guide() -> str:
    return (
        "🎯 **狙擊監控教學**\n"
        "━━━━━━━━━━━━━━\n"
        "本功能啟動 FVG 缺口與流動性掃蕩 (Sweep) 的 24/7 實時監控。\n"
        "當標的進入結構失衡區或發生掃蕩時，我會主動發送警報。\n\n"
        "✅ **新增監控**：`/sweep add NVDA TSLA` (支援批量)\n"
        "❌ **移除監控**：`/sweep del AAPL`\n"
        "📋 **查看清單**：`/sweep list`\n"
        "🧹 **全部清空**：`/sweep clear`"
    )


def sweep_list(symbols: list[str]) -> str:
    if not symbols:
        return "🎯 **狙擊監控名單**\n━━━━━━━━━━━━━━\n目前為空 🈳\n\n💡 提示：使用 `/sweep add [代號]` 開始監控結構共振。"
    return "🎯 **當前狙擊名單：**\n" + ", ".join([f"`{s}`" for s in symbols])


def portfolio_total_report(
    total_cost: float,
    total_value: float,
    unrealized_profit: float,
    realized_profit: float,
    history_perf: dict[str, dict[str, Any]] | None = None,
    join_date: str = "N/A",
    today_date: str = "N/A",
) -> str:
    total_all_profit = unrealized_profit + realized_profit
    unrealized_pct = (unrealized_profit / total_cost * 100) if total_cost > 0 else 0.0

    sign_u = "+" if unrealized_profit >= 0 else ""
    sign_r = "+" if realized_profit >= 0 else ""
    sign_a = "+" if total_all_profit >= 0 else ""

    lines = [
        "💰 **全球資產總盈虧報告**",
        "━━━━━━━━━━━━━━",
        f"📦 總持倉成本：`${total_cost:,.2f}`",
        f"🏦 目前總市值：`${total_value:,.2f}`",
        "",
        f"💵 未實現損益：`{sign_u}${unrealized_profit:,.2f}` ({sign_u}{unrealized_pct:.2f}%)",
        f"💰 已實現損益：`{sign_r}${realized_profit:,.2f}`",
        f"📈 累計總盈虧：`{sign_a}${total_all_profit:,.2f}`",
        "━━━━━━━━━━━━━━",
    ]

    if history_perf:
        lines.append(f"⏳ **歷史表現回溯** (加入日: `{join_date}` ~ 今日: `{today_date}`)")
        periods = [("7d", "7 Day"), ("1mo", "1 Month"), ("6mo", "6 Month"), ("ytd", "YTD"), ("1y", "1 Year"), ("max", "MAX")]
        for key, label in periods:
            perf = history_perf.get(key)
            if perf:
                diff = perf["diff"]
                pct = perf["pct"]
                date_str = perf.get("date_str", "N/A")
                s = "+" if diff >= 0 else ""
                lines.append(f"├ {label} ({date_str})：`{s}${diff:,.2f}` ({s}{pct:.2f}%)")
            else:
                lines.append(f"├ {label}：`N/A` (`N/A`)")
        lines.append("━━━━━━━━━━━━━━")

    return "\n".join(lines)


def bc_settings_status(enabled: bool, interval: int) -> str:
    status = "✅ 已開啟" if enabled else "❌ 已關閉"
    return (
        "📢 **自動推播設定**\n"
        "━━━━━━━━━━━━━━\n"
        f"🔹 目前狀態：{status}\n"
        f"⏱ 推播頻率：`{interval}` 分鐘\n\n"
        "💡 指令：\n"
        "• `/bc on` - 開啟自動推播\n"
        "• `/bc off` - 關閉自動推播\n"
        "• `/bc timer [分鐘]` - 設定頻率 (最少 30 分)"
    )


def data_clear_confirm_text() -> str:
    return (
        "⚠️ **高風險操作確認**\n"
        "━━━━━━━━━━━━━━\n"
        "你即將清除以下資料：\n"
        "• 持股庫存（buy / sell / list）\n"
        "• 已實現總損益\n"
        "• watch 清單\n"
        "• sweep 狙擊清單\n\n"
        "若確定執行，請在 60 秒內再輸入一次：`data clear`"
    )


def data_clear_done_text() -> str:
    return "🧹 **資料已清除完成**\n" "━━━━━━━━━━━━━━\n" "你的資產庫存、總損益、watch 與 sweep 清單已清空。"


def buy_success(symbol: str, price: float, qty: float) -> str:
    p_val = safe_round(price, 2)
    return f"✅ **已成功記錄買入**\n━━━━━━━━━━━━━━\n📈 標的：`{symbol.upper()}`\n🔹 股數：`{qty:g}` 股\n💰 成本：`${p_val:.2f}`"


def sell_success(symbol: str, price: float, qty: float, profit: float, rem: float) -> str:
    p_val = safe_round(profit, 2)
    pr_val = safe_round(price, 2)
    sign = "+" if p_val >= 0 else ""
    icon = "💰" if p_val >= 0 else "📉"
    msg = (
        f"✅ **已成功記錄賣出**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 標的：`{symbol.upper()}`\n"
        f"🔹 數量：`{qty - rem:g}` 股\n"
        f"💵 價格：`${pr_val:.2f}`\n"
        f"{icon} 損益：{sign}${p_val:.2f} USD"
    )
    if rem > 0:
        msg += f"\n⚠️ **庫存不足**：尚有 `{rem:g}` 股未能賣出。"
    return msg


def portfolio_list(rows: list[dict[str, Any]], summary: dict[str, Any], page: int = 1, total_pages: int = 1) -> str:
    if not rows:
        return "📋 **持股明細**：目前無庫存資料。 🈳"

    lines = [f"📋 **持股詳細明細 (第 {page}/{total_pages} 頁)**", "━━━━━━━━━━━━━━"]

    # 使用從外部傳入的全域總計，避免分頁導致計算錯誤
    total_cost_all = summary.get("total_cost", 0.0)
    total_profit = summary.get("pl_val", 0.0)
    realized_profit = summary.get("realized_profit", 0.0)

    for r in rows:
        symbol = r["symbol"]
        qty = float(r["quantity"])
        avg_cost = float(r["avg_cost"])
        curr = r.get("current_price", "N/A")
        day_diff = r.get("day_diff", 0.0)
        day_pct = r.get("day_pct", 0.0)

        cost_basis = avg_cost * qty

        if isinstance(curr, (int, float)):
            market_value = safe_round(float(curr) * qty, 2)
            profit = safe_round((float(curr) - avg_cost) * qty, 2)
            pct = (profit / cost_basis * 100) if cost_basis else 0.0

            sign = "+" if profit >= 0 else ""
            trend_icon = "📈" if profit >= 0 else "📉"

            day_sign = "+" if day_diff >= 0 else ""

            lines.append(
                f"{trend_icon} **{symbol}** (`${safe_round(float(curr), 2):.2f}` | {day_sign}{day_diff:.2f} / {day_sign}{day_pct:.2f}%)\n"
                f"├ 股數：`{qty:g}` | 均價：`${safe_round(avg_cost, 2):.2f}`\n"
                f"├ 總成本：`${cost_basis:,.2f}`\n"
                f"└ 市值：`${market_value:,.2f}` | 獲利：{sign}${profit:,.2f} ({sign}{pct:.2f}%)\n"
            )
        else:
            lines.append(f"⚪ **{symbol}**\n" f"├ 股數：`{qty:g}` | 成本：`${safe_round(avg_cost, 2):.2f}`\n" f"└ 現價：`N/A`\n")

    unrealized_pct = (total_profit / total_cost_all * 100) if total_cost_all > 0 else 0.0
    realized_pct = (realized_profit / total_cost_all * 100) if total_cost_all > 0 else 0.0

    sign_total = "+" if total_profit >= 0 else ""
    sign_realized = "+" if realized_profit >= 0 else ""

    lines.append("━━━━━━━━━━━━━━")
    if total_pages == 1 or page == total_pages:
        lines.append(f"📦 **持倉總成本**：`${total_cost_all:,.2f} USD`")
        lines.append(f"💵 **未實現損益**：`{sign_total}${total_profit:,.2f} USD` ({sign_total}{unrealized_pct:.2f}%)")
        lines.append(f"💰 **已實現總損益**：`{sign_realized}${realized_profit:,.2f} USD` ({sign_realized}{realized_pct:.2f}%)")

    lines.append(f"\n💡 提示：使用 `/list [頁碼]` 切換分頁。")
    return "\n".join(lines)


def fin_report(data: dict[str, Any]) -> str:
    rev_growth = data.get("revenue_growth_qoq", "N/A")
    eps_growth = data.get("eps_growth_qoq", "N/A")

    growth_section = ""
    if rev_growth != "N/A" or eps_growth != "N/A":
        growth_section = f"📈 **季度增長 (QoQ)**\n• 營收增長：`{rev_growth}`\n• EPS 增長 ：`{eps_growth}`\n\n"

    return (
        f"📊 **財報快照：{data.get('company_name', data.get('symbol', 'N/A'))}**\n"
        "━━━━━━━━━━━━━━\n"
        f"🔹 代號：`{data.get('symbol', 'N/A')}`\n"
        f"💵 現價：`${data.get('current_price', 'N/A')}`\n"
        f"🏗️ 產業：{data.get('sector', 'N/A')} / {data.get('industry', 'N/A')}\n"
        f"💎 市值：`{data.get('market_cap', 'N/A')}`\n"
        f"📢 TTM 營收：`{data.get('revenue_ttm', 'N/A')}`\n"
        f"💵 TTM 淨利：`{data.get('net_income', 'N/A')}`\n"
        f"📝 EPS (TTM)：`{data.get('trailing_eps', 'N/A')}`\n\n"
        f"{growth_section}"
        f"📐 **估值與範圍**\n"
        f"• 本益比 (TTM)：`{data.get('trailing_pe', 'N/A')}` / 預期：`{data.get('forward_pe', 'N/A')}`\n"
        f"• 毛利率：`{data.get('gross_margin', 'N/A')}` | 淨利率：`{data.get('profit_margin', 'N/A')}`\n"
        f"• 52 週：`{data.get('year_low', 'N/A')} - {data.get('year_high', 'N/A')}`\n"
        + (
            f"\n📅 **最新季報 ({data.get('latest_quarter')})**\n"
            f"• EPS：`{data.get('latest_quarter_eps', 'N/A')}`\n"
            f"• 營收：`{data.get('latest_quarter_revenue', 'N/A')}`"
            if data.get("latest_quarter")
            else ""
        )
    )


def news_help_text() -> str:
    return (
        "📰 **新聞功能指南**\n"
        "━━━━━━━━━━━━━━\n"
        "提供即時市場新聞、個股相關新聞及 AI 深度解析。\n\n"
        "**指令用法：**\n"
        "• `/news`：預設隨機推送持股或關注標的的新聞。\n"
        "• `/news [代號]`：查詢指定股票的即時解讀。\n"
        "• `/news [關鍵詞]`：搜尋特定主題新聞。\n"
        "• `/news list`：查看新聞來源清單。\n\n"
        "**AI 深度解析：**\n"
        "包含重要程度評級、新聞大綱、專業觀點及 SMC 結構影響分析。\n\n"
        "📊 祝您投資順利！"
    )


def hidden_op_text(current_model: str) -> str:
    return (
        "🕵️ **隱藏功能指令集 (Hidden Features)**\n"
        "━━━━━━━━━━━━━━\n"
        f"🤖 當前 AI 核心：`{current_model}`\n\n"
        "📌 **指令清單：**\n"
        "• `/op model [flash|pro]` - 切換 AI 模型\n"
        "• `/op log` - 查看系統實時日誌\n"
        "• `/op log clear` - 清除日誌檔案\n"
        "• `/op quota` - 查詢今日 API 配額進度\n"
        "━━━━━━━━━━━━━━\n"
        "💡 提示：這些指令不會顯示在選單中。"
    )


def quota_text(used: int, limit: int, percent: float) -> str:
    # 建立進度條
    bar_length = 10
    filled_length = int(bar_length * percent / 100)
    if filled_length > bar_length:
        filled_length = bar_length
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    return (
        "💎 **Gemini 配額使用報告**\n"
        "━━━━━━━━━━━━━━\n"
        f"🔹 今日已使用：`{used:,}` Token\n"
        f"🔸 每日上限：`{limit:,}` Token\n"
        f"📊 目前進度：`{percent:.2f}%`\n"
        f"⏳ 使用狀態：`[{bar}]`"
    )
