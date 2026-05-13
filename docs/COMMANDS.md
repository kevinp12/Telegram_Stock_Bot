# 📘 指令維運手冊（COMMANDS）

本文件給開發者/維運者快速確認：
- 指令用途
- 主要程式入口
- 常見排錯方向

---

## 1. 使用者指令

| 指令 | 功能 | 主要入口 |
|---|---|---|
| `/now` | 市場總覽與 AI 短評 | `main_bot.on_now` → `command.cmd_now` |
| `/risk` | 風險儀表板 | `main_bot.on_risk` → `command.cmd_risk` |
| `/marco` | 宏觀雷達（CPI/PCE/PPI/NFP...） | `main_bot.on_marco` → `command.cmd_marco` |
| `/tech` | 技術與 SMC | `main_bot.on_tech` → `command.cmd_tech` |
| `/fin` | 財務分析 | `main_bot.on_fin` → `command.cmd_fin` |
| `/news` | 新聞與 AI 解讀 | `main_bot.on_news` → `command.cmd_news` |
| `/theme` | 主題趨勢快報 | `main_bot.on_theme` → `command.cmd_theme` |
| `/whale` | 內部人/機構追蹤 | `main_bot.on_whale` → `command.cmd_whale` |
| `/ask` | 深度問答 | `main_bot.on_ask` → `command.cmd_ask` |
| `/buy` `/sell` `/list` | 持倉管理 | `command.cmd_buy/sell/list` |
| `/watch` `/sweep` | 監控清單管理 | `command.cmd_watch/sweep` |
| `/bc` | 自動推播設定 | `command.cmd_bc` |
| `/status` | 系統狀態 | `command.cmd_status` |
| `/quota` | Token 配額 | `command.cmd_quota` |
| `/help` | 指令教學頁 | `frame.help_text` |

---

## 2. 管理者隱藏指令

| 指令 | 用途 |
|---|---|
| `/op help` | 查看隱藏指令 |
| `/op model flash|pro` | 切換模型偏好 |
| `/op user list` | 查看使用者清單 |
| `/op user log [id/名稱]` | 查看使用者互動紀錄 |
| `/op log` | 查看審計日誌 |
| `/op log clear` | 清除審計日誌 |

---

## 3. 背景任務

| 任務 | 說明 | 入口 |
|---|---|---|
| auto_news_job | 週期推播 | `main_bot.auto_news_job` |
| major_news_alert_job | watchlist 重大新聞提醒 | `main_bot.major_news_alert_job` |
| market_report_job | 開盤前/收盤後報告 | `main_bot.market_report_job` |
| sniper_alert_job | sweep 狙擊監控 | `main_bot.sniper_alert_job` |
| log_cleanup_job | 日誌清理 | `main_bot.log_cleanup_job` |

---

## 4. 排錯建議

1. `/status` 先看核心連線與最近錯誤碼
2. 檢查 `.env`：`TELEGRAM_TOKEN / GEMINI_API_KEY / NEWS_API_KEY / FRED_API_KEY / BLS_API_KEY`
3. 若是宏觀資料異常：優先檢查 `market_api.get_macro_core_snapshot()`
4. 若是指令沒反應：確認 `main_bot.py` 對應 handler 是否存在
