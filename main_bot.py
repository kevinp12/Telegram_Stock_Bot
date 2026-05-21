"""main_bot.py
Telegram 執行核心：指令註冊、訊息分發、開關機通報、polling。
"""

from __future__ import annotations

import matplotlib
matplotlib.use('Agg')

import logging
from logging.handlers import TimedRotatingFileHandler
import signal
import sys
import threading
import time
import gc
from collections import OrderedDict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import telebot
import sec_api
import market_api
import psutil
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telebot.apihelper import RetryAfter
except ImportError:
    RetryAfter = ApiTelegramException

import command
import database
import frame
import tech_indicators
import utils
from config import (
    AUTO_NEWS_INTERVAL_SECONDS,
    ADMIN_ID,
    GEMINI_AUDIT_LOG_PATH,
    LONG_POLLING_TIMEOUT,
    MAX_TELEGRAM_MESSAGE_LENGTH,
    POLLING_TIMEOUT,
    SNIPER_CHECK_INTERVAL,
    TELEGRAM_TOKEN,
)

# 重大新聞即時推送，最小輪詢間隔
ALERT_NEWS_INTERVAL_SECONDS = 600


def is_market_open() -> bool:
    """檢查美股是否正在交易 (09:30 - 16:00 ET)"""
    tz = ZoneInfo("America/New_York")
    now_et = datetime.now(tz)
    # 星期一到星期五 (0=Mon, 4=Fri)
    if 0 <= now_et.weekday() <= 4:
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et <= market_close
    return False


LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(message)s"
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if not root_logger.handlers:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(stream_handler)

system_log_handler = TimedRotatingFileHandler(
    filename="system.log",
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8",
)
system_log_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(system_log_handler)

# 統一由 config 模組讀取，若為空則報錯
if not TELEGRAM_TOKEN or len(TELEGRAM_TOKEN) < 10:
    logging.error("❌ 錯誤：TELEGRAM_TOKEN 未設定或格式不正確。請檢查 .env 檔案內容。")
    sys.exit(1)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True, num_threads=2)
PAGED_CACHE_MAX_ITEMS = 12
PAGED_CACHE_TTL_SECONDS = 15 * 60
PAGED_MESSAGE_CACHE: OrderedDict[str, tuple[list[str], float]] = OrderedDict()
_HEAVY_TASK_SEMAPHORE = threading.BoundedSemaphore(value=1)
_USER_HEAVY_TASK_TS: OrderedDict[tuple[int, str], float] = OrderedDict()


def add_to_paged_cache(token: str, pages: list[str]) -> None:
    """限制分頁快取上限，避免長時間運作造成記憶體累積。"""
    now_ts = time.time()
    expired = [k for k, v in PAGED_MESSAGE_CACHE.items() if now_ts - float(v[1]) > PAGED_CACHE_TTL_SECONDS]
    for k in expired:
        PAGED_MESSAGE_CACHE.pop(k, None)

    while len(PAGED_MESSAGE_CACHE) >= PAGED_CACHE_MAX_ITEMS:
        PAGED_MESSAGE_CACHE.popitem(last=False)
    PAGED_MESSAGE_CACHE[token] = (pages, now_ts)
TECH_CHART_COOLDOWN_SECONDS = 45
HEAVY_TASK_USER_COOLDOWN_SECONDS = 12
_TECH_CHART_LAST_TS: dict[tuple[int, str], float] = {}
_USER_CHART_THEME: dict[int, str] = {}
MAX_AI_CORPUS_LEN = 3000


def _truncate_ai_text(text: str, limit: int = MAX_AI_CORPUS_LEN) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit]


def _allow_user_heavy_task(user_id: int, task_name: str, cooldown_seconds: int = HEAVY_TASK_USER_COOLDOWN_SECONDS) -> tuple[bool, int]:
    """使用者級節流：防止短時間重複觸發高成本任務。"""
    now = time.time()
    key = (int(user_id), task_name)
    last_ts = _USER_HEAVY_TASK_TS.get(key, 0.0)
    remaining = int(cooldown_seconds - (now - last_ts))
    if remaining > 0:
        return False, remaining

    _USER_HEAVY_TASK_TS[key] = now
    _USER_HEAVY_TASK_TS.move_to_end(key)
    while len(_USER_HEAVY_TASK_TS) > 800:
        _USER_HEAVY_TASK_TS.popitem(last=False)
    return True, 0


def try_acquire_heavy_task(message, user_id: int, task_name: str, *, cooldown_seconds: int = HEAVY_TASK_USER_COOLDOWN_SECONDS) -> bool:
    """全域併發保護：改為排隊等待，不顯示冷卻/等待拒絕訊息。"""
    _HEAVY_TASK_SEMAPHORE.acquire(blocking=True)
    return True


def release_heavy_task() -> None:
    try:
        _HEAVY_TASK_SEMAPHORE.release()
    except Exception:
        pass
    gc.collect()


def get_user_display_name(m) -> str:
    """從 Telegram message 中提取顯示名稱。"""
    user = getattr(m, "from_user", None)
    if user:
        name = user.first_name or ""
        if user.last_name:
            name += f" {user.last_name}"
        return name or user.username or "User"
    return "User"


def get_user_id(m) -> int:
    user = getattr(m, "from_user", None)
    if user and getattr(user, "id", None) is not None:
        return int(user.id)
    return int(m.chat.id)


def normalize_loose_command_text(text: str) -> str:
    """把 ./bc、/ bc、./ sweep 這類寬鬆輸入統一成標準 /bc、/sweep 格式。"""
    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return ""

    lower = normalized.lower()

    # / bc on  -> /bc on
    if lower.startswith("/"):
        after = normalized[1:].lstrip()
        if after:
            return "/" + after

    # ./bc on / ./ bc on / .bc on -> /bc on
    dot_cmd_prefixes = ("./", ".")
    for prefix in dot_cmd_prefixes:
        if lower.startswith(prefix):
            after = normalized[len(prefix) :].lstrip()
            if after:
                return "/" + after

    return normalized


def read_hidden_log_lines(line_count: int = 40) -> list[str]:
    try:
        with open(GEMINI_AUDIT_LOG_PATH, "r", encoding="utf-8") as handle:
            lines = [line.rstrip() for handle_line in handle.readlines() if (line := handle_line.strip())]
        return lines[-line_count:]
    except FileNotFoundError:
        return []
    except Exception as exc:
        logging.warning("read hidden log failed: %s", exc)
        return []


def register_user(m) -> tuple[int, str]:
    user_id = get_user_id(m)
    display_name = get_user_display_name(m)
    username = ""
    user = getattr(m, "from_user", None)
    if user:
        username = getattr(user, "username", "") or ""
    database.add_or_update_user(user_id, display_name, username)
    return user_id, display_name


def get_username(m) -> str:
    user = getattr(m, "from_user", None)
    if user:
        return getattr(user, "username", "") or ""
    return ""


def safe_send(chat_id, text: str | list[str] | tuple[str, ...], parse_mode: str | None = "Markdown", reply_markup: any = None):
    if text is None:
        text = ""
    if isinstance(text, (list, tuple)):
        full_text = "\n\n".join(str(part) for part in text)
    else:
        full_text = str(text)
    CHUNK_SIZE = min(MAX_TELEGRAM_MESSAGE_LENGTH, 3800)

    def _chunk_text(s: str, limit: int) -> list[str]:
        if len(s) <= limit:
            return [s]
        chunks = []
        while len(s) > limit:
            split_at = s.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(s[:split_at].strip())
            s = s[split_at:].strip()
        if s:
            chunks.append(s)
        return chunks

    message_chunks = _chunk_text(full_text, CHUNK_SIZE)
    for i, chunk in enumerate(message_chunks):
        markup = reply_markup if i == len(message_chunks) - 1 else None
        try:
            bot.send_message(chat_id, chunk, parse_mode=parse_mode, reply_markup=markup)
        except Exception as exc:
            logging.error(f"Failed to send message chunk: {exc}")
            if parse_mode == "Markdown":
                try:
                    bot.send_message(chat_id, chunk, parse_mode=None, reply_markup=markup)
                except Exception as exc2:
                    logging.error(f"Failed to send message chunk even without Markdown: {exc2}")
        time.sleep(1.0)


def stringify_response(text: str | list[str] | tuple[str, ...]) -> str:
    if isinstance(text, (list, tuple)):
        return "\n\n".join(str(part) for part in text)
    return str(text or "")


def record_qa_safely(user_id: int, question: str, answer: str | list[str] | tuple[str, ...]) -> None:
    try:
        database.record_qa_log(user_id, question, stringify_response(answer))
    except Exception as exc:
        logging.warning("record qa log failed: %s", exc)


def record_user_log_safely(
    user_id: int,
    user_name: str,
    username: str,
    question: str,
    answer: str | list[str] | tuple[str, ...] | None = None,
    *,
    source: str = "text",
    file_id: str | None = None,
) -> None:
    try:
        database.record_user_interaction(
            user_id,
            question,
            stringify_response(answer) if answer is not None else None,
            display_name=user_name,
            username=username,
            source=source,
            file_id=file_id,
        )
    except Exception as exc:
        logging.warning("record user.log failed: %s", exc)


def send_photo_with_user_log(
    chat_id: int,
    photo,
    *,
    caption: str = "",
    parse_mode: str | None = None,
    user_id: int | None = None,
    user_name: str = "User",
    username: str = "",
    question: str = "",
    source: str = "chart",
):
    """統一發送圖表並把 Telegram file_id 寫入 user.log，供 /ulog 日後調圖。"""
    msg = bot.send_photo(chat_id, photo=photo, caption=caption, parse_mode=parse_mode)
    if user_id:
        try:
            file_id = msg.photo[-1].file_id if msg and msg.photo else None
            record_user_log_safely(
                int(user_id),
                user_name,
                username,
                question or caption or "圖表",
                caption or None,
                source=source,
                file_id=file_id,
            )
        except Exception as exc:
            logging.warning("record chart file_id failed: %s", exc)
    return msg


def reply(message, text: str | list[str], parse_mode: str | None = "Markdown", reply_markup: any = None):
    return safe_send(message.chat.id, text, parse_mode=parse_mode, reply_markup=reply_markup)


def maybe_send_tech_chart(
    chat_id: int,
    text: str,
    cmd_prefix: str = "/tech",
    *,
    user_id: int | None = None,
    user_name: str = "User",
    username: str = "",
    theme: str = "dark",
) -> None:
    """在 /tech 或 /chart 單一代號模式時發送戰術圖表。"""
    parts = (text or "").split()
    if len(parts) < 2:
        return

    sub = parts[1].strip().lower()
    if cmd_prefix == "/tech" and sub in {"compare", "help"}:
        return
    # /chart 支援 /chart SYMBOL THEME (3 parts)
    if cmd_prefix == "/chart":
        if len(parts) not in {2, 3}:
            return
    else:
        if len(parts) != 2:
            return

    symbol = parts[1].strip().upper()
    if not symbol:
        return

    # 冷卻機制：同 chat + symbol 短時間內不重繪，降低 CPU/RAM
    now_ts = time.time()
    key = (int(chat_id), symbol)
    last_ts = _TECH_CHART_LAST_TS.get(key, 0.0)
    if now_ts - last_ts < TECH_CHART_COOLDOWN_SECONDS:
        return

    buf = None
    try:
        buf = tech_indicators.generate_tech_chart_buffer(symbol, theme=theme)
        
        # 發送圖表並提取 file_id，供 /ulog 日後調圖
        send_photo_with_user_log(
            chat_id,
            buf,
            caption=f"{symbol} Tactical Chart",
            user_id=user_id,
            user_name=user_name,
            username=username,
            question=text,
            source="chart",
        )
            
        _TECH_CHART_LAST_TS[key] = now_ts
    except Exception as exc:
        logging.warning("maybe_send_tech_chart failed for %s: %s", symbol, exc)
    finally:
        if buf is not None:
            try:
                buf.close()
            except Exception:
                pass
        # 發送後立即清掉該 symbol 快取，降低記憶體占用
        try:
            tech_indicators.clear_tech_df_cache(symbol)
        except Exception:
            pass
        gc.collect()


def maybe_send_fin_chart(
    chat_id: int,
    text: str,
    *,
    theme: str = "dark",
    user_id: int | None = None,
    user_name: str = "User",
    username: str = "",
) -> None:
    """/fin 圖表輸出：支援 /fin [symbol] 與 /fin chart [symbol]。"""
    parts = (text or "").split()
    if not parts or parts[0].lower() != "/fin":
        return

    symbol = ""
    is_explicit_chart_cmd = False
    if len(parts) == 2 and parts[1].strip().lower() != "compare":
        symbol = parts[1].strip().upper()
    elif len(parts) == 3 and parts[1].strip().lower() == "chart":
        symbol = parts[2].strip().upper()
        is_explicit_chart_cmd = True
    else:
        return

    if not symbol:
        return

    def _build_fin_diag_message(sym: str) -> str:
        diag = sec_api.get_financial_diagnostics(sym)
        detail = diag.get("details", {})
        rev = detail.get("revenue", {})
        ni = detail.get("net_income", {})
        eps = detail.get("eps", {})
        return (
            f"ℹ️ `{sym}` 目前無法產生財報圖。\n"
            f"• 原因：`{diag.get('reason', 'unknown')}`\n"
            f"• CIK：`{diag.get('cik', 'N/A')}`\n"
            f"• SEC HTTP：`{diag.get('http_status', 'N/A')}`\n"
            f"• Revenue：`rows={rev.get('rows', 0)}`，最新季：`{rev.get('latest_end', 'N/A')}`\n"
            f"• Net Income：`rows={ni.get('rows', 0)}`，最新季：`{ni.get('latest_end', 'N/A')}`\n"
            f"• EPS：`rows={eps.get('rows', 0)}`，最新季：`{eps.get('latest_end', 'N/A')}`\n"
            "請稍後重試，系統會自動刷新 SEC 對照與重抓最新資料。"
        )

    fin_buf = None
    try:
        # 強制使用 SEC API 獲取數據
        df = sec_api.fetch_sec_financials(symbol)
        fin_buf = market_api.generate_professional_chart(df, symbol, theme=theme)

        if fin_buf is None:
            safe_send(chat_id, _build_fin_diag_message(symbol))
            return

        # 傳送穩定化：失敗時重試一次
        sent = False
        last_exc = None
        for _ in range(2):
            try:
                fin_buf.seek(0)
                send_photo_with_user_log(
                    chat_id,
                    fin_buf,
                    caption=f"{symbol} Financial Chart (Rev/NI/Margin/QoQ)",
                    user_id=user_id,
                    user_name=user_name,
                    username=username,
                    question=text,
                    source="/fin_chart",
                )
                sent = True
                break
            except Exception as exc:
                last_exc = exc

        if not sent:
            safe_send(chat_id, f"⚠️📤 `{symbol}` 財報圖傳送失敗。原因：{last_exc}")
            logging.warning("send fin chart failed after retry for %s: %s", symbol, last_exc)

    except Exception as exc:
        # 使用者明確下 /fin chart 時，回覆完整錯誤原因
        if is_explicit_chart_cmd:
            safe_send(chat_id, f"🚫⚠️ `{symbol}` /fin chart 失敗：{exc}\n\n{_build_fin_diag_message(symbol)}")
        logging.warning("send fin chart failed: %s", exc)
    finally:
        if fin_buf is not None:
            try:
                fin_buf.close()
            except Exception:
                pass
        gc.collect()


def maybe_send_fin_compare_chart(
    chat_id: int,
    text: str,
    *,
    user_id: int | None = None,
    user_name: str = "User",
    username: str = "",
) -> None:
    """/fin compare 後附加合併對比圖（2~3 檔）。"""
    parts = (text or "").split()
    if len(parts) < 4 or parts[0].lower() != "/fin" or parts[1].lower() != "compare":
        return
    symbols = [p.strip().upper() for p in parts[2:] if p.strip()][:3]
    if len(symbols) < 2:
        return
    buf = None
    try:
        buf = command.market_api.generate_fin_compare_chart_buffer(symbols)
        if buf is None:
            safe_send(chat_id, "ℹ️ /fin compare 對比圖資料不足，暫時無法出圖。")
            return
        send_photo_with_user_log(
            chat_id,
            buf,
            caption=f"{' vs '.join(symbols)} Financial Comparison Chart",
            user_id=user_id,
            user_name=user_name,
            username=username,
            question=text,
            source="/fin_compare_chart",
        )
    except Exception as exc:
        logging.warning("send fin compare chart failed: %s", exc)
    finally:
        if buf is not None:
            try:
                buf.close()
            except Exception:
                pass
        gc.collect()


def run_with_loading(message, loading_text: str, task_fn, error_prefix: str = "處理失敗"):
    """統一 loading 訊息顯示/刪除與錯誤回覆流程。"""
    loading = reply(message, loading_text)
    try:
        result = task_fn()
        if loading:
            bot.delete_message(message.chat.id, loading.message_id)
        return result
    except Exception as exc:
        logging.exception("%s: %s", error_prefix, exc)
        if loading:
            bot.delete_message(message.chat.id, loading.message_id)
        reply(message, f"⚠️ {error_prefix}：{exc}")
        return None


def delete_loading_safe(message, msg):
    """安全刪除 loading 訊息（若存在）。"""
    try:
        bot.delete_message(message.chat.id, msg.message_id)
    except Exception:
        pass


def setup_bot_commands() -> None:
    commands = [
        telebot.types.BotCommand("now", "⚡ 即時全景 + 總損益"),
        telebot.types.BotCommand("calendar", "🗓️ 宏觀與事件日曆"),
        telebot.types.BotCommand("theory", "📘 交易百科教學"),
        telebot.types.BotCommand("list", "📋 持股詳細明細"),
        telebot.types.BotCommand("news", "📰 即時新聞與市場報告"),
        telebot.types.BotCommand("fin", "📊 個股財報 / compare / chart"),
        telebot.types.BotCommand("whale", "🐋 大鯨魚/內部人追蹤"),
        telebot.types.BotCommand("tech", "📊 專業量化分析"),
        telebot.types.BotCommand("backtest", "📊 量化回測（含 /bt model）"),
        telebot.types.BotCommand("simulator", "🔮 蒙地卡羅（含極端風險警告）"),
        telebot.types.BotCommand("chart", "🖼️ 戰術圖表"),
        telebot.types.BotCommand("risk", "🛡️ 市場風險雷達"),
        telebot.types.BotCommand("marco", "📊 宏觀數據雷達"),
        telebot.types.BotCommand("sweep", "🎯 狙擊監控管理"),
        telebot.types.BotCommand("bc", "📢 自動推播設定"),
        telebot.types.BotCommand("data", "🧹 資料清除（需二次確認）"),
        telebot.types.BotCommand("quota", "💳 API 使用配額"),
        telebot.types.BotCommand("status", "🔍 AI 連線驗證"),
        telebot.types.BotCommand("help", "🎯 指揮手冊（美化版）"),
    ]
    bot.set_my_commands(commands)


def get_pagination_markup(prefix: str, current_page: int, total_pages: int, token: str | None = None) -> InlineKeyboardMarkup | None:
    if total_pages <= 1 or token is None:
        return None
    markup = InlineKeyboardMarkup()
    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton("⬅️ 上一頁", callback_data=f"{prefix}_{token}_{current_page-1}"))
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton("下一頁 ➡️", callback_data=f"{prefix}_{token}_{current_page+1}"))
    if buttons:
        markup.row(*buttons)
    return markup


def get_cached_page_markup(token: str, current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    markup = InlineKeyboardMarkup()
    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton("⬅️ 上一頁", callback_data=f"page_{token}_{current_page-1}"))
    buttons.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data=f"page_{token}_{current_page}"))
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton("下一頁 ➡️", callback_data=f"page_{token}_{current_page+1}"))
    markup.row(*buttons)
    return markup


def send_paged_message(chat_id, pages: list[str] | tuple[str, ...], parse_mode: str | None = "Markdown") -> None:
    clean_pages = [str(p).strip() for p in pages if str(p).strip()]
    if not clean_pages:
        safe_send(chat_id, "⚠️ 沒有可顯示的內容。", parse_mode=parse_mode)
        return
    token = f"{int(time.time() * 1000000) % 10**12:x}"
    add_to_paged_cache(token, clean_pages)
    safe_send(
        chat_id,
        clean_pages[0],
        parse_mode=parse_mode,
        reply_markup=get_cached_page_markup(token, 1, len(clean_pages)),
    )


def notify_status(status_type: str) -> None:
    if not ADMIN_ID:
        return
    from ai_core import get_current_time_str

    now_full = get_current_time_str()
    if status_type == "online":
        logging.info("🚀 [SYSTEM] 啟動中")
        status_pages = command.cmd_status(int(ADMIN_ID))
        startup_header = f"🎯 美股顧問核心已啟動\n\n🕒 啟動時間：{now_full}"
        safe_send(ADMIN_ID, [*status_pages, startup_header])
    elif status_type == "offline":
        logging.info("🛑 [SYSTEM] 關閉中")
        safe_send(ADMIN_ID, f"⚠️ 美股顧問系統已下線\n🕒 關閉時間：{now_full}")


def handle_shutdown(signum=None, frame_obj=None):
    notify_status("offline")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def auto_news_job() -> None:
    while True:
        try:
            now_ts = time.time()
            for row in database.get_all_active_bc_users():
                user_id = int(row.get("user_id", 0) or 0)
                if user_id <= 0:
                    continue
                interval_min = int(row.get("bc_timer", 120) or 120)
                if interval_min < 30:
                    interval_min = 30
                last_ts = float(row.get("last_bc_ts", 0) or 0)
                if last_ts > 0 and now_ts - last_ts < interval_min * 60:
                    continue
                user_name = database.get_user_display_name(user_id)
                msg = _truncate_ai_text(command.cmd_proactive_news(user_name, user_id=user_id))
                safe_send(user_id, msg)
                database.update_bc_settings(user_id, last_ts=now_ts)
        except Exception as exc:
            logging.warning("auto_news_job failed: %s", exc)
        finally:
            gc.collect()
            time.sleep(30)


def major_news_alert_job() -> None:
    seen_news_urls: set[str] = set()
    while True:
        try:
            for user_id in database.get_all_user_ids():
                watchlist = database.get_watchlist(user_id)
                if not watchlist:
                    continue
                user_name = database.get_user_display_name(user_id)
                for symbol in watchlist:
                    news_items = command.market_api.fetch_news_filtered(symbol, limit=2)
                    for item in news_items:
                        url = item.get("url") or ""
                        if not url or url in seen_news_urls:
                            continue
                        seen_news_urls.add(url)
                        summary = command.process_news_item_smart(symbol, item, user_name, user_id)
                        message = _truncate_ai_text(f"🔔 重大新聞快訊：{symbol}\n━━━━━━━━━━━━━━\n{summary}")
                        safe_send(user_id, message)
        except Exception as exc:
            logging.warning("major_news_alert_job failed: %s", exc)
        finally:
            gc.collect()
            time.sleep(ALERT_NEWS_INTERVAL_SECONDS)


def market_report_job() -> None:
    tz = ZoneInfo("America/New_York")
    last_pre_report_day = ""
    last_post_report_day = ""
    while True:
        try:
            now_et = datetime.now(tz)
            day_str = now_et.strftime("%Y-%m-%d")
            time_str = now_et.strftime("%H:%M")
            if 0 <= now_et.weekday() <= 4:
                if time_str == "09:00" and last_pre_report_day != day_str:
                    for user_id in database.get_all_user_ids():
                        user_name = database.get_user_display_name(user_id)
                        safe_send(user_id, _truncate_ai_text(command.cmd_pre_market_report(user_name, user_id=user_id)))
                    last_pre_report_day = day_str
                if time_str == "16:30" and last_post_report_day != day_str:
                    for user_id in database.get_all_user_ids():
                        user_name = database.get_user_display_name(user_id)
                        safe_send(user_id, _truncate_ai_text(command.cmd_post_market_report(user_name, user_id=user_id)))
                    last_post_report_day = day_str
        except Exception as exc:
            logging.warning("market_report_job error: %s", exc)
        finally:
            gc.collect()
            time.sleep(30)


SNIPER_WATCH_ZONES: dict[str, dict[str, Any]] = {}


def sniper_alert_job() -> None:
    import ai_core
    import market_api
    import tech_indicators

    sent_alerts: set[tuple[int, str, str, str]] = set()
    logging.info("🎯 [SNIPER] 狙擊監控執行緒已啟動")

    while True:
        if not is_market_open():
            # logging.info("🎯 [SNIPER] 市場未開盤，狙擊任務休眠 60s")
            time.sleep(60)
            continue

        time.sleep(SNIPER_CHECK_INTERVAL)
        try:
            targets = database.get_all_sniper_targets()
            if not targets:
                continue

            today = datetime.now().strftime("%Y-%m-%d")
            symbols = list(set([t[1] for t in targets]))
            current_prices = market_api.fetch_batch_quotes(symbols)

            for user_id, symbol in targets:
                price = current_prices.get(symbol)
                if not price:
                    continue

                now_ts = time.time()
                if symbol not in SNIPER_WATCH_ZONES or now_ts - SNIPER_WATCH_ZONES[symbol]["last_updated"] > 3600:
                    data = tech_indicators.calculate_indicators(symbol)
                    if "error" not in data:
                        SNIPER_WATCH_ZONES[symbol] = {
                            "fvg": data.get("fvg", {}),
                            "sweep": data.get("sweep", "無"),
                            "snapshot": data,
                            "last_updated": now_ts,
                        }

                zone_info = SNIPER_WATCH_ZONES.get(symbol)
                if not zone_info:
                    continue

                fvg = zone_info["fvg"]
                sweep = zone_info["sweep"]
                hit_type = None

                # FVG 比對 (數字比對，0 Token)
                if fvg.get("low_b") and fvg.get("high_b"):
                    if fvg["low_b"] <= price <= fvg["high_b"]:
                        hit_type = f"進入 {fvg['type']}"

                # 掃蕩比對
                if sweep != "無":
                    hit_type = sweep

                if hit_type:
                    alert_key = (user_id, symbol, hit_type, today)
                    if alert_key not in sent_alerts:
                        logging.info(f"🎯 [SNIPER] 命中！{symbol} 觸發 {hit_type}")
                        user_name = database.get_user_display_name(user_id)
                        model_pref = database.get_user_model_preference(user_id)
                        prompt = _truncate_ai_text(
                            f"🚨 狙擊警報：{symbol} 已命中 {hit_type}！現價：{price}\n"
                            f"技術快照：\n{zone_info['snapshot']}\n請產出正式狙擊報表。"
                        )
                        ai_message = ai_core.ask_model(prompt, user_name, model=model_pref, user_id=user_id)
                        header = f"🚨 **【狙擊手警報：{symbol}】**\n結構共振：{hit_type}"
                        safe_send(user_id, [header, _truncate_ai_text(ai_message)])
                        sent_alerts.add(alert_key)

            if datetime.now().hour == 0 and datetime.now().minute < 20:
                sent_alerts.clear()
        except Exception as exc:
            logging.warning("sniper_alert_job error: %s", exc)
        finally:
            gc.collect()


def log_cleanup_job() -> None:
    import os

    from config import GEMINI_AUDIT_LOG_PATH

    while True:
        time.sleep(4 * 24 * 3600)
        try:
            if os.path.exists(GEMINI_AUDIT_LOG_PATH):
                os.remove(GEMINI_AUDIT_LOG_PATH)
                logging.info("🧹 系統審計日誌已自動清除。")
        except Exception as e:
            logging.error(f"自動清除日誌失敗：{e}")


@bot.message_handler(commands=["tech"])
def on_tech(m):
    user_id, user_name = register_user(m)
    if not try_acquire_heavy_task(m, user_id, "tech"):
        return
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/tech")
    status_msg = bot.reply_to(m, "📊 正在跑量化數據與產生 SMC 儀表板...")
    try:
        result = command.cmd_tech(m.text or "", user_id)
        if isinstance(result, (list, tuple)):
            send_paged_message(m.chat.id, result)
        else:
            safe_send(m.chat.id, result)
        maybe_send_tech_chart(m.chat.id, m.text or "", user_id=user_id, user_name=user_name, username=get_username(m))
    except Exception as e:
        logging.error(f"Tech analysis failed: {e}")
        safe_send(m.chat.id, f"❌ 技術分析執行異常：{str(e)}")
    finally:
        delete_loading_safe(m, status_msg)
        release_heavy_task()


@bot.message_handler(commands=["bt", "backtest"])
def on_backtest(m):
    user_id, user_name = register_user(m)
    if not try_acquire_heavy_task(m, user_id, "backtest"):
        return
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/backtest")
    chart_buf = None
    
    status_msg = bot.reply_to(m, "📊 正在執行 SMC 回測與生成報表...")
    try:
        result = command.cmd_backtest(m.text or "", user_id)
        
        if isinstance(result, tuple):
            pages, chart_buf = result
            # 分頁文字 + 獨立圖表
            if isinstance(pages, list) and len(pages) > 0:
                send_paged_message(m.chat.id, pages)
            else:
                safe_send(m.chat.id, pages)
            if chart_buf:
                send_photo_with_user_log(
                    m.chat.id,
                    chart_buf,
                    caption=f"回測資產曲線圖",
                    user_id=user_id,
                    user_name=user_name,
                    username=get_username(m),
                    question=m.text or "",
                    source="/backtest_chart",
                )
        elif isinstance(result, list):
            send_paged_message(m.chat.id, result)
        else:
            safe_send(m.chat.id, result)
    except Exception as e:
        logging.error(f"Backtest execution failed: {e}")
        safe_send(m.chat.id, f"❌ 回測執行時發生未預期錯誤：{str(e)}")
    finally:
        try:
            if chart_buf:
                chart_buf.close()
        except Exception:
            pass
        try:
            bot.delete_message(m.chat.id, status_msg.message_id)
        except Exception:
            pass
        release_heavy_task()


@bot.message_handler(commands=["sim", "simulator"])
def on_simulator(m):
    user_id, user_name = register_user(m)
    if not try_acquire_heavy_task(m, user_id, "simulator"):
        return
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/simulator")
    chart_buf = None
    
    status_msg = bot.reply_to(m, "🔮 正在生成蒙地卡羅路徑與風險分布...")
    try:
        result = command.cmd_simulator(m.text or "", user_id)

        if isinstance(result, tuple):
            pages, chart_buf = result
            # 分頁文字 + 獨立圖表
            if isinstance(pages, list) and len(pages) > 0:
                send_paged_message(m.chat.id, pages)
            else:
                safe_send(m.chat.id, pages)
            if chart_buf:
                send_photo_with_user_log(
                    m.chat.id,
                    chart_buf,
                    caption=f"蒙地卡羅模擬路徑圖",
                    user_id=user_id,
                    user_name=user_name,
                    username=get_username(m),
                    question=m.text or "",
                    source="/simulator_chart",
                )
        elif isinstance(result, list):
            send_paged_message(m.chat.id, result)
        else:
            safe_send(m.chat.id, result)
    except Exception as e:
        logging.error(f"Simulator execution failed: {e}")
        safe_send(m.chat.id, f"❌ 模擬執行時發生未預期錯誤：{str(e)}")
    finally:
        try:
            if chart_buf:
                chart_buf.close()
        except Exception:
            pass
        try:
            bot.delete_message(m.chat.id, status_msg.message_id)
        except Exception:
            pass
        release_heavy_task()


@bot.message_handler(commands=["chart"])
def on_chart(m):
    user_id, user_name = register_user(m)
    text = (m.text or "").strip()
    parts = text.split()
    if len(parts) >= 2 and parts[1].strip().lower() == "theme":
        if len(parts) != 3 or parts[2].strip().lower() not in {"dark", "light"}:
            reply(m, "❌ 用法：`/chart theme [dark|light]`\n例如：`/chart theme dark`")
            return
        selected = parts[2].strip().lower()
        _USER_CHART_THEME[user_id] = selected
        reply(m, f"✅ 圖表主題已切換為：`{selected}`\n之後 `/chart [代號]` 會自動套用。")
        return

    if len(parts) < 2 or len(parts) > 3:
        reply(
            m,
            "📘 `/chart` 指令教學\n"
            "━━━━━━━━━━━━━━\n"
            "• `/chart [代號]`：輸出戰術圖\n"
            "• `/chart [代號] [dark|light]`：指定本次主題\n"
            "• `/chart theme [dark|light]`：設定預設主題\n"
            "例如：`/chart NVDA`",
        )
        return
    symbol = parts[1].strip().upper()
    if not symbol.isalnum():
        reply(m, "❌ 代號格式錯誤，請輸入英數代號，例如：`/chart NVDA`")
        return
    theme = _USER_CHART_THEME.get(user_id, "dark")
    if len(parts) == 3:
        candidate = parts[2].strip().lower()
        if candidate not in {"dark", "light"}:
            reply(m, "❌ 主題格式錯誤，請使用 `dark` 或 `light`，例如：`/chart NVDA light`")
            return
        theme = candidate
    record_user_log_safely(user_id, user_name, get_username(m), text, source="/chart")
    maybe_send_tech_chart(m.chat.id, text, cmd_prefix="/chart", user_id=user_id, user_name=user_name, username=get_username(m), theme=theme)


@bot.message_handler(commands=["risk"])
def on_risk(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "/risk", source="/risk")
    status_msg = bot.reply_to(m, "🛡️ 正在整理風險雷達資料...")
    try:
        result = command.cmd_risk(user_id=user_id, user_name=user_name)
        if result is not None:
            reply(m, result)
    except Exception as exc:
        logging.error(f"Risk command failed: {exc}")
        safe_send(m.chat.id, f"⚠️ 讀取風險資料失敗：{exc}")
    finally:
        delete_loading_safe(m, status_msg)


@bot.message_handler(commands=["marco"])
def on_marco(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "/marco", source="/marco")
    status_msg = bot.reply_to(m, "📊 正在蒐集總體經濟數據...")
    try:
        pages = command.cmd_marco(user_id=user_id, user_name=user_name)
        if pages:
            send_paged_message(m.chat.id, pages)
    except Exception as exc:
        logging.error(f"Marco command failed: {exc}")
        safe_send(m.chat.id, f"⚠️ 讀取宏觀數據失敗：{exc}")
    finally:
        delete_loading_safe(m, status_msg)


@bot.message_handler(commands=["help"])
def on_help(m):
    help_parts = command.frame.help_text()
    send_paged_message(m.chat.id, help_parts)


@bot.message_handler(commands=["now"])
def on_now(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "/now", source="/now")
    status_msg = bot.reply_to(m, "⚡ 正在彙整即時市場資訊與 AI 短評...")
    try:
        sections = command.cmd_now(user_id, user_name)
        if isinstance(sections, (list, tuple)):
            send_paged_message(m.chat.id, sections)
        else:
            reply(m, sections)
    except Exception as exc:
        logging.error(f"Now command failed: {exc}")
        safe_send(m.chat.id, f"⚠️ 讀取行情失敗。")
    finally:
        delete_loading_safe(m, status_msg)


@bot.message_handler(commands=["list"])
def on_list(m):
    user_id, _ = register_user(m)
    text, total_pages = command.cmd_list(user_id, page=1)
    markup = get_pagination_markup("list_page", 1, total_pages, token=str(user_id))
    reply(m, text, reply_markup=markup)


@bot.message_handler(commands=["buy"])
def on_buy(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "🧾 正在寫入買入紀錄...", lambda: command.cmd_buy(m.text or "", user_id), "買入記錄失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["sell"])
def on_sell(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "🧾 正在寫入賣出紀錄...", lambda: command.cmd_sell(m.text or "", user_id), "賣出記錄失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["watch"])
def on_watch(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "👀 正在更新雷達監控...", lambda: command.cmd_watch(m.text or "", user_id), "雷達指令失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["sweep"])
def on_sweep(m):
    user_id, _ = register_user(m)
    try:
        result = command.cmd_sweep(m.text or "", user_id)
        if result is not None:
            reply(m, result)
    except Exception as exc:
        logging.exception("狙擊指令失敗: %s", exc)
        reply(m, f"⚠️ 狙擊指令失敗：{exc}")


@bot.message_handler(commands=["news"])
def on_news(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/news")
    status_msg = bot.reply_to(m, "📰 正在搜尋相關新聞與 AI 分析...")
    try:
        msgs = command.cmd_news(m.text or "", user_name, user_id)
        if msgs:
            send_paged_message(m.chat.id, msgs)
    except Exception as e:
        logging.error(f"News fetch failed: {e}")
        safe_send(m.chat.id, f"❌ 新聞查詢異常：{str(e)}")
    finally:
        delete_loading_safe(m, status_msg)


@bot.message_handler(commands=["fin"])
def on_fin(m):
    user_id, _ = register_user(m)
    if not try_acquire_heavy_task(m, user_id, "fin"):
        return
    user_name = get_user_display_name(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/fin")
    text = m.text or ""
    parts = text.split()
    is_compare = len(parts) >= 2 and parts[1].lower() == "compare"
    status_msg = None
    try:
        if is_compare:
            status_msg = bot.reply_to(m, "📊 正在整理財報比較與 AI 評析...")
            try:
                result = command.cmd_fin(text, user_id)
            except Exception as exc:
                reply(m, f"⚠️ 財報查詢失敗：{exc}")
                return
        else:
            try:
                result = command.cmd_fin(text, user_id)
            except Exception as exc:
                reply(m, f"⚠️ 財報查詢失敗：{exc}")
                return

        if isinstance(result, (list, tuple)):
            send_paged_message(m.chat.id, result)
        else:
            reply(m, result)

        # /fin compare 送合併圖；其餘 /fin 送單檔圖
        if is_compare:
            maybe_send_fin_compare_chart(m.chat.id, text, user_id=user_id, user_name=user_name, username=get_username(m))
        else:
            theme = _USER_CHART_THEME.get(user_id, "dark")
            maybe_send_fin_chart(m.chat.id, text, theme=theme, user_id=user_id, user_name=user_name, username=get_username(m))
    finally:
        if status_msg is not None:
            try:
                bot.delete_message(m.chat.id, status_msg.message_id)
            except Exception:
                pass
        release_heavy_task()


@bot.message_handler(commands=["whale"])
def on_whale(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/whale")
    result = run_with_loading(m, "🐋 正在抓取內部人與機構持倉資料...", lambda: command.cmd_whale(m.text or "", user_id), "鯨魚情報查詢失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["quota"])
def on_quota(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "💳 正在統計配額使用量...", lambda: command.cmd_quota(user_id), "配額查詢失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["bc"])
def on_bc(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "📢 正在更新推播設定...", lambda: command.cmd_bc(m.text or "", user_id), "推播設定失敗")
    if result is not None:
        reply(m, result)


@bot.message_handler(commands=["data"])
def on_data(m):
    user_id, _ = register_user(m)
    result = run_with_loading(m, "🧹 正在處理資料清除請求...", lambda: command.cmd_data_clear(m.text or "", user_id), "資料清除失敗")
    if result is not None:
        reply(m, result)


CHART_KEYWORDS = ["chart", "圖表", "線圖", "走勢圖", "分析圖"]


def check_and_send_auto_chart(chat_id, query_text, symbol, user_id, user_name, username):
    """偵測問題中是否包含圖表關鍵字，若是則自動補發戰術圖。"""
    if any(kw in query_text.lower() for kw in CHART_KEYWORDS) and symbol:
        logging.info(f"Auto-chart triggered for {symbol} by query: {query_text}")
        # 延遲一下下，確保文字回覆先到
        time.sleep(0.5)
        maybe_send_tech_chart(
            chat_id, 
            f"/chart {symbol}", 
            cmd_prefix="/chart", 
            user_id=user_id, 
            user_name=user_name, 
            username=username
        )


@bot.message_handler(commands=["ask"])
def on_ask(m):
    user_id, user_name = register_user(m)
    if not try_acquire_heavy_task(m, user_id, "ask", cooldown_seconds=8):
        return
    username = get_username(m)
    query_text = m.text or ""
    
    status_msg = bot.reply_to(m, "🤖 正在生成深度戰術回覆...")
    try:
        result = command.cmd_ask(query_text, user_name, user_id)
        reply(m, result)
        record_qa_safely(user_id, query_text, result)
        record_user_log_safely(user_id, user_name, username, query_text, result, source="/ask")
        
        # 自動圖表觸發
        parts = query_text.split(maxsplit=2)
        if len(parts) >= 2:
            symbol = parts[1].upper().strip()
            check_and_send_auto_chart(m.chat.id, query_text, symbol, user_id, user_name, username)
    except Exception as exc:
        logging.exception("ask failed: %s", exc)
        reply(m, f"⚠️ /ask 執行失敗：{exc}")
    finally:
        delete_loading_safe(m, status_msg)
        release_heavy_task()


@bot.message_handler(commands=["theory"])
def on_theory(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/theory")
    pages = command.cmd_theory(m.text or "")
    if isinstance(pages, (list, tuple)):
        send_paged_message(m.chat.id, pages)
    else:
        reply(m, pages)


@bot.message_handler(commands=["calendar"])
def on_calendar(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/calendar")
    status_msg = bot.reply_to(m, "🗓️ 正在彙整宏觀事件與財報日曆...")
    try:
        pages, cal_img = command.cmd_calendar(user_id, user_name)
        if isinstance(pages, (list, tuple)):
            send_paged_message(m.chat.id, pages)
        else:
            reply(m, pages)
        if cal_img is not None:
            safe_send(m.chat.id, "🖼️ 以下為當月美股事件行事曆（含生成時間）")
            bot.send_photo(m.chat.id, photo=cal_img, caption="US Market Calendar")
    except Exception as exc:
        logging.error("Calendar command failed: %s", exc)
        safe_send(m.chat.id, f"❌ /calendar 執行失敗：{exc}")
    finally:
        delete_loading_safe(m, status_msg)


@bot.message_handler(commands=["status"])
def on_status(m):
    user_id, _ = register_user(m)
    try:
        result = command.cmd_status(user_id)
        if result is not None:
            reply(m, result)
    except Exception as exc:
        logging.exception("狀態檢查失敗: %s", exc)
        reply(m, f"⚠️ 狀態檢查失敗：{exc}")


def reply_multi_modal(message, result):
    """處理多模態回覆 (文字、圖片轉發)。"""
    if result is None:
        return
    if isinstance(result, str):
        reply(message, result)
    elif isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, str):
                safe_send(message.chat.id, item)
            elif isinstance(item, dict) and item.get("type") == "photo":
                file_id = item.get("file_id")
                caption = item.get("caption", "")
                if file_id:
                    try:
                        bot.send_photo(message.chat.id, photo=file_id, caption=caption)
                    except Exception as exc:
                        logging.warning("send_photo by file_id failed: %s", exc)
                        safe_send(message.chat.id, f"🖼️ (圖片轉發失敗，請確認 CDN 權限) {caption}")
    else:
        reply(message, str(result))


@bot.message_handler(commands=["op"])
def on_op(m):
    user_id = get_user_id(m)
    try:
        res = command.cmd_op(m.text or "", user_id)
        if res is None:
            return
        if res == "__TRIGGER_LOG__":
            on_log(m)
        else:
            reply_multi_modal(m, res)
    except Exception as exc:
        logging.exception("後台指令失敗: %s", exc)
        reply(m, f"⚠️ 後台指令失敗：{exc}")


@bot.message_handler(commands=["log"])
def on_log(m):
    log_lines = read_hidden_log_lines(40)
    if not log_lines:
        reply(m, "🔒 系統日誌為空。")
    else:
        safe_send(m.chat.id, "🔒 系統日誌\n" + "\n".join(log_lines))


@bot.message_handler(commands=["ulog"])
def on_ulog(m):
    user_id, user_name = register_user(m)
    record_user_log_safely(user_id, user_name, get_username(m), m.text or "", source="/ulog")
    result = run_with_loading(m, "📚 正在查詢使用者紀錄...", lambda: command.cmd_ulog(m.text or "", user_id), "查詢紀錄失敗")
    if result is not None:
        reply_multi_modal(m, result)


@bot.callback_query_handler(func=lambda call: call.data.startswith("list_page_"))
def on_list_callback(call):
    try:
        parts = call.data.split("_")
        page = int(parts[-1])
        user_id = int(parts[2])
        text, total_pages = command.cmd_list(user_id, page=page)
        markup = get_pagination_markup("list_page", page, total_pages, token=str(user_id))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as exc:
        logging.warning("list callback failed: %s", exc)


@bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
def on_cached_page_callback(call):
    try:
        parts = call.data.split("_")
        page = int(parts[-1])
        token = parts[1]
        entry = PAGED_MESSAGE_CACHE.get(token)
        pages = entry[0] if isinstance(entry, tuple) else (entry or [])
        if not pages:
            bot.answer_callback_query(call.id, "⚠️ 這份分頁內容已過期，請重新輸入指令。")
            return
        total_pages = len(pages)
        if page < 1 or page > total_pages:
            bot.answer_callback_query(call.id, "已在頁面邊界。")
            return
        bot.edit_message_text(
            pages[page - 1],
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_cached_page_markup(token, page, total_pages),
        )
    except Exception as exc:
        logging.warning("cached page callback failed: %s", exc)


@bot.message_handler(func=lambda m: True)
def on_text(m):
    text_raw = getattr(m, "text", "") or ""
    text = normalize_loose_command_text(text_raw)
    if not text:
        return

    # 補強：讓 ./bc、/ bc、./sweep 等輸入也可正常觸發
    if text.startswith("/"):
        user_id, user_name = register_user(m)
        lowered = text.lower()

        if lowered.startswith("/now"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/now")
            result = command.cmd_now(user_id, user_name)
            if isinstance(result, (list, tuple)):
                send_paged_message(m.chat.id, result)
            else:
                reply(m, result)
            return
        if lowered.startswith("/tech"):
            if not try_acquire_heavy_task(m, user_id, "tech_text"):
                return
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/tech")
            try:
                result = command.cmd_tech(text, user_id)
                if isinstance(result, (list, tuple)):
                    send_paged_message(m.chat.id, result)
                else:
                    reply(m, result)
                maybe_send_tech_chart(m.chat.id, text, user_id=user_id, user_name=user_name, username=get_username(m))
            finally:
                release_heavy_task()
            return
        if lowered.startswith("/chart"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/chart")
            parts = text.split()
            if len(parts) >= 2 and parts[1].strip().lower() == "theme":
                if len(parts) == 3 and parts[2].strip().lower() in {"dark", "light"}:
                    selected = parts[2].strip().lower()
                    _USER_CHART_THEME[user_id] = selected
                    reply(m, f"✅ 圖表主題已切換為：`{selected}`\n之後 `/chart [代號]` 會自動套用。")
                else:
                    reply(m, "❌ 用法：`/chart theme [dark|light]`\n例如：`/chart theme dark`")
                return

            theme = _USER_CHART_THEME.get(user_id, "dark")
            if len(parts) == 3 and parts[2].strip().lower() in {"dark", "light"}:
                theme = parts[2].strip().lower()
            maybe_send_tech_chart(m.chat.id, text, cmd_prefix="/chart", user_id=user_id, user_name=user_name, username=get_username(m), theme=theme)
            return
        if lowered.startswith("/news"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/news")
            status_msg = bot.reply_to(m, "📰 正在搜尋最新新聞與 AI 分析...")
            try:
                msgs = command.cmd_news(text, user_name, user_id)
                if msgs:
                    send_paged_message(m.chat.id, msgs)
            except Exception as exc:
                logging.error("News command failed: %s", exc)
                safe_send(m.chat.id, f"❌ 新聞查詢異常：{exc}")
            finally:
                delete_loading_safe(m, status_msg)
            return
        if lowered.startswith("/risk"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/risk")
            reply(m, command.cmd_risk(user_id=user_id, user_name=user_name))
            return
        if lowered.startswith("/marco"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/marco")
            send_paged_message(m.chat.id, command.cmd_marco(user_id=user_id, user_name=user_name))
            return
        if lowered.startswith("/calendar"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/calendar")
            status_msg = bot.reply_to(m, "🗓️ 正在彙整宏觀事件與財報日曆...")
            try:
                pages, cal_img = command.cmd_calendar(user_id, user_name)
                if isinstance(pages, (list, tuple)):
                    send_paged_message(m.chat.id, pages)
                else:
                    reply(m, pages)
                if cal_img is not None:
                    safe_send(m.chat.id, "🖼️ 以下為當月美股事件行事曆（含生成時間）")
                    bot.send_photo(m.chat.id, photo=cal_img, caption="US Market Calendar")
            except Exception as exc:
                logging.error("Calendar command failed: %s", exc)
                safe_send(m.chat.id, f"❌ /calendar 執行失敗：{exc}")
            finally:
                delete_loading_safe(m, status_msg)
            return
        if lowered.startswith("/fin"):
            if not try_acquire_heavy_task(m, user_id, "fin_text"):
                return
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/fin")
            try:
                result = command.cmd_fin(text, user_id)
                if isinstance(result, (list, tuple)):
                    send_paged_message(m.chat.id, result)
                else:
                    reply(m, result)
                parts = text.split()
                if len(parts) >= 2 and parts[1].lower() == "compare":
                    maybe_send_fin_compare_chart(m.chat.id, text, user_id=user_id, user_name=user_name, username=get_username(m))
                else:
                    theme = _USER_CHART_THEME.get(user_id, "dark")
                    maybe_send_fin_chart(m.chat.id, text, theme=theme, user_id=user_id, user_name=user_name, username=get_username(m))
            finally:
                release_heavy_task()
            return
        if lowered.startswith("/whale"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/whale")
            status_msg = bot.reply_to(m, "🐋 正在抓取內部人與機構持倉資料...")
            try:
                result = command.cmd_whale(text, user_id)
                if result is not None:
                    reply(m, result)
            except Exception as exc:
                logging.error("Whale command failed: %s", exc)
                safe_send(m.chat.id, f"⚠️ 鯨魚情報查詢失敗：{exc}")
            finally:
                delete_loading_safe(m, status_msg)
            return

        if lowered.startswith("/bc"):
            reply(m, command.cmd_bc(text, user_id))
            return
        if lowered.startswith("/sweep"):
            reply(m, command.cmd_sweep(text, user_id))
            return
        if lowered.startswith("/data") or lowered == "/data clear":
            reply(m, command.cmd_data_clear(text, user_id))
            return
        if lowered.startswith("/help"):
            send_paged_message(m.chat.id, command.frame.help_text())
            return
        if lowered.startswith("/theory"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/theory")
            result = command.cmd_theory(text)
            if isinstance(result, (list, tuple)):
                send_paged_message(m.chat.id, result)
            else:
                reply(m, result)
            return
        if lowered.startswith("/ulog"):
            record_user_log_safely(user_id, user_name, get_username(m), text, source="/ulog")
            reply(m, command.cmd_ulog(text, user_id))
            return

        # 其他斜線指令交由既有 command handler，這裡直接略過
        return

    user_id, user_name = register_user(m)
    if " ".join(text.strip().split()).lower() == "data clear":
        reply(m, command.cmd_data_clear(text, user_id))
        return
    status_msg = bot.reply_to(m, "🤖 AI 思考中，正在整理回覆...")
    try:
        result = command.handle_natural_language(text, user_name, user_id=user_id)
        reply(m, result)
        record_qa_safely(user_id, text, result)
        username = get_username(m)
        record_user_log_safely(user_id, user_name, username, text, result, source="natural")

        # 自然對話自動圖表觸發
        syms = command.STOCK_RE.findall(text)
        if syms:
            check_and_send_auto_chart(m.chat.id, text, syms[0].upper(), user_id, user_name, username)
    except Exception as exc:
        logging.error("Natural language handler failed: %s", exc)
        safe_send(m.chat.id, f"❌ AI 回覆失敗：{exc}")
    finally:
        delete_loading_safe(m, status_msg)


if __name__ == "__main__":
    database.init_db()
    database.reset_user_log()
    try:
        font_info = utils.debug_cjk_font_loading()
        logging.info("[CJK_FONT] env_dir=%s", font_info.get("cjk_font_dir_env") or "(empty)")
        logging.info("[CJK_FONT] picked_font=%s", font_info.get("picked_font"))
        logging.info("[CJK_FONT] scanned_files=%s", len(font_info.get("scanned_files", [])))
        for p in font_info.get("scanned_files", [])[:10]:
            logging.info("[CJK_FONT] file=%s", p)
    except Exception as exc:
        logging.warning("[CJK_FONT] debug print failed: %s", exc)

    setup_bot_commands()
    import brain

    brain.stats.alert_callback = lambda msg: safe_send(ADMIN_ID, msg)
    threading.Thread(target=auto_news_job, daemon=True).start()
    threading.Thread(target=major_news_alert_job, daemon=True).start()
    threading.Thread(target=market_report_job, daemon=True).start()
    threading.Thread(target=sniper_alert_job, daemon=True).start()
    threading.Thread(target=log_cleanup_job, daemon=True).start()
    notify_status("online")
    while True:
        try:
            bot.infinity_polling(timeout=POLLING_TIMEOUT, long_polling_timeout=LONG_POLLING_TIMEOUT)
        except Exception as exc:
            logging.error("Polling failed: %s", exc)
            time.sleep(10)
