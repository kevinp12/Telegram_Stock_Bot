"""ai_core.py
AI 思考層：決定美股顧問如何分析與回覆。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import brain

SYSTEM_PROMPT_TEMPLATE = """
你是一位冷緊、精準的美股顧問「美股顧問」，是 {user_name} 的私人投資副官。
同時，你也可以擔任廣泛的分析師與專業助理，回答非交易、非股票的問題。

【當前時間】
現在是西元 {current_time}。請務必以此時間點為基準進行分析。

【核心守則】
1. 必須全程使用「繁體中文」回覆，除了原文網址與股票代號外，禁止出現簡體中文或其他語言。
2. 稱呼使用者為 {user_name}。
3. 回覆風格：專業、冷靜、精準，帶有特色與觀點。對交易問題可用交易副官口吻；對其他問題可用資深分析師或專業助理口吻。
4. 不保證獲利，不給絕對買賣指令；用「觀察、偏多、偏空、風險、條件」表達交易相關建議。
5. 優先提供：新聞摘要、催化劑、量價關係、裸 K 結構、支撐壓力、風險提醒。若問題不是交易相關，則以最適當的專業角度給出清晰、實用的分析或答案。
6. 所有合適的分析盡量包含「短、中、長期」三個維度；若問題不適用此框架，請改用最合理的分析維度並說明。
7. 必須包含「斐波那契分析」的數值判斷，僅使用 0.382、0.618、1.618 這三個核心位置，並根據提供的區間高低點進行位置解讀；若未提供區間高低點或問題非技術分析，則可省略該項。
8. 回答要有特色，不要制式或冗長廢話。請直接、清楚、具洞察力地回應問題。
9. 如果是新聞相關內容，務必提供原文網址並把摘要整理成新聞稿風格，至少要有一段清楚的新聞摘要。
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
    return text.replace("_", " ").replace("*", " ").strip()


def ask_flash(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.45, max_output_tokens: int = 2000) -> str:
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


def ask_pro(prompt: str, user_name: str, *, user_id: int | None = None, temperature: float = 0.35, max_output_tokens: int = 3000) -> str:
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


def get_market_tactical_comment(macro_text: str, portfolio: dict[str, float], user_name: str, user_id: int | None = None, model: str | None = None) -> str:
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


def analyze_news(symbol: str, news_items: list[dict[str, Any]], user_name: str, user_id: int | None = None) -> str:
    if not news_items:
        return f"📌 {symbol}\n⚠️ 暫無最新新聞或採集超時。"
    news_text = "\n".join(
        f"{idx+1}. 標題：{n.get('title','')}\n摘要：{n.get('description','')}\n來源：{n.get('source','')}\n原文連結：{n.get('url','')}"
        for idx, n in enumerate(news_items)
    )
    prompt = f"""
請針對 {symbol} 的最新新聞替 {user_name} 做新聞稿式深度解讀：
{news_text}

請詳細輸出：
1. 新聞重點深度摘要，保持新聞稿風格，並附上原文網址。
2. 對股價的短、中、長期可能影響。
3. 市場情緒與投資者心理判斷。
4. 基於斐波那契 0.382、0.618、1.618 位置的潛在支撐壓力分析。
5. 具體的戰術觀察與待觀察訊號。
""".strip()
    analysis = ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=1500)
    return f"📌 {symbol}\n{analysis}"


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
1. 不要限制字數，請盡可能詳細且完整地說明所有細節，將話講完。
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
{user_name} 你好。
請你作為專業的美股交易副官，根據以下財務數據與最新消息比較這幾家公司：{', '.join(symbols)}。

"""
    prompt += "\n\n".join(summary_lines)
    prompt += "\n\n請給我：\n"
    prompt += (
        "1. 哪支股票整體財務健康較佳，並說明主要理由。\n"
        "2. 依據成長性、獲利能力、估值合理性與現金流/現金地位，做出排序。\n"
        "3. 根據最新新聞，指出對每家公司最重要的利多/利空因素。\n"
        "4. 若使用者已有持股，請考量成本價與持股風險，並給出交易策略方向。\n"
        "5. 若這次比較 2~3 支股票，請直接列出最健康與次健康標的。\n"
        "6. 用簡潔的條列式結構輸出，不要用太長冗言。"
    )
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.35, max_output_tokens=2000)


def summarize_news_with_format(
    category: str,
    symbol: str,
    news_item: dict[str, Any],
    user_name: str,
    watchlist: list[str] | None = None,
    user_holdings: dict[str, Any] | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> str:
    """依照使用者要求格式化單一新聞：[Tag] [Importance] [Outline] [URL]"""
    title = news_item.get("title", "")
    desc = news_item.get("description", "")
    url = news_item.get("url", "")
    source = news_item.get("source", "Unknown")
    watchlist = watchlist or []
    watchlist_text = (
        f"請根據以下觀察清單判斷是否對其股票有影響：{', '.join(watchlist)}。若無直接關聯，請不要列出無關股票。"
        if watchlist
        else "目前沒有觀察清單，不需要列出多餘的影響標的。"
    )
    holding_text = "使用者目前無此標的持股資訊。"
    if user_holdings and symbol in user_holdings:
        position = user_holdings[symbol]
        holding_text = (
            f"使用者持有 {symbol}：{position.get('shares', 0):.2f} 股，平均成本 ${position.get('avg_cost', 0):.2f}。"
        )

    prompt = f"""
請幫 {user_name} 總結這篇新聞。
類別：{category}
標的：{symbol}
標題：{title}
摘要：{desc}
來源：{source}

{holding_text}
{watchlist_text}

【嚴格要求】
1. 除了原文網址與股票代號外，所有內容必須使用「繁體中文」。
2. 請直接輸出推播稿式新聞摘要，避免空洞廢話，並確實呈現原文網址。
3. 如果可以，請將新聞內容濃縮成最重要的 1-2 個觀點。
4. 若有可公開新聞重點、時間、來源、影響，請以新聞稿式方式補充說明。
5. 可能影響標的僅列出最重要的 1-2 檔，且只列出與觀察清單或持股直接相關的股票。若無直接關聯，請寫「無相關標的」。
6. 請以使用者的交易策略角度提供觀點，評估多空、風險、支撐壓力與後續觀察重點。
7. 若此新聞與美國宏觀、聯準會或市場動向相關，請補充以下指標：
   - 增長趨勢：YoY、QoQ、MoM、YTD 的定義與最近公布數值或標準判準。
   - 獲利與估值：EPS、P/E、Guidance 的意義與一般標準水準。
   - 期權情緒：POP、IV、Put/Call ratio 的常見標準值與市場情緒解讀。
   若新聞未提供具體數據，也請直接說明這些指標的標準值與目前應如何解讀。
8. 儘量使用「最近公布」或「即將公布」的資料來敘述，若無法精準取得也請標示為一般市場觀察。

請輸出以下格式：
【{category}：{symbol}】
重要程度：[請給 1~5 顆星，例如 ★★★☆☆]
大綱：[請以要點列出新聞核心內容]
內文整理：[以段落整理新聞內容與影響]
觀點：[提供專業視角與關鍵判斷]
可能影響標的：[列出對你的持股或觀察清單可能有影響的股票，最多 1-2 檔]
原文連結：{url}
""".strip()
    return ask_model(prompt, user_name, model=model, user_id=user_id, temperature=0.3, max_output_tokens=800)


def chat_with_kevin(query: str, user_name: str, context_symbol: str | None = None, snapshot: dict[str, Any] | None = None, user_id: int | None = None, model: str | None = None) -> str:
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

