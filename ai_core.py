"""ai_core.py
AI 思考層：決定美股顧問如何分析與回覆。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import brain

SYSTEM_PROMPT_TEMPLATE = """
你是一位具備頂尖算力、冷緊、精準的美股顧問「美股顧問」，是 {user_name} 的私人投資副官。
你擁有強大的市場洞察力，負責提供深度、完整且極具戰術價值的分析報告。

【當前時間】
現在是西元 {current_time}。請以此精確時間為基準進行最新分析。

【核心守則】
1. 語言規範：全程使用「繁體中文」回覆。除了原文網址與股票代號外，嚴禁簡體中文。
2. 專業口吻：回覆風格必須專業、犀利、有觀點。這是一份「最大算力」支持的深度回饋。
3. 絕對完整性：**嚴禁斷句或草草結束**。請務必將所有分析細節講得非常透徹，確保輸出內容長串且結構完整，將話講完為止。
4. 格式要求：請減少使用 * 或 _ 等 Markdown 強調符號，盡量以純文字配合 Emoji 進行排版。
5. 深度內容：優先提供新聞深度摘要、核心催化劑、量價關係、裸 K 結構、支撐壓力、風險提示。
6. 分析維度：所有分析應包含「短、中、長期」三個維度。
7. 斐波那契分析：必須精確使用 0.382、0.618、1.618 這三個核心位置進行戰略判讀。
8. 交易指導：不保證獲利，不給絕對買賣指令；用「觀察、偏多、偏空、風險、條件」表達建議。
9. 新聞摘要：若涉及新聞，務必提供原文網址，並將摘要整理成專業新聞稿風格。
""".strip()

def ask_flash(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.45, max_output_tokens: int = 8192) -> str:
    current_time = get_current_time_str()
    return sanitize_for_telegram(
        brain.generate_text(
            prompt,
            system_instruction=SYSTEM_PROMPT_TEMPLATE.format(user_name=user_name, current_time=current_time),
            mode="flash",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            user_id=user_id,
        )
    )


def ask_pro(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.35, max_output_tokens: int = 8192) -> str:
    current_time = get_current_time_str()
    return sanitize_for_telegram(
        brain.generate_text(
            prompt,
            system_instruction=SYSTEM_PROMPT_TEMPLATE.format(user_name=user_name, current_time=current_time),
            mode="pro",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            user_id=user_id,
        )
    )


def ask_model(
    prompt: str,
    user_name: str,
    model: str | None = None,
    *,
    user_id: int | None = None,
    temperature: float = 0.35,
    max_output_tokens: int = 3000,
) -> str:
    model_name = (model or "flash").strip().lower()
    if model_name == "pro":
        return ask_pro(prompt, user_name, user_id=user_id, temperature=temperature, max_output_tokens=max_output_tokens)
    return ask_flash(prompt, user_name, user_id=user_id, temperature=temperature, max_output_tokens=max_output_tokens)


def summarize_tech_news(symbol: str, news_item: dict[str, Any], user_name: str, model: str | None = None, user_id: int | None = None) -> str:
    """一般科技新聞：強制輸出情緒分數與 Hashtag"""
    title = news_item.get("title", "")
    desc = news_item.get("description", "")
    url = news_item.get("url", "")
    
    prompt = f"""
請幫 {user_name} 總結這篇關於 {symbol} 的科技/趨勢新聞。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 全程使用繁體中文。
2. 聚焦於該技術/事件對產業未來護城河、競爭力或資本支出的影響。
3. 輸出必須長串且完整，細節講透徹，絕對禁止斷句。
4. 請按以下格式輸出：

【🚀 科技前沿情報：{symbol}】
🌡️ 情緒分數：[1-10分，1為極度悲觀，10為極度樂觀]
🏷️ 智能標籤：[給予3個精準的Hashtag，例如 #AI伺服器 #資本支出擴大 #利空出盡]
📝 核心大綱：[用精煉的一句話總結重點]
💡 深度觀點：[長篇深度分析，評估對科技產業鏈的上下游影響與潛在投資機會，並包含量價趨勢與支撐壓力觀察]
🔗 原文：{url}
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=1500)


def summarize_earnings_report(symbol: str, news_item: dict[str, Any], user_name: str, model: str | None = None, user_id: int | None = None) -> str:
    """財報專用：強制提取 EPS、營收與未來指引(Guidance)"""
    title = news_item.get("title", "")
    desc = news_item.get("description", "")
    url = news_item.get("url", "")
    
    prompt = f"""
{user_name}，這是 {symbol} 的最新財報/業績新聞。
標題：{title}
摘要：{desc}

【嚴格要求】
1. 全程使用繁體中文。
2. 科技股極度看重財測(Guidance)，請務必提取以下數據，若新聞未提及請寫「新聞未揭露」。
3. 輸出必須長串且完整，細節講透徹，絕對禁止斷句。
4. 請按以下格式輸出：

【🔥 財報快訊：{symbol}】
💰 營收 (Revenue)：[實際] vs [預期]
📈 獲利 (EPS)：[實際] vs [預期]
🚀 未來指引 (Guidance)：[上調 / 下調 / 持平，並簡述理由]
🤖 趨勢亮點：[針對管理層對 AI、新技術、核能採用或資本支出的發言進行長篇總結]
⚖️ 戰術評估：[深度分析這份財報對股價及同業板塊的可能催化方向，包含斐波那契位置參考]
🔗 原文：{url}
"""
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.2, max_output_tokens=2000)


def get_market_tactical_comment(
macro_text: str, portfolio: dict[str, float], user_name: str, user_id: int | None = None, model: str | None = None) -> str:
    pl_pct = float(portfolio.get("pl_pct", 0.0))
    pl_val = float(portfolio.get("pl_val", 0.0))
    prompt = f"""
以下是目前大盤、商品與風險資產即時數據：
{macro_text}

{user_name} 目前帳戶總損益：{pl_pct:.2f}% ({pl_val:.2f} USD)

請做一段交易副官式戰術評語。
請以精簡段落輸出，避免冗長，重點突顯量價關係與風險判斷。
包含：
1. 市場情緒與趨勢（短中長期展望）
2. VIX 與風險資產的連動解讀
3. 具體的交易戰術建議（追價、分批、或等待）
""".strip()
    return ask_model(prompt, user_name, model=model, temperature=0.5, max_output_tokens=1000)


def infer_related_news_terms(symbol: str, user_name: str, *, user_id: int | None = None) -> list[str]:
    prompt = f"""
請針對以下股票代號列出最重要的相關公司、產品、服務或生態圈關鍵詞，並只輸出 3 到 5 個關鍵詞，使用英文或常見標的名稱。
股票代號：{symbol}

輸出格式：僅用逗號分隔，不要加其他文字。
""".strip()
    result = ask_flash(prompt, user_name, user_id=user_id, temperature=0.4, max_output_tokens=200)
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

    holding_info = "目前尚未持有該標的。"
    if user_holdings and symbol in user_holdings:
        position = user_holdings[symbol]
        holding_info = (
            f"持股狀態：持有 {position.get('shares', 0):.2f} 股，平均成本 ${position.get('avg_cost', 0):.2f}。"
        )

    prompt = f"""
【報告產生時間：{current_time}】
{user_name} 詢問標的：{symbol}
{user_name} 的問題：{query}

{holding_info}

市場快照：
- 現價：{snapshot.get('price', 'N/A')}
- 今日漲跌：{snapshot.get('diff', 'N/A')} ({snapshot.get('pct', 'N/A')}%)
- 20 日支撐參考：{snapshot.get('support', 'N/A')}
- 20 日壓力參考：{snapshot.get('resistance', 'N/A')}
- 3個月區間高點：{snapshot.get('range_high_3mo', 'N/A')}
- 3個月區間低點：{snapshot.get('range_low_3mo', 'N/A')}
- 趨勢狀態：{snapshot.get('trend_note', 'N/A')}
- 量能狀態：{snapshot.get('volume_note', 'N/A')}

近期新聞：
{news_text}

請給予「極度深度」的戰術分析，語氣可以更有特色與洞察力，不要過於制式。
【要求】
1. 不要限制字數，請盡可能詳細且完整地說明所有細節，將話講完，絕對不要斷句。
2. 包含：
   - 技術面詳細觀察：裸 K、趨勢、成交量
   - 斐波那契分析：僅聚焦 0.382、0.618、1.618 三個核心位置，並說明目前位置的戰略意義。
   - 催化劑深度分析：新聞、財報、產業趨勢
   - 短、中、長期展望分析
   - 風險評估與具體戰術建議
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=3000)


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
    for symbol in symbols:
        data = fundamentals_map[symbol]
        holding_note = ""
        if symbol in holdings:
            position = holdings[symbol]
            holding_note = f"使用者持有 {symbol} {position.get('shares', 0):.2f} 股，成本 ${position.get('avg_cost', 0):.2f}。"
        news_items = news_map.get(symbol, [])
        news_text = "\n".join(
            f"- {n.get('title','')} ({n.get('source','Unknown')}) {n.get('url','')}"
            for n in news_items[:2]
        ) or "- 無可用新聞。"

        summary_lines.append(
            f"{symbol} - {data.get('company_name', symbol)}\n"
            f"現價：{data.get('current_price', 'N/A')}，市值：{data.get('market_cap', 'N/A')}\n"
            f"EPS：{data.get('trailing_eps', 'N/A')} / {data.get('forward_eps', 'N/A')}，"
            f"P/E：{data.get('trailing_pe', 'N/A')} / {data.get('forward_pe', 'N/A')}\n"
            f"TTM 營收：{data.get('revenue_ttm', 'N/A')}，TTM 淨利：{data.get('net_income', 'N/A')}\n"
            f"毛利率：{data.get('gross_margin', 'N/A')}，淨利率：{data.get('profit_margin', 'N/A')}\n"
            f"最新季：{data.get('latest_quarter', 'N/A')}，EPS：{data.get('latest_quarter_eps', 'N/A')}，營收：{data.get('latest_quarter_revenue', 'N/A')}\n"
            f"{holding_note}\n"
            f"最新消息：\n{news_text}"
        )
    prompt = f"""
【報告產生時間：{current_time}】
{user_name} 你好。
請你作為專業的美股交易副官，根據以下財務數據與最新消息比較這幾家公司：{', '.join(symbols)}。

"""
    prompt += "\n\n".join(summary_lines)
    prompt += "\n\n請給我極度深度的分析，將所有細節講清楚，絕對不要斷句：\n"
    prompt += (
        "1. 哪支股票整體財務健康較佳，並說明具體數據支持的理由。\n"
        "2. 依據成長性、獲利能力、估值合理性與現金流/現金地位，做出詳細排序與解釋。\n"
        "3. 根據最新新聞，深入分析對每家公司最重要的利多/利空因素與未來催化劑。\n"
        "4. 若使用者已有持股，請考量其成本價與當前風險，給出具體的交易策略方向（加碼、減碼、觀望）。\n"
        "5. 列出最值得投資的標的排序。\n"
        "6. 回應必須詳盡且專業，展現強大的數據洞察力。"
    )
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=3000)


def chat_with_kevin(
query: str, user_name: str, context_symbol: str | None = None, snapshot: dict[str, Any] | None = None, user_id: int | None = None, model: str | None = None) -> str:
    if context_symbol:
        prompt = f"""
{user_name} 的自然語言問題：{query}
偵測到股票代號：{context_symbol}
市場快照：{snapshot or {}}

請轉為個股「簡述模式」。
【要求】
1. 使用大綱或條列式簡述。
2. 包含短中長期展望與核心技術位（含斐波那契 0.382、0.618、1.618）。
3. 內容精確，不需要過度展開，但要將話講完。
""".strip()
        return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.38, max_output_tokens=1500)

    prompt = f"""
{user_name} 說：{query}
請以專業分析師／顧問身份回答。如果這是一般問題，請直接以最適合的角度給出清晰、專業且務實的回覆，不必強行套用交易術語。
回答要有特色，語氣可以更有個性與觀點，但保持精準。
【要求】
1. 若問題與投資或金融相關，可提供有洞察力的觀察與分析；若問題屬於其他領域，請用通用的專業分析方式回答。
2. 不要加入無謂的風險提醒或制式結語，除非題目需要。
3. 保持簡練且完整，必要時可用條列式呈現。
""".strip()
    return ask_model(prompt, user_name, model=model, temperature=0.5, max_output_tokens=1000)

