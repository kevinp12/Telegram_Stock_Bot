import pandas as pd
import numpy as np

from . import data_loader

def calculate_tech_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    將 /tech 指標升級為「波段趨勢策略」：
    保留精確進場，但改用 10-EMA 追蹤止損，並加入大盤濾網與部位控管。
    """
    if len(df) < 50:
        return pd.DataFrame()

    # 1. 指標計算
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    df['ATR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean()
    
    # RSI 進場過濾
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['FVG_Bull'] = df['Low'] > df['High'].shift(2)
    
    # 大盤濾網
    spy_df = data_loader.get_market_benchmark(years=12)
    df['Market_Filter'] = True
    if not spy_df.empty:
        spy_filter = spy_df['Close'] > spy_df['SMA_200']
        df['Market_Filter'] = spy_filter.reindex(df.index, method='ffill').fillna(True)

    # --- 進場邏輯 ---
    cond_ema_trend = (df['EMA20'] > df['EMA50']) & (df['Close'] > df['EMA20'])
    cond_fvg = df['FVG_Bull'].rolling(5).max() > 0
    cond_rsi_safe = df['RSI'] < 70
    
    df['Raw_Buy_Signal'] = cond_ema_trend & cond_fvg & cond_rsi_safe & df['Market_Filter']
    
    # --- 執行模擬 (10-EMA 追蹤止損 + 部位控管) ---
    df['Position_Size'] = 0.0
    in_position = False
    
    for i in range(len(df) - 1):
        market_ok = df.iat[i, df.columns.get_loc('Market_Filter')]
        
        if not in_position:
            if df.iat[i, df.columns.get_loc('Raw_Buy_Signal')]:
                in_position = True
                # 波動率部位控管
                atr_pct = (df.iat[i, df.columns.get_loc('ATR')] / df.iat[i, df.columns.get_loc('Close')]) if df.iat[i, df.columns.get_loc('Close')] > 0 else 0.02
                pos_size = min(1.0, 0.02 / atr_pct) if atr_pct > 0 else 1.0
                df.iat[i+1, df.columns.get_loc('Position_Size')] = pos_size
        else:
            cond_exit_trend = df.iat[i, df.columns.get_loc('Close')] < df.iat[i, df.columns.get_loc('EMA10')]
            if cond_exit_trend or not market_ok:
                in_position = False
                df.iat[i+1, df.columns.get_loc('Position_Size')] = 0
            else:
                df.iat[i+1, df.columns.get_loc('Position_Size')] = df.iat[i, df.columns.get_loc('Position_Size')]
                
    # --- 計算報酬與成本 ---
    fee_rate = 0.0012 
    df['Strategy_Return'] = df['Position_Size'].shift(1) * df['Close'].pct_change()
    trades = (df['Position_Size'] != df['Position_Size'].shift(1).fillna(0))
    df['Strategy_Return'] = df['Strategy_Return'] - (trades * fee_rate)
    
    df.fillna(0, inplace=True)
    df['Position'] = (df['Position_Size'] > 0).astype(int)
    return df
