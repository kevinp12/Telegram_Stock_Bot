"""brain.py
Gemini Brain：只負責和 Gemini API 溝通。
- 基本對話使用 Flash
- 深度分析使用 Pro
- 自動 fallback
- 可列出可用模型
"""

from __future__ import annotations

import logging
import re
import time
import gc
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from google import genai
from google.genai import types

import database
from config import BASE_DIR, DAILY_TOKEN_LIMIT, FLASH_FALLBACK_MODELS, GEMINI_API_KEY, GEMINI_AUDIT_LOG_PATH, PRO_FALLBACK_MODELS


@dataclass
class BrainStats:
    success: int = 0
    fail: int = 0
    total_tokens: int = 0
    last_model: str = "N/A"
    last_mode: str = "N/A"
    last_error: str = "N/A"
    available_models: list[str] = field(default_factory=list)
    alert_callback: Callable[[str], None] | None = None


stats = BrainStats()
_client: genai.Client | None = None
_last_alert_percent = 0

# Module A: 3-Day Lightweight Persistent Memory (SQLite + small in-process fallback)
user_memory: dict[int, dict] = {}
MEMORY_TIMEOUT = 3 * 24 * 60 * 60  # 3 天 (秒)
MEMORY_MAX_TURNS = 5  # 最多保留最近 5 輪（user+model 約 10 則），進一步降低 context 與 RAM 壓力
MEMORY_MAX_USER_CHARS = 900
MEMORY_MAX_MODEL_CHARS = 1400

# 對話難度 -> 建議輸出 token（可依機器資源調整）
TOKEN_BUDGET_LIGHT = 1000
TOKEN_BUDGET_MEDIUM = 2500
TOKEN_BUDGET_HEAVY = 5000


def _clip_memory_text(text: str, role: str) -> str:
    """壓縮單則記憶內容，保留語意但避免佔用過多 context/RAM。"""
    compact = " ".join((text or "").strip().split())
    limit = MEMORY_MAX_MODEL_CHARS if role == "model" else MEMORY_MAX_USER_CHARS
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def classify_dialogue_complexity(prompt: str, history_len: int = 0) -> tuple[str, int]:
    """依問題長度/關鍵字/上下文量，回傳（輕度|中度|重度, 建議 max_output_tokens）。"""
    text = (prompt or "").strip().lower()
    length = len(text)

    heavy_keywords = [
        "深度", "完整", "比較", "策略", "回測", "蒙地卡羅", "財報", "估值", "風險", "情境", "步驟", "多因子",
        "comprehensive", "deep", "scenario", "valuation", "backtest", "portfolio",
        "/bt", "/backtest", "/sim", "/fin", "fin compare", "/ask",
    ]
    medium_keywords = [
        "分析", "原因", "影響", "看法", "重點", "建議", "summary", "outlook", "news",
    ]
    command_heavy_keywords = ["/bt", "/backtest", "/sim", "/fin", "fin compare", "/ask"]

    # 指令優先：深度研究/策略指令直接視為重度
    if any(k in text for k in command_heavy_keywords):
        return "重度", TOKEN_BUDGET_HEAVY

    score = 0
    if length > 280:
        score += 2
    elif length > 120:
        score += 1

    # 降低歷史長度干擾，避免一般長對話被誤判成重度
    if history_len >= 10:
        score += 1

    if any(k in text for k in heavy_keywords):
        score += 3
    elif any(k in text for k in medium_keywords):
        score += 1

    if score >= 4:
        return "重度", TOKEN_BUDGET_HEAVY
    if score >= 2:
        return "中度", TOKEN_BUDGET_MEDIUM
    return "輕度", TOKEN_BUDGET_LIGHT


def _prune_user_memory(now: float | None = None) -> None:
    """移除超過 TTL 的使用者記憶，避免長時間運作時記憶字典持續膨脹。"""
    current = now or time.time()
    expired = [uid for uid, item in user_memory.items() if current - float(item.get("timestamp", 0) or 0) > MEMORY_TIMEOUT]
    for uid in expired:
        user_memory.pop(uid, None)
    try:
        database.prune_chat_memory()
    except Exception as exc:
        logging.debug("[Brain] prune DB chat memory skipped: %s", exc)


def clear_user_memory(user_id: int | None = None) -> None:
    """清除單一使用者或全部自然對話記憶（RAM fallback + DB）。"""
    if user_id is None:
        user_memory.clear()
    else:
        user_memory.pop(int(user_id), None)
    try:
        database.clear_chat_memory(user_id)
    except Exception as exc:
        logging.debug("[Brain] clear DB chat memory skipped: %s", exc)


def _load_memory_history(user_id_int: int, now: float) -> list[dict[str, str]]:
    """優先從 DB 載入 3 天記憶；DB 不可用時 fallback 到 RAM。"""
    try:
        rows = database.get_chat_memory(user_id_int, limit=MEMORY_MAX_TURNS * 2)
        return [
            {"role": str(row.get("role", "user")), "text": _clip_memory_text(str(row.get("text", "")), str(row.get("role", "user")))}
            for row in rows
            if str(row.get("text", "")).strip()
        ]
    except Exception as exc:
        logging.debug("[Brain] load DB chat memory fallback to RAM: %s", exc)
        if user_id_int not in user_memory or (now - user_memory[user_id_int].get("timestamp", 0) > MEMORY_TIMEOUT):
            user_memory[user_id_int] = {"timestamp": now, "history": []}
        user_memory[user_id_int]["timestamp"] = now
        raw_history = user_memory[user_id_int].get("history", [])
        return [
            {"role": h.get("role", "user"), "text": _clip_memory_text(str(h.get("text", "")), str(h.get("role", "user")))}
            for h in raw_history[-MEMORY_MAX_TURNS * 2 :]
            if str(h.get("text", "")).strip()
        ]


def _save_memory_history(user_id_int: int, history: list[dict[str, str]]) -> None:
    """同步精簡後記憶到 DB；若 DB 不可用則寫 RAM fallback。"""
    trimmed = history[-MEMORY_MAX_TURNS * 2 :]
    try:
        database.replace_chat_memory(user_id_int, trimmed, max_rows=MEMORY_MAX_TURNS * 2)
    except Exception as exc:
        logging.debug("[Brain] save DB chat memory fallback to RAM: %s", exc)
        user_memory[user_id_int] = {"timestamp": time.time(), "history": trimmed}


def is_quota_exhausted_error(message: str) -> bool:
    """判斷是否為 Gemini 配額耗盡/資源不足類錯誤。"""
    msg = (message or "").lower()
    return (
        "429" in msg
        or "resourceexhausted" in msg
        or "resource_exhausted" in msg
        or "quota exceeded" in msg
        or "exceeded your current quota" in msg
    )


def format_status_error(message: str, max_len: int = 120) -> str:
    """將錯誤訊息格式化為狀態頁可讀短訊，避免洗版。"""
    raw = (message or "").replace("\n", " ").strip()
    if not raw or raw == "N/A":
        return "N/A"
    if is_quota_exhausted_error(raw):
        return "429 RESOURCE_EXHAUSTED（配額不足，請檢查 billing / rate limit）"

    compact = " ".join(raw.split())
    if len(compact) > max_len:
        compact = compact[: max_len - 1].rstrip() + "…"
    return compact


def extract_status_error_code(message: str) -> str:
    """狀態頁只顯示錯誤碼數字（例如 429 / 404）；無錯誤時回傳 0。"""
    raw = (message or "").strip()
    if not raw or raw == "N/A":
        return "0"

    if is_quota_exhausted_error(raw):
        return "429"

    match = re.search(r"\b([1-5]\d{2})\b", raw)
    if match:
        return match.group(1)
    return "0"


def get_next_fallback_model(current_model: str, chain: Iterable[str]) -> str:
    """依目前模型回傳下一順位 fallback；若無法判定則回傳首個候選。"""
    normalized_chain = [normalize_model_name(m) for m in chain if normalize_model_name(m)]
    if not normalized_chain:
        return "未設定"

    current = normalize_model_name(current_model)
    if current in normalized_chain:
        idx = normalized_chain.index(current)
        if idx + 1 < len(normalized_chain):
            return normalized_chain[idx + 1]
        return "無（已是最後順位）"

    # 若目前模型不在該鏈上（例如 flash-latest），嘗試用關鍵字猜測鏈別，回傳首選備援
    return normalized_chain[0]

AUDIT_LOG_PATH: Path = GEMINI_AUDIT_LOG_PATH
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _append_audit_line(line: str) -> None:
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    except Exception as exc:
        logging.warning("[Brain] 無法寫入 Gemini audit log: %s", exc)


def _format_usage(response: object) -> dict[str, int | None]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return {"prompt": None, "output": None, "total": None, "lost": None}

    prompt_tokens = getattr(usage, "prompt_token_count", None)
    output_tokens = getattr(usage, "output_token_count", None)
    total_tokens = getattr(usage, "total_token_count", None)
    lost_tokens = None
    if total_tokens is not None and prompt_tokens is not None and output_tokens is not None:
        lost_tokens = total_tokens - prompt_tokens - output_tokens
        if lost_tokens < 0:
            lost_tokens = None
    return {
        "prompt": prompt_tokens,
        "output": output_tokens,
        "total": total_tokens,
        "lost": lost_tokens,
    }


def _audit_gemini_entry(
    *,
    user_id: int | None,
    model: str,
    success: bool,
    response_text: str | None = None,
    usage_info: dict[str, int | None] | None = None,
    error: str | None = None,
    max_output_tokens: int | None = None,
    urls: list[str] | None = None,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "✅ SUCCESS" if success else "❌ FAILED"

    usage_info = usage_info or {"prompt": 0, "output": 0, "total": 0, "lost": 0}
    p = usage_info.get("prompt") or 0
    o = usage_info.get("output") or 0
    t = usage_info.get("total") or 0

    line = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    line += f"🕒 {timestamp} | {status} | User:{user_id or 0} | Model:{model}\n"
    line += f"📊 Tokens: Prompt:{p} | Output:{o} | Total:{t}\n"

    if urls:
        line += f"🌐 Research URLs:\n"
        for url in urls:
            line += f"   - {url}\n"

    if error:
        line += f"⚠️ Error: {error}\n"

    if response_text:
        # 僅保留開頭一段預覽，避免 Log 爆炸
        preview = response_text.replace("\n", " ")[:200]
        line += f"📝 Response Preview: {preview}...\n"

    _append_audit_line(line)

    if success:
        database.record_token_log(user_id, model, p, o, t, urls)


def log_gemini_error(user_id: int | None, model: str, exc: Exception, urls: list[str] | None = None) -> None:
    msg = str(exc).replace("\n", " ").strip()
    _audit_gemini_entry(
        user_id=user_id,
        model=model,
        success=False,
        response_text=None,
        usage_info=None,
        error=msg[:500],
        urls=urls,
    )


def log_gemini_success(
    user_id: int | None, model: str, response: object, response_text: str | None, max_output_tokens: int, urls: list[str] | None = None
) -> None:
    usage_info = _format_usage(response)
    _audit_gemini_entry(
        user_id=user_id,
        model=model,
        success=True,
        response_text=response_text,
        usage_info=usage_info,
        max_output_tokens=max_output_tokens,
        urls=urls,
    )


def get_client() -> genai.Client:
    global _client
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is empty. 請檢查 .env")
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def normalize_model_name(name: str) -> str:
    return (name or "").replace("models/", "").strip()


def list_available_models(force_refresh: bool = False) -> list[str]:
    """列出目前 API key 可用且支援 generateContent 的 Gemini 模型。"""
    if stats.available_models and not force_refresh:
        return stats.available_models

    models: list[str] = []
    try:
        client = get_client()
        for m in client.models.list():
            # 過濾掉不支援生成內容的模型 (例如只有 TTS 的模型)
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" not in methods:
                continue

            name = normalize_model_name(getattr(m, "name", ""))
            if "gemini" in name.lower():
                models.append(name)
        # 去重但保留順序
        seen = set()
        stats.available_models = [m for m in models if not (m in seen or seen.add(m))]
    except Exception as exc:
        stats.last_error = str(exc)[:500]
        logging.warning("[Brain] ListModels failed: %s", exc)
        stats.available_models = []
    return stats.available_models


def filter_available(chain: Iterable[str]) -> list[str]:
    """用 ListModels 結果過濾模型。若 ListModels 失敗，仍照原清單嘗試。"""
    raw_chain = [normalize_model_name(m) for m in chain if normalize_model_name(m)]
    available = list_available_models()
    if not available:
        return raw_chain

    filtered = [m for m in raw_chain if m in available]
    # 如果使用者指定的模型不在清單，但 Google 有其他 Gemini 模型，補上可用模型。
    for m in available:
        if m not in filtered and ("flash" in m or "pro" in m):
            filtered.append(m)
    return filtered or raw_chain


def check_quota_alert(used_tokens: int):
    """檢查流量是否過低並發送警報。"""
    global _last_alert_percent
    percent = (used_tokens / DAILY_TOKEN_LIMIT) * 100

    # 在 80%, 90%, 100% 時提醒
    for threshold in [100, 90, 80]:
        if percent >= threshold > _last_alert_percent:
            _last_alert_percent = threshold
            msg = f"⚠️ 【流量預警】\n當日 Token 已使用：{used_tokens:,}\n每日配額：{DAILY_TOKEN_LIMIT:,}\n目前進度：{percent:.1f}%"
            if stats.alert_callback:
                stats.alert_callback(msg)
            break


def generate_text(
    prompt: str,
    *,
    system_instruction: str = "",
    mode: str = "flash",
    temperature: float = 0.45,
    max_output_tokens: int = 1200,
    priority_model: str | None = None,
    user_id: int | None = None,
    urls: list[str] | None = None,
) -> str:
    """呼叫 Gemini 產生文字，支援 3 天輕量記憶與 context 容錯機制。"""
    # 每次生成前先觸發 GC，降低長時間運作下的記憶體碎片/殘留
    gc.collect()
    client = get_client()

    # 若未來切換到 stateful chats.create()，請使用隨機 session_id 避免 collision
    _session_id_hint = f"session_{uuid.uuid4().hex[:8]}"

    # Module A: 歷史紀錄管理 (3-Day TTL + 輕量上限)
    now = time.time()
    _prune_user_memory(now)
    history = []
    if user_id is not None:
        user_id_int = int(user_id)
        history = _load_memory_history(user_id_int, now)

    if mode.lower() == "pro":
        chain = PRO_FALLBACK_MODELS
    else:
        chain = FLASH_FALLBACK_MODELS

    if priority_model:
        clean_priority = normalize_model_name(priority_model)
        chain = [clean_priority] + [m for m in chain if normalize_model_name(m) != clean_priority]

    model_chain = filter_available(chain)
    last_exc = None

    # 若傳入 <=0，啟用自動分級 token（輕/中/重）
    complexity, suggested_tokens = classify_dialogue_complexity(prompt, history_len=len(history))
    effective_max_tokens = max_output_tokens if max_output_tokens and max_output_tokens > 0 else suggested_tokens

    try:
        for model in model_chain:
            clean_model = normalize_model_name(model)
            if not clean_model:
                continue

            # 安全網重試機制：若 Context 過長則移除最舊對話後重試
            current_history = list(history)
            while True:
                try:
                    # 組合 Content 陣列
                    contents = []
                    for h in current_history:
                        contents.append(types.Content(role=h["role"], parts=[types.Part(text=h["text"])]))
                    contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

                    logging.info(
                        "🧠 [Brain] mode=%s model=%s history_len=%d complexity=%s max_tokens=%d",
                        mode,
                        clean_model,
                        len(current_history),
                        complexity,
                        effective_max_tokens,
                    )
                    response = client.models.generate_content(
                        model=clean_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction or None,
                            temperature=temperature,
                            max_output_tokens=effective_max_tokens,
                        ),
                    )
                    text = getattr(response, "text", None)
                    if not text:
                        raise RuntimeError("Gemini returned empty text")

                    # 成功後更新持久記憶
                    if user_id is not None:
                        user_id_int = int(user_id)
                        updated_history = current_history + [
                            {"role": "user", "text": _clip_memory_text(prompt, "user")},
                            {"role": "model", "text": _clip_memory_text(text.strip(), "model")},
                        ]
                        _save_memory_history(user_id_int, updated_history)

                    # 追蹤流量
                    usage = getattr(response, "usage_metadata", None)
                    if usage:
                        token_count = usage.total_token_count
                        if user_id is not None:
                            used_today = database.update_daily_tokens(user_id, token_count)
                            stats.total_tokens = used_today
                            check_quota_alert(used_today)
                        else:
                            used_today = 0

                    stats.success += 1
                    stats.last_model = clean_model
                    stats.last_mode = mode
                    stats.last_error = "N/A"
                    log_gemini_success(user_id, clean_model, response, text, effective_max_tokens, urls=urls)
                    return text.strip()

                except Exception as exc:
                    msg = str(exc).lower()
                    # API Token 防爆機制：若報錯且有歷史紀錄，移除最舊的一組 (User+Model) 後重試
                    if ("token" in msg or "length" in msg or "400" in msg or "invalid argument" in msg) and current_history:
                        logging.warning("⚠️ [Brain] Context 可能過長，移除最舊歷史後重試 (%s)", clean_model)
                        if len(current_history) >= 2:
                            current_history = current_history[2:]
                        else:
                            current_history = []
                        continue

                    last_exc = exc
                    stats.last_error = str(exc)[:500]
                    log_gemini_error(user_id, clean_model, exc, urls=urls)

                    if is_quota_exhausted_error(msg):
                        if stats.alert_callback:
                            used_today, _ = database.get_daily_tokens(user_id) if user_id else (0, 0)
                            stats.alert_callback(f"❌ 【流量耗盡】\nAPI 回傳 429 錯誤。\n目前今日已使用：{used_today:,}")

                    logging.warning("⚠️ [Brain] %s failed: %s", clean_model, msg[:300])
                    break  # 跳出 while True，嘗試下一個 model 備援

        stats.fail += 1
        reason = str(last_exc)[:300] if last_exc else "unknown error"
        return f"❌ 顧問大腦連線失敗。原因：{reason}"
    finally:
        # 每次生成後立即回收大型暫存物件
        gc.collect()


def ping(user_id: int | None = None) -> bool:
    result = generate_text(
        "請只回覆 OK",
        mode="flash",
        temperature=0,
        max_output_tokens=10,
        user_id=user_id,
    )
    return "OK" in result.upper()


def get_status_text(user_id: int) -> str:
    available = list_available_models()
    flash_ready = [m for m in FLASH_FALLBACK_MODELS if normalize_model_name(m) in available]
    pro_ready = [m for m in PRO_FALLBACK_MODELS if normalize_model_name(m) in available]

    current_model = stats.last_model
    if current_model == "N/A":
        if flash_ready:
            current_model = f"{flash_ready[0]} (首選候選)"
        elif pro_ready:
            current_model = f"{pro_ready[0]} (首選候選)"
        elif available:
            current_model = f"{available[0]} (可用模型)"

    used_today, _ = database.get_daily_tokens(user_id)
    percent = (used_today / DAILY_TOKEN_LIMIT) * 100

    t_stats = database.get_token_stats(user_id)

    status_error = extract_status_error_code(stats.last_error)

    flash_next = get_next_fallback_model(current_model, FLASH_FALLBACK_MODELS)
    pro_next = get_next_fallback_model(current_model, PRO_FALLBACK_MODELS)

    lines = [
        f"• 今日流量: {used_today:,} / {DAILY_TOKEN_LIMIT:,} ({percent:.1f}%)",
        f"• 消耗統計: Min:{t_stats['min']:.0f} | Max:{t_stats['max']:.0f} | Avg:{t_stats['avg']:.1f}",
        f"• 目前使用模型: `{current_model}`",
        f"• Flash 下一個模型: {flash_next}",
        f"• Pro 下一個模型: {pro_next}",
        f"• 成功調用: {stats.success} 次",
        f"• 最近錯誤: {status_error}",
    ]
    return "\n".join(lines)
