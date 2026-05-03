# 🎯 美股顧問・百萬作戰指揮室 (Millionaire Command Center)

[![Stock Bot](https://img.shields.io/badge/美股顧問-百萬作戰-blue?style=for-the-badge&logo=telegram)]()
[![Version](https://img.shields.io/badge/Version-v.26.5.3-green?style=for-the-badge)](https://github.com/kevinp12/Telegram_Stock_Bot)
[![Python](https://img.shields.io/badge/Python-3.9+-yellow?style=for-the-badge&logo=python)](https://www.python.org/)

這是一個專為美股投資者量身打造的 **Telegram 私人投資副官**。具備頂尖 AI 算力支持，結合即時市場數據、量化指標、智慧新聞分析與自動化匯報功能。

---

## 🚀 核心戰術功能

### 📊 1. 全景儀表板 (`/now`)
*   **宏觀即時觀測**：標普500、納斯達克、黃金、原油、比特幣與 VIX 恐慌指數。
*   **帳戶總損益**：整合持股市值，計算未實現損益與百分比。
*   **AI 戰術短評**：由 Gemini 深度分析當前量價關係，給出具體交易建議。

### 📉 2. 專業量化分析 (`/tech`) `NEW`
*   **核心儀表板**：EMA 均線系統、ATR 波動風險、RSI 強弱、MACD 動能、TD9 反轉序列、VWAP 機構成本。
*   **主力籌碼追蹤**：偵測爆量與機構建倉/倒貨訊號。
*   **進攻指標**：綜合多空評級（大買 / 觀察 / 大賣）。
*   **自動化策略**：生成包含進場位、停損位與防守位的完整交易計畫。

### 📋 3. 資產與雷達管理 (`/list`, `/buy`, `/sell`, `/watch`)
*   **FIFO 會計系統**：自動計算分批買入成本與已實現損益。
*   **雷達監控**：批量新增/移除監控標的，系統將優先推送相關情報。
*   **分頁顯示**：持股明細支持翻頁功能，應對大量持股需求。

### 📰 4. 智慧情報系統 (`/news`, `/theme`, `/ask`)
*   **智慧路由**：自動識別個股、財報或宏觀新聞，切換至最合適的分析人格。
*   **產業趨勢 (`/theme`)**：針對 AI、半導體、核能等主題生成深度產業速報。
*   **Pro 深度諮詢 (`/ask`)**：針對特定個股問題，啟動最大算力的戰術判讀。
*   **自動推播**：每 20 分鐘隨機推播持股、監控或宏觀的重要情報。

### 💹 5. 數值精確規範 `OPTIMIZED`
*   **精確四捨五入**：所有數值（EPS、P/E、股價、百分比）均採用 `ROUND_HALF_UP` 邏輯計算。
*   **統一格式**：所有財務數據抓取至小數點後兩位，確保報告嚴謹與美觀。

---

## 🛠️ 系統監控與維護

### 🔍 狀態報告 (`/status`)
*   **AI 流量統計**：顯示今日 Token 消耗、配額上限與預警進度。
*   **消耗統計**：自動計算平均、最小與最大 Token 消耗量。
*   **大腦狀態**：顯示當前主模型、備援模型清單與成功調用次數。
*   **硬體資源**：即時顯示 CPU、RAM、硬碟與系統運行時間。

### 🔒 管理者選單 (`/op`)
*   **模型切換**：`/op model [flash|pro]` 即時切換 AI 核心。
*   **日誌審計**：`/op log` 讀取最近運行的美觀結構化日誌（含 Token 細項與研究網址）。
*   **配額查詢**：`/op quota` 視覺化 Token 使用進度。

---

## 📦 專案結構

```text
├── main_bot.py      # Telegram 入口、指令註冊與背景任務
├── command.py       # 業務邏輯流程、報表生成
├── ai_core.py       # AI 思考層、人格設定、Prompt 模板
├── brain.py         # Gemini API 串接、Fallback 機制、審計日誌
├── tech_indicators.py # 量化指標計算核心 (EMA, ATR, TD9...)
├── market_api.py    # Yahoo Finance, Finnhub, NewsAPI 採集
├── database.py      # SQLite 持久化、持股紀錄、Token 計數
├── frame.py         # 視覺排版與 Emoji 格式集中管理
├── utils.py         # 核心工具類 (精確四捨五入、數值格式化)
└── config.py        # 環境變數與全局設定
```

---

## ⚙️ 快速部署

### 1. 環境準備
```bash
git clone https://github.com/your_repo/gemini_stock_bot.git
cd gemini_stock_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置環境變數 (`.env`)
```env
TELEGRAM_TOKEN=123456789:ABCDEF...
CHAT_ID=你的_Telegram_Chat_ID
NEWS_API_KEY=你的_NewsAPI_Key
FINNHUB_KEY=你的_Finnhub_Key
GEMINI_API_KEY=你的_Gemini_API_Key
DAILY_TOKEN_LIMIT=500000
```

### 3. 啟動與維護
使用 systemd 確保 24/7 運行：
```bash
sudo systemctl enable gemini-bot
sudo systemctl start gemini-bot
```

---

## ⚖️ 免責聲明
本工具僅供資訊參考與學術研究，**不構成任何投資建議**。投資美股具有高度風險，請在交易前諮詢專業金融顧問。AI 產生的所有內容可能存在偏差，請務必搭配原文網址查證。
