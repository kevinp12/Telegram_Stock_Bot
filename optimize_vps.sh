#!/bin/bash

echo "🚀 開始優化系統記憶體防線..."

# 1. 如果已經有 swapfile 則先移除 (確保重新設定)
sudo swapoff /swapfile 2>/dev/null
sudo rm /swapfile 2>/dev/null

# 2. 建立 2GB Swap 檔案 (對應 1GB RAM 最安全的比例)
echo "📦 正在建立 2GB Swap 空間..."
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 3. 設定開機自動掛載
if ! grep -q "/swapfile" /etc/fstab; then
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 4. 優化核心參數
echo "🛠️ 正在優化 Linux 核心參數..."
# swappiness=20: 盡量用實體 RAM，剩餘 20% 才開始用 Swap
sudo sysctl vm.swappiness=20
sudo sysctl vm.vfs_cache_pressure=50

# 寫入設定檔確保重啟後生效
sudo sed -i '/vm.swappiness/d' /etc/sysctl.conf
sudo sed -i '/vm.vfs_cache_pressure/d' /etc/sysctl.conf
echo "vm.swappiness=20" | sudo tee -a /etc/sysctl.conf
echo "vm.vfs_cache_pressure=50" | sudo tee -a /etc/sysctl.conf

# 5. 清理系統日誌空間
sudo journalctl --vacuum-size=100M

echo "✅ 優化完成！您的系統現在有 1GB RAM + 2GB Swap 防線。"
echo "📊 目前記憶體狀態："
free -h
