"""ai_core.py
AI 思考層：決定美股顧問如何分析與回覆。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import brain
from utils import safe_round

SYSTEM_PROMPT_TEMPLATE = """
# 角色：機構級 SMC (Smart Money Concepts) 與多時間框架 (MTF) 量化交易 AI 副官
你是 {user_name} 的私人投資副官，具備頂尖算力、冷靜、精準。

【當前時間】
現在是西元 {current_time}。請以此精確時間為基準進行最新分析。

=========================================
【核心處理原則與輸出限制】
=========================================
1. 語言規範：全程使用「繁體中文」回覆。除了原文網址與股票代號外，嚴禁簡體中文。
2. 實時數據優先：你必須嚴格基於下方提供的「市場快照與量化指標」進行分析。若與你的內部訓練數據有衝突，請以提供的数据為準。嚴禁虛構股價或指標數值。
3. 嚴格遵守格式：禁止使用 Markdown 表格或產生任何圖片。只能使用符號與縮排。
4. 原子化輸出 (Atomic Output)：情報與分析必須精煉、直接給出重點。嚴禁任何起承轉合的廢話。
5. 資訊不重複原則：在【戰術決策】中，嚴禁再次覆述上方儀表板已存在的數字。必須直接將這些數據轉化為「具體行動計畫」。
6. 趨勢結構標籤：必須嚴格且僅能使用以下三種標籤之一：/上升趨勢/、/下跌趨勢/、/盤整區間/。
7. 絕對完整性：請務必將所有分析細節講得非常透徹，確保輸出內容結構完整，將話講完為止。
8. 深度內容：優先提供新聞深度摘要、核心催化劑、領頭羊公司動態、供應鏈風險、長中短期展望。

=========================================
【指標定義與 AI 推論邏輯庫】
=========================================
1. 多時間框架 (MTF) 協同邏輯：
   - 1D (日 K)：決定宏觀大方向與主要結構。
   - 4H (四小時 K)：尋找關鍵結構支撐/壓力與大級別 FVG。
   - 1H (小時 K)：尋找短線流動性掃蕩作為進場點。
   註：若快照中未提供 4H/1H 數據，請基於 1D 趨勢與波幅 (ATR) 推論短期關鍵位。
2. SMC 聰明錢核心概念：
   - FVG (公允價值缺口)：標註 /看漲 FVG/ 或 /看跌 FVG/。
   - 流動性掃蕩 (Liquidity Sweep)：主力刻意跌破前低或突破前高。
   - POC (Point of Control)：成交量最大的價格位。若回踩 POC + FVG 為強共振進場點。
3. 核心量化指標：
   - 主力籌碼量 (Whale Volume)：大買/大賣 (>2倍)、中買/中賣 (1.5-2倍)、小買/小賣 (1.2-1.5倍)。
   - 進攻指標 (Attack Gauge)：綜合 EMA、MACD、RSI、VWAP 評分。
4. 🛡️ 恐慌指數濾網 (VIX Filter)：
   - 若 VIX > 25，強制將「大買」降級為「觀察」，並嚴格縮小建議進場區間，警惕系統性風險。

=========================================
【標準輸出模板】
=========================================
📰 【市場情報速遞】
* 🌡️ 情緒分數：[1-10 分]
* 💡 核心驅動：[1-2 句話精煉總結目前影響價格的最核心基本面、財報或新聞事件]
* 📌 關鍵快訊：
  - [快訊 1：直接陳述事實與對盤面的影響]
  - [快訊 2：直接陳述事實與對盤面的影響]

📊 【多時區量化與 SMC 儀表板】
* ⏱️ 趨勢結構：日線 [填入標籤]｜4H [填入標籤]｜1H [填入標籤]
* ⚔️ 進攻指標：[填入數值]
* 🐋 主力籌碼：[填入數值]
* 🛡️ 波幅風險：ATR = [數值] (VIX 狀態：[正常/恐慌])
* 📍 控制點參考：POC = [數值]
* 🧲 SMC 結構：[標註最近的關鍵 FVG 屬於 /看漲 FVG/ 或 /看跌 FVG/，價格區間]
* 🎯 建議入場區間：[基於 SMC 結構與流動性，給出具體價格區間]

💡 【戰術決策】
[請在此給出 3-4 句精煉的戰略計畫。
1. 說明目前大級別趨勢與小級別回檔的關係。
2. 說明如何利用「流動性掃蕩」結合上述 FVG/POC 區間進行進場佈局。
3. 必須給出基於 ATR 計算的明確防守 (停損) 價格。
4. 若 VIX 高於 25，必須在最後加註風險警語。]
""".strip()


def get_current_time_str() -> str:
    """獲取精確到秒的當前時間與星期。"""
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_str = weekdays[now.weekday()]
    return now.strftime(f"%Y年%m月%d日 {weekday_str} %H:%M:%S")


def sanitize_for_telegram(text: str) -> str:
    if not text:
        return ""
    return text.strip()


def ask_flash(
    prompt: str,
    user_name: str,
    *,
    user_id: int | None = None,
    temperature: float = 0.45,
    max_output_tokens: int = 4000,
    urls: list[str] | None = None,
) -> str:
    current_time = get_current_time_str()
    return sanitize_for_telegram(
        brain.generate_text(
            prompt,
            system_instruction=SYSTEM_PROMPT_TEMPLATE.format(user_name=user_name, current_time=current_time),
            mode="flash",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            user_id=user_id,
            urls=urls,
        )
    )


def ask_pro(
    prompt: str,
    user_name: str,
    *,
    user_id: int | None = None,
    temperature: float = 0.35,
    max_output_tokens: int = 4000,
    urls: list[str] | None = None,
) -> str:
    current_time = get_current_time_str()
    return sanitize_for_telegram(
        brain.generate_text(
            prompt,
            system_instruction=SYSTEM_PROMPT_TEMPLATE.format(user_name=user_name, current_time=current_time),
            mode="pro",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            user_id=user_id,
            urls=urls,
        )
    )


def ask_model(
    prompt: str,
    user_name: str,
    model: str | None = None,
    *,
    user_id: int | None = None,
    temperature: float = 0.35,
    max_output_tokens: int = 4000,
    urls: list[str] | None = None,
) -> str:
    model_name = (model or "flash").strip().lower()
    if model_name == "pro":
        return ask_pro(prompt, user_name, user_id=user_id, temperature=temperature, max_output_tokens=max_output_tokens, urls=urls)
    return ask_flash(prompt, user_name, user_id=user_id, temperature=temperature, max_output_tokens=max_output_tokens, urls=urls)


def summarize_tech_news(symbol: str, news_item: dict[str, Any], user_name: str, model: str | None = None, user_id: int | None = None) -> str:
    """一般科技新聞：強制輸出情緒分數、重要程度與 Hashtag"""
    title = news_item.get("title", "")
    desc = news_item.get("description", "")
    url = news_item.get("url", "")

    import market_api

    price_info = market_api.get_fast_price(symbol)
    price_str = f"（當前股價：{price_info} USD）" if price_info != "N/A" else ""

    prompt = f"""
請幫 {user_name} 產出「消息面主導」的新聞戰報，主題為 {symbol} {price_str}。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 這份回覆要以「新聞催化劑」為主，不要把重點放在技術指標教科書。
2. 必須回答：事件本質、影響公司、影響產業鏈、短中期可能催化。
3. 可補充 SMC 觀點，但僅作輔助，不可喧賓奪主。
4. 固定段落：A消息重點、B多空催化、C風險點、D交易觀察。
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=2500, urls=[url] if url else None)


def summarize_earnings_report(symbol: str, news_item: dict[str, Any], user_name: str, model: str | None = None, user_id: int | None = None) -> str:
    """財報專用：強制提取 EPS、營收與未來指引(Guidance)"""
    title = news_item.get("title", "")
    desc = news_item.get("description", "")
    url = news_item.get("url", "")

    import market_api

    price_info = market_api.get_fast_price(symbol)
    price_str = f"（當前股價：{price_info} USD）" if price_info != "N/A" else ""

    prompt = f"""
{user_name}，這是 {symbol} {price_str} 的最新財報/業績新聞，請做「財報面主導」分析。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 必須先提取 EPS、營收、Guidance、YoY/QoQ（若新聞未提供則明確標示缺失）。
2. 重點是估值與基本面變化：成長性、獲利品質、預期修正。
3. 技術面只可放在最後「市場反應觀察」一句，不可主導全文。
4. 固定段落：A關鍵數字、B財報解讀、C估值影響、D後續追蹤。
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.2, max_output_tokens=2500, urls=[url] if url else None)


def analyze_tech_comparison(data_list: list[dict[str, Any]], user_name: str, model: str | None = None, user_id: int | None = None) -> str:
    """提供 AI 戰術評析：比較多支股票的量價與行業關聯。"""

    prompt = f"""
{user_name}，請對以下幾支股票進行橫向 SMC 與量化技術對比分析：
{data_list}

【要求】
1. 判斷它們在 SMC 結構上的優劣（誰在掃蕩低點，誰在填補 FVG）。
2. 根據 Attack Gauge 與 Whale Volume 給出買入、觀望、避險建議。
3. 若 VIX 高於 25，需特別強調保守策略。
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=2000)


def infer_related_news_terms(symbol: str, user_name: str, *, user_id: int | None = None) -> list[str]:
    prompt = f"""
請針對以下股票代號列出最重要的相關公司、產品、服務 or 生態圈關鍵詞，並只輸出 3 到 5 個關鍵詞，使用英文或常見標的名稱。
股票代號：{symbol}

輸出格式：僅用逗號分隔，不要加其他文字。
""".strip()
    result = ask_flash(prompt, user_name, user_id=user_id, temperature=0.4, max_output_tokens=500)
    items = [item.strip() for item in result.replace(";", ",").replace("\n", ",").split(",") if item.strip()]
    return items[:5]


def ask_ai_investment_advice(
    symbol: str,
    query: str,
    snapshot: dict[str, Any],
    news_items: list[dict[str, Any]],
    user_name: str,
    user_holdings: dict[str, Any] | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    current_time = get_current_time_str()
    news_text = "\n".join(f"- {n.get('title','')}｜{n.get('description','')}" for n in news_items[:3]) or "目前無可用新聞。"

    urls = [n.get("url") for n in news_items if n.get("url")]

    holding_info = "目前尚未持有該標的。"
    if user_holdings and symbol in user_holdings:
        position = user_holdings[symbol]
        holding_info = f"持股狀態：持有 {position.get('shares', 0):.2f} 股，平均成本 ${position.get('avg_cost', 0):.2f}。"

    def _f(val):
        res = safe_round(val, 2)
        if isinstance(res, (int, float)):
            return f"{res:.2f}"
        return res

    # 獲取 VIX 數值
    import market_api

    vix_data = market_api.get_macro_quote("VIX")
    raw_vix = vix_data.get("price", 0)
    vix_val = float(raw_vix) if isinstance(raw_vix, (int, float)) else 0.0
    vix_str = f"{vix_val:.2f} ({'恐慌' if vix_val > 25 else '正常'})" if vix_val > 0 else "N/A"

    prompt = f"""
【報告產生時間：{current_time}】
{user_name} 詢問標的：{symbol}
問題：{query}

{holding_info}

市場快照與量化指標（實時數據）：
- 現價：{_f(snapshot.get('last_price', snapshot.get('price')))}
- 今日漲跌：{_f(snapshot.get('diff', 0))} ({_f(snapshot.get('pct', 0))}%)
- 趨勢結構：{snapshot.get('ema_status', 'N/A')}
- 支撐/壓力：{_f(snapshot.get('support'))} / {_f(snapshot.get('resistance'))}
- 進攻指標 (Attack Gauge)：{snapshot.get('attack_status', '觀察')}
- 主力籌碼 (Whale Volume)：{snapshot.get('whale_status', '中立')} (倍率: {snapshot.get('vol_ratio', 1)})
- SMC 結構：{snapshot.get('fvg', {}).get('type', 'N/A')} ({snapshot.get('fvg', {}).get('range', 'N/A')})
- 流動性掃蕩：{snapshot.get('sweep', '無')}
- POC 控制點：{_f(snapshot.get('poc', 0))}
- ATR 波幅：{_f(snapshot.get('atr', 0))}
- RSI (14)：{_f(snapshot.get('rsi', 'N/A'))}
- MACD：{snapshot.get('macd_status', 'N/A')}
- 🛡️ VIX 指數：{vix_str}

近期新聞：
{news_text}

本任務屬於「個股深度回答模式（/ask）」，請以深度與可執行性為最高優先。
請嚴格套用【標準輸出模板】進行深度分析，並特別注意 VIX 濾網規則。
請確保【多時區量化與 SMC 儀表板】中的數值與上述提供的一致。
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=4000, urls=urls)


def ask_stock_brief(
    symbol: str,
    query: str,
    snapshot: dict[str, Any],
    news_items: list[dict[str, Any]],
    user_name: str,
    *,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    """自然對話的個股初步分析：短、準、先給方向。"""
    news_text = "\n".join(f"- {n.get('title','')}" for n in news_items[:2]) or "- 暫無重大新聞"
    prompt = f"""
{user_name} 的問題：{query}
標的：{symbol}
快照：{snapshot}
最近消息：
{news_text}

請輸出「初步分析模式」：
1. 先給一句結論（偏多/中性/偏空）。
2. 再給 3 點重點：消息面、技術面、風險點。
3. 保持精簡、可讀，不要寫成超長報告。
4. 若數據不足要直接講，不可腦補。
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=1600)


def analyze_financial_snapshot(
    symbol: str,
    fundamentals: dict[str, Any],
    news_items: list[dict[str, Any]],
    user_name: str,
    *,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    """/fin 單股專用：財報與估值主導，技術面僅輔助。"""
    news_text = "\n".join(f"- {n.get('title','')} ({n.get('source','Unknown')})" for n in news_items[:2]) or "- 暫無近期新聞"
    urls = [n.get("url") for n in news_items if n.get("url")]
    prompt = f"""
{user_name} 正在看 {symbol} 的財報快照，請輸出「財報面主導」分析。

財務資料：
{fundamentals}

近期新聞：
{news_text}

請嚴格遵守：
1. 先看基本面與估值，不要先談技術線圖。
2. 固定段落：A財報關鍵數字、B獲利品質、C估值判斷、D後續觀察。
3. 若資料缺失要明確標註「資料不足」。
4. 技術面最多 1 段作輔助觀察。
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=2200, urls=urls)


def compare_financials(
    symbols: list[str],
    fundamentals_map: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    user_name: str,
    user_holdings: dict[str, Any] | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    current_time = get_current_time_str()
    holdings = user_holdings or {}
    summary_lines: list[str] = []
    all_urls: list[str] = []

    def _f(val):
        res = safe_round(val, 2)
        if isinstance(res, (int, float)):
            return f"{res:.2f}"
        return res

    for symbol in symbols:
        data = fundamentals_map[symbol]
        holding_note = ""
        if symbol in holdings:
            position = holdings[symbol]
            holding_note = f"使用者持有 {symbol} {position.get('shares', 0):.2f} 股，成本 ${position.get('avg_cost', 0):.2f}。"
        news_items = news_map.get(symbol, [])
        for n in news_items:
            if n.get("url"):
                all_urls.append(n["url"])

        news_text = "\n".join(f"- {n.get('title','')} ({n.get('source','Unknown')}) {n.get('url','')}" for n in news_items[:2]) or "- 無可用新聞。"

        summary_lines.append(
            f"{symbol} - {data.get('company_name', symbol)}\n"
            f"現價：{_f(data.get('current_price'))}，市值：{data.get('market_cap', 'N/A')}\n"
            f"EPS：{_f(data.get('trailing_eps'))} / {_f(data.get('forward_eps'))}，"
            f"P/E：{_f(data.get('trailing_pe'))} / {_f(data.get('forward_pe'))}\n"
            f"TTM 營收：{data.get('revenue_ttm', 'N/A')}，TTM 淨利：{data.get('net_income', 'N/A')}\n"
            f"毛利率：{data.get('gross_margin', 'N/A')}，淨利率：{data.get('profit_margin', 'N/A')}\n"
            f"最新季：{data.get('latest_quarter', 'N/A')}，EPS：{_f(data.get('latest_quarter_eps'))}，營收：{data.get('latest_quarter_revenue', 'N/A')}\n"
            f"{holding_note}\n"
            f"最新消息：\n{news_text}"
        )
    prompt = f"""
【報告產生時間：{current_time}】
{user_name} 你好。
請你作為專業的美股交易副官，根據以下財務數據、產業領頭羊動態與供應鏈風險比較這幾家公司：{', '.join(symbols)}。

"""
    prompt += "\n\n".join(summary_lines)
    prompt += "\n\n請給我極度深度的分析，將所有細節講清楚，絕對不要斷句：\n"
    prompt += (
        "1. 哪支股票整體財務健康與技術護城河較佳，並說明具體理由。\n"
        "2. 依據成長性、供應鏈穩定性與估值合理性做出詳細解釋。\n"
        "3. 根據最新新聞與未來催化劑，給出戰略排序。\n"
        "4. 回應必須詳盡且專業，展現強大的數據洞察力。"
    )
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=4000, urls=all_urls)


def analyze_whale_insider(
    symbol: str,
    insider_data: list[dict[str, Any]],
    institutional_data: list[dict[str, Any]],
    user_name: str,
    model: str | None = None,
    user_id: int | None = None,
) -> str:
    """分析「大鯨魚/內部人」情報，給出綜合判斷。"""
    current_time = get_current_time_str()

    # 格式化內線交易
    insider_lines = []
    for item in insider_data[:10]:
        name = item.get("name", "Unknown")
        share = item.get("share", 0)
        change = item.get("change", 0)
        price = item.get("transactionPrice", 0)
        date = item.get("filingDate", "N/A")
        action = "買入" if change > 0 else "賣出"
        insider_lines.append(f"- {date}｜{name}｜{action} {abs(change):,} 股 @ ${price}")
    insider_text = "\n".join(insider_lines) or "暫無近期重大內線交易紀錄。"

    # 格式化機構持倉
    inst_lines = []
    for item in institutional_data[:10]:
        name = item.get("name", "Unknown")
        share = item.get("share", 0)
        change = item.get("change", 0)
        date = item.get("reportDate", "N/A")
        action = "加倉" if change > 0 else "減倉"
        inst_lines.append(f"- {date}｜{name}｜{action} {abs(change):,} 股 (持股: {share:,})")
    inst_text = "\n".join(inst_lines) or "暫無近期重大機構持倉變動紀錄。"

    prompt = f"""
【報告產生時間：{current_time}】
標的：{symbol}
「大鯨魚/內部人」實時追蹤分析

【內線交易紀錄 (SEC Form 4)】
{insider_text}

【機構持倉紀錄 (13F/Ownership)】
{inst_text}

請以「頂尖交易副官」人格，針對上述「大鯨魚」動向進行深度解析。
你的目標是找出「真情報」：結合技術面與基本面（假設目前已有良好表現），內部人與大機構的動作是否在背書目前的漲勢或預示反轉？

【嚴格限制】
1. 只能根據上方提供的「內線交易紀錄」與「機構持倉紀錄」下結論，不可憑空補資料。
2. 若資料不足，必須直接標示「資料不足」，不可延伸猜測。
3. 禁止泛談總經與無關新聞，重點必須鎖定：內部人 / 機構 / 資金方向。

【分析要求】
1. 內部人行為分析：CEO/CFO 是在「偷偷賣」還是「低位加倉」？這傳達了什麼信心訊號？
2. 機構博弈分析：橋水、文藝復興或先鋒領航等大機構的近期動作代表了什麼資本流向？
3. 「真情報」綜合判定：給出 1-10 分的「鯨魚信心指數」，並給出具體的戰術結論。
4. 固定輸出格式（不可改標題）：
   A. 內部人重點
   B. 機構重點
   C. 資金方向結論（偏多/中性/偏空）
   D. 鯨魚信心指數（1-10）
   E. 戰術建議（僅 3 點）
5. 輸出必須詳細，講透徹，嚴格遵守副官標籤規範，絕對不要斷句。
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=3500)


def chat_with_user(
    query: str,
    user_name: str,
    context_symbol: str | None = None,
    snapshot: dict[str, Any] | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    if context_symbol:
        prompt = f"""
{user_name} 的自然語言問題：{query}
偵測到股票代號：{context_symbol}
市場快照：{snapshot or {}}

請轉為個股「簡述模式」。
【要求】
1. 使用條列式簡述。
2. 包含 SMC 核心位、POC 參考。
3. 內容精確，不需要過度展開，但要將話講完，絕對不要斷句。
""".strip()
        return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.38, max_output_tokens=4000)

    prompt = f"""
{user_name} 說：{query}
請以「機構級 AI 副官」身份回答。如果這是一般問題，請直接以最適合的角度給出清晰、專業且務實的回覆。
回答要有特色，語氣冷靜且精準。
【要求】
1. 絕對完整性：嚴禁斷句或草草結束。
2. 保持簡練且完整，必要時可用符號與縮排排版。
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.5, max_output_tokens=4000)
