<div align="center">

# 🎯 Gemini Stock Bot | 百萬作戰指揮室
---
> *您的專屬 AI 投資副官*

[![Status](https://img.shields.io/badge/系統狀態-運行中-brightgreen?style=for-the-badge&logo=appveyor)]()
[![AI](https://img.shields.io/badge/AI_引擎-Gemini_Flash/Pro-orange?style=for-the-badge&logo=google-gemini)]()
[![Architecture](https://img.shields.io/badge/架構-模組化設計-blue?style=for-the-badge&logo=python)]()

</div>

---

> 🚀 **系統使命**：為美股投資者提供最冷靜的 AI 戰術分析、即時量化指標與精準的市場情報決策。

---

## 🛰️ 系統架構流向 (Architectural Flow)

```mermaid
graph TD
    User((使用者)) -->|輸入指令| Bot[main_bot.py]
    Bot -->|路由解析| Command[command.py]
    
    subgraph 分析引擎
    Command --> Indicators[tech_indicators.py]
    Command --> MarketAPI[market_api.py]
    Command --> AICore[ai_core.py]
    end
    
    AICore --> Brain[brain.py]
    Brain -->|呼叫| AI((Google Gemini AI))
    
    Command --> DB[(database.py - SQLite)]
    Command --> Frame[frame.py]
    
    Bot -->|顯示回報| User
```

---

## 🛠️ 模組結構 (Modules Overview)

<details>
<summary><b>📂 點擊查看核心架構邏輯</b></summary>

| 模組 | 職責 |
| :--- | :--- |
| `main_bot.py` | 系統入口，Telegram API 對接、自動化任務排程。 |
| `command.py` | 業務邏輯樞紐，處理所有指令行為與報表生成。 |
| `ai_core.py` | AI 決策核心，轉換原始資料為戰術分析與投資建議。 |
| `brain.py` | Gemini API 底層通訊，處理自動 Fallback、Token 統計與日誌。 |
| `tech_indicators.py` | 量化分析運算 (均線、動能、TD9、斐波那契)。 |
| `market_api.py` | 市場資訊採集 (Yahoo Finance, Finnhub, NewsAPI)。 |
| `database.py` | 資料持久化，記錄持股、帳務與 Token 使用。 |
| `frame.py` | 排版與視覺格式中心，優化 Telegram 介面體驗。 |

</details>

---

## 📟 指令速查表 (Command Cheat Sheet)

### 📈 技術分析與戰術
*   `/tech [代號]` — 產出專業量化儀表板 (EMA, MACD, TD9, VWAP)。
*   `/tech compare [A] [B]` — 橫向對比分析，給出 AI 交易建議。
*   `/fin [代號]` — 個股財報、EPS 與核心估值。
*   `/fin compare [A] [B]` — QoQ 季增長對比，判斷財報基本面。
*   `/ask [代號] [問題]` — Pro 級 AI 深度戰術諮詢。

### 📰 市場情報
*   `/news` — 執行全市場新聞摘要。
*   `/now` — 即時盤勢全景、總損益與 AI 短評。
*   `/theme [主題]` — 產業趨勢速報 (AI, 半導體, 核能)。

### 📋 資產管理
*   `/list` — 持股明細與盈虧分析。
*   `/buy /sell` — 交易紀錄 (FIFO 自動結算)。
*   `/watch [add/del/list]` — 管理關注雷達名單。

---

## ⚙️ 維護與自動化

> 🤖 **智能自動推播**：每 **1 小時** 自動推送情報 (開盤時間 `09:30-16:00 ET` 暫停)。
> 🧹 **系統自癒**：每 **4 天** 自動執行日誌清理，確保效能。
> 💎 **配額警報**：Token 消耗達到 80%/90%/100% 時，自動推送預警。

### 🕵️ 隱藏功能指令 (`/op`)
*   `/op model [flash\|pro]` — 切換 AI 模型核心。
*   `/op log` — 查看最近 40 筆審計日誌。
*   `/op log clear` — 手動清除日誌。
*   `/op quota` — 查詢今日 Token 使用進度。

---

<div align="center">

**⚖️ 免責聲明**：本工具僅供學術研究，**不構成任何投資建議**。投資美股具有高度風險。

</div>
