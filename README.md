# 🎯 美股顧問・百萬作戰指揮室

這是一個為 User 量身打造的 Telegram 美股投資副官機器人，具備 AI 深度分析、即時新聞推播與伺服器監控功能。

## 核心功能

1.  **即時全景 (`/now`)**：宏觀指數、帳戶損益與 AI 戰術短評。
2.  **資產管理 (`/list`, `/buy`, `/sell`)**：FIFO 先進先出損益計算，追蹤持股成本。
3.  **智能新聞 (`/news`)**：
    *   從指定頂級來源（金十、Reuters, Bloomberg, WSJ 等）抓取資訊。
    *   每 20 分鐘自動推播重要宏觀、持股或觀察清單新聞。
    *   AI 自動評分（1~5 顆星）並提供繁體中文摘要。
4.  **定時匯報**：
    *   **開盤預備 (開盤前 30 分)**：市場全景、帳戶損益與今日焦點新聞。
    *   **收盤結算 (收盤後 30 分)**：今日持股明細、當日損益結算與市場總結。
    *   自動偵測夏令/冬令時間（美東時間）。
5.  **系統監控 (`/status`)**：
    *   **AI 流量**：監控每日 Token 使用量，設有 80/90/100% 預警通知。
    *   **大腦狀態**：顯示當前使用的 Gemini 模型與備援清單。
    *   **伺服器資源**：顯示 CPU、RAM、硬碟使用率與機器人運行時間 (Uptime)。
6.  **開關機通報**：機器人啟動與下線時自動發送通知。

## 專案結構

- `main_bot.py`：Telegram 入口、事件分發、背景任務、開關機通報。
- `command.py`：所有指令流程實作與報表生成。
- `ai_core.py`：AI 顧問人格設定、新聞摘要格式化。
- `brain.py`：Gemini API 串接、Token 流量監控、模型 Fallback 機制。
- `market_api.py`：Yahoo Finance、NewsAPI、Finnhub 多來源數據採集。
- `database.py`：SQLite 資料持久化、持股紀錄、Token 計數、Watchlist。
- `frame.py`：Telegram 訊息排版與顯示格式集中管理。
- `config.py`：環境變數讀取與全局設定。

## 部署與安裝 (GCP VM)

### 1. 安裝環境
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 設定 .env
請參考以下範例建立 `.env` 檔案：
```env
TELEGRAM_TOKEN=你的_TOKEN
CHAT_ID=你的_CHAT_ID
NEWS_API_KEY=你的_NewsAPI_Key
FINNHUB_KEY=你的_Finnhub_Key
GEMINI_API_KEY=你的_Gemini_API_Key
DAILY_TOKEN_LIMIT=500000
```

### 3. 自動維護 (GCP systemd)
建立 `/etc/systemd/system/gemini-bot.service`：
```ini
[Unit]
Description=Gemini Stock Bot
After=network.target

[Service]
WorkingDirectory=/path/to/your/bot
ExecStart=/usr/bin/python3 main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
執行：`sudo systemctl start gemini-bot`

## 維護指令
- **查看狀態**：`/status`
- **查看手冊**：`/help`
- **查看 Log**：`journalctl -u gemini-bot -f`
