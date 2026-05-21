module.exports = {
  apps: [{
    name: "gemini_stock_bot",
    script: "./main_bot.py",
    interpreter: "python3",
    // 記憶體防禦：當程式使用超過 800MB 時自動重啟，保留主機安全緩衝
    max_memory_restart: "800M",
    autorestart: true,
    // 每天美股休市後自動重啟，釋放長時間碎片化記憶體
    cron_restart: "0 5 * * *",
    // 效能優化環境變數
    env: {
      // 使用系統分配器，減少記憶體碎片
      PYTHONMALLOC: "malloc",
      // 確保日誌即時輸出
      PYTHONUNBUFFERED: "1",
      // 提示 glibc 及時回收空閒記憶體，降低 RSS 長時間膨脹
      MALLOC_TRIM_THRESHOLD_: "131072",
      // 如果您的 .env 在不同位置，可以在這裡指定
      // DOTENV_CONFIG_PATH: "./.env"
    },
    // 異常重啟保護：崩潰後採退避重試
    exp_backoff_restart_delay: 200,
    // 限制重啟次數的記錄時間
    restart_delay: 3000
  }]
}
