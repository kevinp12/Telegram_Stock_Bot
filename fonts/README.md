# Portable CJK Fonts (for GCP / Docker / Linux)

請把可商用授權的中文字型放在此目錄，讓 bot 在沒有系統中文字型的環境（例如 GCP）也能正常渲染中文圖表。

建議字型：

- `NotoSansCJKtc-Regular.otf`（優先）
- `NotoSansTC-Regular.ttf`

載入優先順序：

1. 環境變數 `CJK_FONT_DIR` 指定路徑
2. `./fonts`
3. `./assets/fonts`
4. 系統字型 fallback

> 若使用 Docker / GCP，請確認此資料夾有被一併部署。