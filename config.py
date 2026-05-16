"""config.py
全局設定檔：優先讀取 .env / 環境變數。
請不要把真正 API key 寫進 GitHub。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# 關鍵：強制載入專案根目錄的 .env 檔案
load_dotenv(BASE_DIR / ".env", override=True)

BOT_START_TIME = datetime.now()

# Paths
DB_NAME = os.getenv("DB_NAME", str(BASE_DIR / "sniper_trades.db"))
# CJK Font directory (for GCP/Docker portable font loading)
CJK_FONT_DIR = os.getenv("CJK_FONT_DIR", str(BASE_DIR / "fonts")).strip()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

# Data APIs
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip()
BLS_API_KEY = os.getenv("BLS_API_KEY", "").strip()

# Gemini
# 兼容 README 舊版範例的 GOOGLE_API_KEY，同時保留正式 GEMINI_API_KEY。
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-3.1-flash-lite").strip()
GEMINI_PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-3.1-pro").strip()
GEMINI_AUDIT_LOG_PATH = BASE_DIR / ".gemini_audit.log"

# Fallbacks：基本對話優先 Flash；深度對話優先 Pro。
# 2026年5月更新：納入 3.1, 3.0, 2.5 全系列。
FLASH_FALLBACK_MODELS = [
    GEMINI_FLASH_MODEL,
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash",
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-2.0-flash-lite",  # 已進入過渡期/404
]

PRO_FALLBACK_MODELS = [
    GEMINI_PRO_MODEL,
    "gemini-3.1-pro",
    "gemini-3-pro",
    "gemini-2.5-pro",
    "gemini-pro-latest",
    "gemini-2.0-pro-exp-02-05",
    "gemini-1.5-pro",
    "gemini-3.1-pro-preview",
    "gemini-2.0-flash-thinking-exp-01-21",
]

# Telegram settings
MAX_TELEGRAM_MESSAGE_LENGTH = int(os.getenv("MAX_TELEGRAM_MESSAGE_LENGTH", "3500"))
POLLING_TIMEOUT = int(os.getenv("POLLING_TIMEOUT", "40"))
LONG_POLLING_TIMEOUT = int(os.getenv("LONG_POLLING_TIMEOUT", "15"))
AUTO_NEWS_INTERVAL_SECONDS = int(os.getenv("AUTO_NEWS_INTERVAL_SECONDS", "28800"))
SNIPER_CHECK_INTERVAL = int(os.getenv("SNIPER_CHECK_INTERVAL", "300"))  # 預設 5 分鐘，符合 Yahoo API 頻率限制

# 自動更新版本資訊 (格式: v.YY.M.D)
_now = datetime.now()
VERSION = f"v.{_now.strftime('%y')}.{_now.month}.{_now.day}"

# 流量監控 (預設 50萬 Token/日)
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "500000"))
