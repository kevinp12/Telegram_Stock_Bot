module.exports = {
  apps : [{
    name: "gemini-stock-bot",
    script: "./main_bot.py",
    interpreter: "python3",
    // 記憶體防禦：當程式使用超過 700MB 時自動重啟，防止主機死機
    max_memory_restart: "700M",
    // 效能優化環境變數
    env: {
      // 使用系統分配器，減少記憶體碎片
      PYTHONMALLOC: "malloc",
      // 確保日誌即時輸出
      PYTHONUNBUFFERED: "1",
      // 如果您的 .env 在不同位置，可以在這裡指定
      // DOTENV_CONFIG_PATH: "./.env"
    },
    // 異常重啟保護：如果程式崩潰，等待 100ms 再重啟，並隨失敗次數增加等待時間
    exp_backoff_restart_delay: 100,
    // 限制重啟次數的記錄時間
    restart_delay: 3000
  }]
}
