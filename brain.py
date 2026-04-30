"""brain.py
Gemini Brain：只負責和 Gemini API 溝通。
- 基本對話使用 Flash
- 深度分析使用 Pro
- 自動 fallback
- 可列出可用模型
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Callable

from google import genai
from google.genai import types

import database
from config import (
    GEMINI_API_KEY,
    FLASH_FALLBACK_MODELS,
    PRO_FALLBACK_MODELS,
    DAILY_TOKEN_LIMIT,
)


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
    """列出目前 API key 可用的 Gemini 模型。"""
    if stats.available_models and not force_refresh:
        return stats.available_models

    models: list[str] = []
    try:
        client = get_client()
        for m in client.models.list():
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
) -> str:
    """呼叫 Gemini 產生文字。"""
    client = get_client()

    if mode.lower() == "pro":
        chain = PRO_FALLBACK_MODELS
    else:
        chain = FLASH_FALLBACK_MODELS

    if priority_model:
        clean_priority = normalize_model_name(priority_model)
        chain = [clean_priority] + [m for m in chain if normalize_model_name(m) != clean_priority]

    model_chain = filter_available(chain)
    last_exc = None

    for model in model_chain:
        clean_model = normalize_model_name(model)
        if not clean_model:
            continue
        try:
            logging.info("🧠 [Brain] mode=%s model=%s", mode, clean_model)
            response = client.models.generate_content(
                model=clean_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction or None,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError("Gemini returned empty text")

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
            return text.strip()
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            stats.last_error = msg[:500]
            
            # 若為配額耗盡錯誤
            if "429" in msg or "ResourceExhausted" in msg:
                if stats.alert_callback:
                    if user_id is not None:
                        used_today, _ = database.get_daily_tokens(user_id)
                    else:
                        used_today = 0
                    stats.alert_callback(f"❌ 【流量耗盡】\nAPI 回傳 429 錯誤。\n目前今日已使用：{used_today:,}\n請檢查 GCP 控制台或調整配額上限。")

            logging.warning("⚠️ [Brain] %s failed: %s", clean_model, msg[:300])
            continue

    stats.fail += 1
    reason = str(last_exc)[:300] if last_exc else "unknown error"
    return f"❌ 顧問大腦連線失敗。原因：{reason}"


def ping() -> bool:
    result = generate_text(
        "請只回覆 OK",
        mode="flash",
        temperature=0,
        max_output_tokens=10,
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

    return (
        f"• 今日流量: {used_today:,} / {DAILY_TOKEN_LIMIT:,} ({percent:.1f}%)\n"
        f"• 目前使用模型: `{current_model}`\n"
        f"• Flash 備援清單: {', '.join(flash_ready[:3])}\n"
        f"• Pro 備援清單: {', '.join(pro_ready[:3])}\n"
        f"• 成功調用: {stats.success} 次\n"
        f"• 最近錯誤: {stats.last_error}"
    )
