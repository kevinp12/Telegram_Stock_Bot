import yfinance as yf
import pandas as pd
import numpy as np
import logging

def get_long_term_data(ticker: str, years: int = 10) -> pd.DataFrame:
    """獲取長達 10 年的歷史資料，並計算長線指標。"""
    try:
        # 使用 auto_adjust=True 自動處理股息與拆股，這是回測準確的關鍵
        df = yf.download(ticker, period=f"{years}y", interval="1d", progress=False, auto_adjust=True)
    except Exception as e:
        logging.error(f"yfinance download error for {ticker}: {e}")
        return pd.DataFrame()
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    if df.empty or 'Close' not in df.columns or len(df) < 50:
        return pd.DataFrame()
        
    # 確保數據類型正確
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    df.dropna(subset=['Close', 'Volume'], inplace=True)
    
    # 計算長線均線 (判斷牛熊)
    df['SMA_50'] = df['Close'].rolling(50).mean()
    df['SMA_150'] = df['Close'].rolling(150).mean()
    df['SMA_200'] = df['Close'].rolling(200).mean()
    
    # 計算成交量均線
    df['VOL_MA20'] = df['Volume'].rolling(20).mean()
    
    # 計算 ATR (Average True Range) - 用於風險管理
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    
    # 計算 RSI (Relative Strength Index) - 判斷過熱程度
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 標記 FVG (Fair Value Gap) - 日線級別
    # Bullish FVG: Low[i] > High[i-2]
    df['FVG_Bull'] = df['Low'] > df['High'].shift(2)
    # Bearish FVG: High[i] < Low[i-2]
    df['FVG_Bear'] = df['High'] < df['Low'].shift(2)
    
    # 移除包含 NaN 的初期數據 (主要是 SMA_200 產生的)
    # 但如果資料不足 200 天，SMA_200 會全是 NaN，dropna 會清空所有資料
    # 我們至少需要 50 天資料來做一些基礎分析，若不足 200 天則只做能做的
    if len(df) > 200:
        df.dropna(subset=['SMA_200'], inplace=True)
    elif len(df) > 50:
        df.dropna(subset=['SMA_50'], inplace=True)
    else:
        # 資料太少，直接回傳空
        return pd.DataFrame()
        
    return df

def get_market_benchmark(years: int = 10) -> pd.DataFrame:
    """獲取大盤標竿 (SPY) 數據用於濾網。"""
    try:
        df = yf.download("SPY", period=f"{years}y", interval="1d", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df['SMA_200'] = df['Close'].rolling(200).mean()
        return df
    except Exception:
        return pd.DataFrame()
