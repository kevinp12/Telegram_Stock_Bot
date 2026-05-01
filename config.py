"""config.py
全局設定檔：優先讀取 .env / 環境變數。
請不要把真正 API key 寫進 GitHub。
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

BOT_START_TIME = datetime.now()

try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent
    load_dotenv(BASE_DIR / ".env")
except Exception:
    BASE_DIR = Path(__file__).resolve().parent

# Paths
DB_NAME = os.getenv("DB_NAME", str(BASE_DIR / "sniper_trades.db"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

# Data APIs
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash").strip()
GEMINI_PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro").strip()
GEMINI_AUDIT_LOG_PATH = BASE_DIR / ".gemini_audit.log"

# Fallbacks：基本對話優先 Flash；深度對話優先 Pro。
FLASH_FALLBACK_MODELS = [
    GEMINI_FLASH_MODEL,
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

PRO_FALLBACK_MODELS = [
    GEMINI_PRO_MODEL,
    "gemini-pro-latest",
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
]

# Telegram settings
MAX_TELEGRAM_MESSAGE_LENGTH = int(os.getenv("MAX_TELEGRAM_MESSAGE_LENGTH", "3500"))
POLLING_TIMEOUT = int(os.getenv("POLLING_TIMEOUT", "40"))
LONG_POLLING_TIMEOUT = int(os.getenv("LONG_POLLING_TIMEOUT", "15"))
AUTO_NEWS_INTERVAL_SECONDS = int(os.getenv("AUTO_NEWS_INTERVAL_SECONDS", "28800"))

# 自動更新版本資訊 (格式: v.YY.M.D)
_now = datetime.now()
VERSION = f"v.{_now.strftime('%y')}.{_now.month}.{_now.day}"

# 流量監控 (預設 50萬 Token/日)
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "500000"))
