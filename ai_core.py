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
2. 嚴格遵守格式：禁止使用 Markdown 表格或產生任何圖片。只能使用符號與縮排。
3. 原子化輸出 (Atomic Output)：情報與分析必須精煉、直接給出重點。嚴禁任何起承轉合的廢話。
4. 資訊不重複原則：在【戰術決策】中，嚴禁再次覆述上方儀表板已存在的數字。必須直接將這些數據轉化為「具體行動計畫」。
5. 趨勢結構標籤：必須嚴格且僅能使用以下三種標籤之一：/上升趨勢/、/下跌趨勢/、/盤整區間/。
6. 絕對完整性：請務必將所有分析細節講得非常透徹，確保輸出內容結構完整，將話講完為止。
7. 深度內容：優先提供新聞深度摘要、核心催化劑、領頭羊公司動態、供應鏈風險、長中短期展望。

=========================================
【指標定義與 AI 推論邏輯庫】
=========================================
1. 多時間框架 (MTF) 協同邏輯：
   - 1D (日 K)：決定宏觀大方向。
   - 4H (四小時 K)：尋找關鍵結構支撐/壓力與大級別 FVG。
   - 1H (小時 K)：尋找短線流動性掃蕩作為進場點。
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
* ⚔️ 進攻指標：[大買 / 中買 / 小買 / 觀察 / 小賣 / 中賣 / 大賣]
* 🐋 主力籌碼：[大買 / 中買 / 小買 / 中立 / 小賣 / 中賣 / 大賣]
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

def ask_flash(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.45, max_output_tokens: int = 4000, urls: list[str] | None = None) -> str:
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

def ask_pro(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.35, max_output_tokens: int = 4000, urls: list[str] | None = None) -> str:
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
請幫 {user_name} 總結這篇關於 {symbol} {price_str} 的科技/趨勢新聞。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 分析對領頭羊公司地位、產業上下游供應鏈及技術護城河的影響。
2. 結合 SMC 邏輯，評估此利多/利空是否可能觸發流動性掃蕩或回踩 FVG。
3. 輸出必須詳細，講透徹，絕對禁止斷句。
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
{user_name}，這是 {symbol} {price_str} 的最新財報/業績新聞。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 提取 EPS、營收與 Guidance。
2. 評估財測對大級別趨勢結構的衝擊，以及是否會產生新的 FVG 缺口。
3. 輸出必須長串且完整，細節講透徹，絕對禁止斷句。
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
    news_text = "\n".join(
        f"- {n.get('title','')}｜{n.get('description','')}"
        for n in news_items[:3]
    ) or "目前無可用新聞。"
    
    urls = [n.get("url") for n in news_items if n.get("url")]

    holding_info = "目前尚未持有該標的。"
    if user_holdings and symbol in user_holdings:
        position = user_holdings[symbol]
        holding_info = (
            f"持股狀態：持有 {position.get('shares', 0):.2f} 股，平均成本 ${position.get('avg_cost', 0):.2f}。"
        )

    def _f(val):
        res = safe_round(val, 2)
        if isinstance(res, (int, float)):
            return f"{res:.2f}"
        return res

    # 獲取 VIX 數值
    import market_api
    vix_data = market_api.get_macro_quote("VIX")
    vix_val = vix_data.get("price", 0)
    vix_str = f"{vix_val:.2f} ({'恐慌' if vix_val > 25 else '正常'})"

    prompt = f"""
【報告產生時間：{current_time}】
{user_name} 詢問標的：{symbol}
問題：{query}

{holding_info}

市場快照與量化指標：
- 現價：{_f(snapshot.get('last_price', snapshot.get('price')))}
- 今日漲跌：{_f(snapshot.get('diff', 0))} ({_f(snapshot.get('pct', 0))}%)
- 支撐/壓力：{_f(snapshot.get('support'))} / {_f(snapshot.get('resistance'))}
- 進攻指標：{snapshot.get('attack_status', '觀察')}
- 主力籌碼：{snapshot.get('whale_status', '中立')} (倍率: {snapshot.get('vol_ratio', 1)})
- SMC 結構：{snapshot.get('fvg', {}).get('type', 'N/A')} ({snapshot.get('fvg', {}).get('range', 'N/A')})
- 流動性掃蕩：{snapshot.get('sweep', '無')}
- POC 控制點：{_f(snapshot.get('poc', 0))}
- ATR 波幅：{_f(snapshot.get('atr', 0))}
- 🛡️ VIX 指數：{vix_str}

近期新聞：
{news_text}

請嚴格套用【標準輸出模板】進行深度分析，並特別注意 VIX 濾網規則。
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=4000, urls=urls)

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
            if n.get("url"): all_urls.append(n["url"])
            
        news_text = "\n".join(
            f"- {n.get('title','')} ({n.get('source','Unknown')}) {n.get('url','')}"
            for n in news_items[:2]
        ) or "- 無可用新聞。"

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

def chat_with_user(
query: str, user_name: str, context_symbol: str | None = None, snapshot: dict[str, Any] | None = None, user_id: int | None = None, model: str | None = None) -> str:
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
    return ask_model(prompt, user_name, model=model, temperature=0.5, max_output_tokens=4000)
