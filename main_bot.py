"""main_bot.py
Telegram 執行核心：指令註冊、訊息分發、開關機通報、polling。
"""
from __future__ import annotations

import html
import logging
import re
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    from telebot.apihelper import RetryAfter
except ImportError:
    RetryAfter = ApiTelegramException

import command
import database
import frame
from config import (
    CHAT_ID,
    GEMINI_AUDIT_LOG_PATH,
    LONG_POLLING_TIMEOUT,
    MAX_TELEGRAM_MESSAGE_LENGTH,
    POLLING_TIMEOUT,
    TELEGRAM_TOKEN,
)

# 使用者要求最多 20 分鐘給一篇宏觀新聞
AUTO_NEWS_INTERVAL_SECONDS = 1200
# 重大新聞即時推送，最小輪詢間隔
ALERT_NEWS_INTERVAL_SECONDS = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")

# 統一由 config 模組讀取，若為空則報錯
if not TELEGRAM_TOKEN or len(TELEGRAM_TOKEN) < 10:
    logging.error("❌ 錯誤：TELEGRAM_TOKEN 未設定或格式不正確。請檢查 .env 檔案內容。")
    sys.exit(1)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True)


def get_user_display_name(m) -> str:
    """從 Telegram message/channel_post 中提取顯示名稱。"""
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


def is_admin_user(user_id: int) -> bool:
    try:
        # CHAT_ID 在 .env 是字串，例如 "-1003802320479"
        # 移除 int() 轉換，直接比對字串，避免處理負號轉型問題
        return CHAT_ID and str(user_id) == str(CHAT_ID).lstrip("-") or str(user_id) == str(CHAT_ID)
    except Exception as exc:
        logging.error(f"is_admin_user error: {exc}")
        return False


def read_hidden_log_lines(line_count: int = 40) -> list[str]:
    try:
        with open(GEMINI_AUDIT_LOG_PATH, "r", encoding="utf-8") as handle:
            lines = [line.rstrip() for line in handle.readlines() if line.strip()]
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


def _split_ai_sections(text: str) -> list[str]:
    markers = [
        "\n🤖 AI 交易副官結語",
        "\n🤖 AI 深度戰術分析：",
        "\n🤖 AI 智慧戰術分析：",
        "\nAI 回應：",
        "\nAI 評析：",
    ]
    for marker in markers:
        idx = text.find(marker)
        if idx > 0:
            before = text[:idx].rstrip()
            after = text[idx:].lstrip()
            if before and after:
                return [before, after]
    return [text]


def safe_send(chat_id, text: str | list[str], parse_mode: str | None = None, reply_markup: any = None):
    """安全發送：確保完整傳遞內容，嚴格按字元長度切割，且不破壞段落結構。"""
    if text is None:
        text = ""
    
    # 將所有內容視為一個長字串
    if isinstance(text, list):
        full_text = "\n\n".join(text)
    else:
        full_text = text
    
    # Telegram 單則訊息最大限制為 4096，設為 3800 以保留邊界
    CHUNK_SIZE = 3800
    
    def _chunk_text(s: str, limit: int) -> list[str]:
        if len(s) <= limit:
            return [s]
        
        chunks = []
        while len(s) > limit:
            # 尋找最近的換行符號切割，避免破壞段落
            split_at = s.rfind("\n", 0, limit)
            if split_at == -1:
                # 若找不到換行，強行切斷
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
            logging.error(f"Failed to send message chunk {i}: {exc}")
            # 降級發送：去除可能導致 Markdown 解析錯誤的符號
            try:
                plain_text = re.sub(r'[*_`]', '', chunk)
                bot.send_message(chat_id, plain_text, reply_markup=markup)
            except Exception as e:
                logging.error(f"Fallback send failed: {e}")
        time.sleep(1.0) # 確保發送間隔，防止被擋


def reply(message, text: str | list[str], parse_mode: str | None = None, reply_markup: any = None):
    return safe_send(message.chat.id, text, parse_mode=parse_mode, reply_markup=reply_markup)


def setup_bot_commands() -> None:
    commands = [
        telebot.types.BotCommand("now", "⚡ 即時全景 + 總損益"),
        telebot.types.BotCommand("list", "📋 持股詳細明細"),
        telebot.types.BotCommand("theme", "🚀 產業趨勢速報 (如: AI, 核能)"),
        telebot.types.BotCommand("news", "📰 即時新聞與完整市場報告"),
        telebot.types.BotCommand("news_help", "📖 新聞功能指南"),
        telebot.types.BotCommand("fin", "📊 個股財報與 EPS 查詢"),
        telebot.types.BotCommand("quota", "💳 查詢今日 API 使用配額"),
        telebot.types.BotCommand("status", "🔍 AI 連線狀態驗證"),
        telebot.types.BotCommand("help", "🎯 查看指揮手冊"),
    ]
    bot.set_my_commands(commands)
    logging.info(frame.menu_registered_text())


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


def notify_status(status_type: str) -> None:
    if not CHAT_ID:
        logging.warning("CHAT_ID is missing, cannot send status notification.")
        return
    
    # 獲取詳細時間
    from ai_core import get_current_time_str
    now_full = get_current_time_str()
    
    if status_type == "online":
        logging.info("🚀 [SYSTEM] 啟動中")
        # 將 CHAT_ID 作為 admin user_id 傳入
        msg = f"🎯 美股顧問核心已啟動\n━━━━━━━━━━━━━━\n{command.cmd_status(int(CHAT_ID))}\n\n🕒 啟動時間：{now_full}"
        safe_send(CHAT_ID, msg)
    elif status_type == "offline":
        logging.info("🛑 [SYSTEM] 關閉中")
        safe_send(CHAT_ID, f"⚠️ 美股顧問系統已下線\n🕒 關閉時間：{now_full}")


def handle_shutdown(signum=None, frame_obj=None):
    notify_status("offline")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def auto_news_job() -> None:
    while True:
        time.sleep(AUTO_NEWS_INTERVAL_SECONDS)
        try:
            for user_id in database.get_all_user_ids():
                user_name = database.get_user_display_name(user_id)
                safe_send(user_id, command.cmd_proactive_news(user_name, user_id=user_id))
        except Exception as exc:
            logging.warning("auto_news_job failed: %s", exc)


def major_news_alert_job() -> None:
    seen_news_urls: set[str] = set()
    while True:
        time.sleep(ALERT_NEWS_INTERVAL_SECONDS)
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
                        message = f"🔔 重大新聞快訊：{symbol}\n━━━━━━━━━━━━━━\n{summary}"
                        safe_send(user_id, message)
        except Exception as exc:
            logging.warning("major_news_alert_job failed: %s", exc)


def market_report_job() -> None:
    tz = ZoneInfo("America/New_York")
    last_pre_report_day = ""
    last_post_report_day = ""

    while True:
        try:
            now_et = datetime.now(tz)
            day_str = now_et.strftime("%Y-%m-%d")
            time_str = now_et.strftime("%H:%M")
            weekday = now_et.weekday()

            if 0 <= weekday <= 4:
                if time_str == "09:00" and last_pre_report_day != day_str:
                    for user_id in database.get_all_user_ids():
                        user_name = database.get_user_display_name(user_id)
                        safe_send(user_id, command.cmd_pre_market_report(user_name, user_id=user_id))
                    last_pre_report_day = day_str

                if time_str == "16:30" and last_post_report_day != day_str:
                    for user_id in database.get_all_user_ids():
                        user_name = database.get_user_display_name(user_id)
                        safe_send(user_id, command.cmd_post_market_report(user_name, user_id=user_id))
                    last_post_report_day = day_str
        except Exception as exc:
            logging.warning("market_report_job error: %s", exc)
        time.sleep(30)


@bot.message_handler(commands=["help"])
@bot.channel_post_handler(commands=["help"])
def on_help(m):
    reply(m, command.cmd_help())


@bot.message_handler(commands=["now"])
@bot.channel_post_handler(commands=["now"])
def on_now(m):
    bot.send_chat_action(m.chat.id, "typing")
    user_id, user_name = register_user(m)
    loading_message = reply(m, "⏳ 正在整理最新行情，請稍後...")
    try:
        sections = command.cmd_now(user_id, user_name)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        if isinstance(sections, (list, tuple)):
            for section in sections:
                reply(m, section)
        else:
            reply(m, sections)
    except Exception as exc:
        logging.warning("now command failed: %s", exc)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        reply(m, "⚠️ 讀取行情失敗，請稍後再試。")


@bot.message_handler(commands=["list"])
@bot.channel_post_handler(commands=["list"])
def on_list(m):
    user_id, _ = register_user(m)
    text, total_pages = command.cmd_list(user_id, page=1)
    markup = get_pagination_markup("list_page", 1, total_pages)
    reply(m, text, reply_markup=markup)


@bot.message_handler(commands=["buy"])
@bot.channel_post_handler(commands=["buy"])
def on_buy(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_buy(m.text or "", user_id))


@bot.message_handler(commands=["sell"])
@bot.channel_post_handler(commands=["sell"])
def on_sell(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_sell(m.text or "", user_id))


@bot.message_handler(commands=["watch"])
@bot.channel_post_handler(commands=["watch"])
def on_watch(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_watch(m.text or "", user_id))


@bot.message_handler(commands=["theme"])
@bot.channel_post_handler(commands=["theme"])
def on_theme(m):
    bot.send_chat_action(m.chat.id, "typing")
    user_id, user_name = register_user(m)
    loading_message = reply(m, "🌐 正在掃描全球趨勢情報，請稍後...")
    try:
        result = command.cmd_theme(m.text or "", user_name, user_id)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        reply(m, result)
    except Exception as exc:
        logging.warning("theme command failed: %s", exc)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        reply(m, "⚠️ 趨勢速報產生失敗，請稍後再試。")


@bot.message_handler(commands=["news"])
@bot.channel_post_handler(commands=["news"])
def on_news(m):
    if m.text and m.text.lower().strip() in {"/news help", "/news_help"}:
        on_news_help(m)
        return
    
    bot.send_chat_action(m.chat.id, "typing")
    user_id, user_name = register_user(m)
    loading_message = reply(m, "📰 正在讀取新聞，請稍後...")
    try:
        news_messages = command.cmd_news(m.text or "", user_name, user_id)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        if not news_messages:
            reply(m, "⚠️ 目前找不到相關新聞，請稍後再試。")
            return
        for message in news_messages:
            safe_send(m.chat.id, message)
    except Exception as exc:
        logging.warning("news command failed: %s", exc)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        reply(m, "⚠️ 讀取新聞失敗，請稍後再試。")


@bot.message_handler(commands=["news_help"])
@bot.channel_post_handler(commands=["news_help"])
def on_news_help(m):
    reply(m, command.cmd_news_help())


@bot.message_handler(commands=["fin"])
@bot.channel_post_handler(commands=["fin"])
def on_fin(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_fin(m.text or "", user_id))


@bot.message_handler(commands=["quota"])
@bot.channel_post_handler(commands=["quota"])
def on_quota(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_quota(user_id))


@bot.message_handler(commands=["ask"])
@bot.channel_post_handler(commands=["ask"])
def on_ask(m):
    bot.send_chat_action(m.chat.id, "typing")
    user_id, user_name = register_user(m)
    reply(m, command.cmd_ask(m.text or "", user_name, user_id))


@bot.message_handler(commands=["status"])
@bot.channel_post_handler(commands=["status"])
def on_status(m):
    bot.send_chat_action(m.chat.id, "typing")
    user_id, _ = register_user(m)
    reply(m, command.cmd_status(user_id))


@bot.message_handler(commands=["model"])
@bot.channel_post_handler(commands=["model"])
def on_model(m):
    user_id, _ = register_user(m)
    reply(m, command.cmd_set_model(m.text or "", user_id))


@bot.message_handler(commands=["op"])
@bot.channel_post_handler(commands=["op"])
def on_op(m):
    logging.info(f"Received /op command from user {m.from_user.id if m.from_user else 'None'}: {m.text}")
    user_id = get_user_id(m)
    admin_check = is_admin_user(user_id)
    logging.info(f"Admin check for user {user_id}: {admin_check}")
    
    if not admin_check:
        logging.warning(f"Unauthorized /op attempt from user {user_id}")
        return
    
    bot.send_chat_action(m.chat.id, "typing")
    text = m.text or ""
    parts = text.split()
    logging.info(f"Processing /op parts: {parts}")
    
    loading_message = None
    if len(parts) > 1 and parts[1].lower() in {"log", "quota"}:
        loading_message = reply(m, f"⏳ 正在執行管理指令 `{parts[1]}`，請稍後...")

    try:
        res = command.cmd_op(text, user_id)
        logging.info(f"cmd_op result: {res}")
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
            
        if res == "__TRIGGER_LOG__":
            on_log(m)
        else:
            reply(m, res)
    except Exception as exc:
        logging.error(f"op command failed with exception: {exc}", exc_info=True)
        if loading_message:
            bot.delete_message(m.chat.id, loading_message.message_id)
        reply(m, "⚠️ 管理指令執行失敗。")


@bot.message_handler(commands=["log"])
@bot.channel_post_handler(commands=["log"])
def on_log(m):
    user_id = get_user_id(m)
    if not is_admin_user(user_id):
        return
    log_lines = read_hidden_log_lines(40)
    if not log_lines:
        reply(m, "🔒 系統日誌目前為空或尚未產生。")
        return
    payload = "🔒 Gemini 系統日誌 (最近 40 筆)\n" + "\n".join(log_lines)
    safe_send(m.chat.id, payload)


@bot.callback_query_handler(func=lambda call: call.data.startswith("list_page_"))
def on_list_callback(call):
    try:
        page = int(call.data.replace("list_page_", ""))
        user_id, _ = register_user(call)
        text, total_pages = command.cmd_list(user_id, page=page)
        markup = get_pagination_markup("list_page", page, total_pages)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as exc:
        logging.warning("list_page callback failed: %s", exc)




@bot.message_handler(func=lambda m: True)
@bot.channel_post_handler(func=lambda m: True)
def on_text(m):
    text = getattr(m, "text", "") or ""
    if not text or text.startswith("/"):
        return
    bot.send_chat_action(m.chat.id, "typing")
    user_id, user_name = register_user(m)
    reply(m, command.handle_natural_language(text, user_name, user_id=user_id))


if __name__ == "__main__":
    database.init_db()
    setup_bot_commands()
    
    import brain
    brain.stats.alert_callback = lambda msg: safe_send(CHAT_ID, msg)
    
    threading.Thread(target=auto_news_job, daemon=True).start()
    threading.Thread(target=major_news_alert_job, daemon=True).start()
    threading.Thread(target=market_report_job, daemon=True).start()
    notify_status("online")

    while True:
        try:
            bot.infinity_polling(timeout=POLLING_TIMEOUT, long_polling_timeout=LONG_POLLING_TIMEOUT)
        except Exception as exc:
            logging.error("Telegram polling failed: %s", exc)
            time.sleep(10)
