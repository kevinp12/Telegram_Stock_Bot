import pandas as pd
import numpy as np

from . import data_loader

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """實作機構級精確度的中長線策略：50/200 均線趨勢 + 20日高點突破 + 大盤濾網 + 波動率控位。"""
    if df.empty or len(df) < 200:
        return df

    # --- 1. 指標準備 ---
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_150'] = df['Close'].rolling(window=150).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['20_High'] = df['Close'].rolling(window=20).max()
    
    # 計算 ATR 用於倉位控管
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    df['ATR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean()
    df['Rolling_Max_20'] = df['High'].rolling(20).max()

    # 長線出場訊號：放寬停利與趨勢破壞判定，避免強勢股震盪洗盤過早下車。
    cond_exit_trend_broken = (df['Close'] < df['SMA_150']).rolling(3).sum() == 3
    cond_exit_trailing = df['Close'] < (df['Rolling_Max_20'] - 3 * df['ATR'])
    cond_overextended = df['Close'] > (df['SMA_150'] * 1.3)
    cond_exit_profit_protect = cond_overextended & (df['Close'] < df['SMA_50'])
    df['Sell_Signal'] = cond_exit_trend_broken | cond_exit_trailing | cond_exit_profit_protect
    
    # 抓取大盤濾網數據 (SPY)
    spy_df = data_loader.get_market_benchmark(years=12) # 多抓一點確保對齊
    df['Market_Filter'] = True
    if not spy_df.empty:
        # 對齊索引
        spy_filter = spy_df['Close'] > spy_df['SMA_200']
        df['Market_Filter'] = spy_filter.reindex(df.index, method='ffill').fillna(True)

    # --- 2. 模擬執行 (隔日開盤成交模型) ---
    df['Position_Size'] = 0.0 # 0.0 到 1.0 之間
    df['Execution_Price'] = np.nan
    
    in_position = False
    fee_rate = 0.001  # 基本手續費 0.1%
    
    for i in range(200, len(df) - 1):
        current_close = df.iat[i, df.columns.get_loc('Close')]
        sma_50 = df.iat[i, df.columns.get_loc('SMA_50')]
        sma_200 = df.iat[i, df.columns.get_loc('SMA_200')]
        high_20 = df.iat[i-1, df.columns.get_loc('20_High')]
        market_ok = df.iat[i, df.columns.get_loc('Market_Filter')]
        
        next_open = df.iat[i+1, df.columns.get_loc('Open')]
        
        if not in_position:
            # 進場條件：50MA > 200MA + 20日突破 + 大盤濾網
            if sma_50 > sma_200 and current_close >= high_20 and market_ok:
                in_position = True
                exec_price = next_open * 1.0008
                
                # --- 波動率部位控管 (Volatility Position Sizing) ---
                # 目標：每筆交易風險固定在總資產的 1% (假設止損距離為 2 * ATR)
                # 倉位 = (總資產 * 1%) / (2 * ATR)
                # 這裡簡化為：如果 ATR/價格 很高 (波動大)，倉位就低。
                # 基準：如果日波動 2%，倉位 100%；如果日波動 4%，倉位 50%。
                atr_pct = (df.iat[i, df.columns.get_loc('ATR')] / current_close) if current_close > 0 else 0.02
                pos_size = min(1.0, 0.02 / atr_pct) if atr_pct > 0 else 1.0
                
                df.iat[i+1, df.columns.get_loc('Position_Size')] = pos_size
                df.iat[i+1, df.columns.get_loc('Execution_Price')] = exec_price
        else:
            # 出場條件：雙重長線出場邏輯；大盤濾網只限制新進場，不再直接砍倉。
            if df.iat[i, df.columns.get_loc('Sell_Signal')]:
                in_position = False
                exec_price = next_open * 0.9992
                df.iat[i+1, df.columns.get_loc('Position_Size')] = 0
                df.iat[i+1, df.columns.get_loc('Execution_Price')] = exec_price
            else:
                df.iat[i+1, df.columns.get_loc('Position_Size')] = df.iat[i, df.columns.get_loc('Position_Size')]
                
    # --- 3. 計算報酬率 ---
    # 策略每日回報 = 倉位大小 * (今日收盤 / 昨日收盤 - 1)
    # 注意：倉位大小會影響 MDD，因為沒買滿時回撤也會按比例縮小
    df['Strategy_Return'] = df['Position_Size'].shift(1) * df['Close'].pct_change()
    
    # 處理成交日的摩擦成本
    trades = (df['Position_Size'] != df['Position_Size'].shift(1).fillna(0))
    df['Strategy_Return'] = df['Strategy_Return'] - (trades * fee_rate)
    
    df.fillna(0, inplace=True)
    # 為了兼容舊的計算邏輯，我們將 Position_Size 轉換為二進制 Position 供 metrics 使用
    df['Position'] = (df['Position_Size'] > 0).astype(int)
    
    return df
