"""tech_indicators.py
量化指標計算核心，提供 EMA, ATR, RSI, MACD, OBV, TD9, Fibonacci, POC 等分析功能。
"""
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Any
from utils import safe_round

def calculate_poc(df: pd.DataFrame, bins: int = 50) -> float:
    """
    計算控制點 (Point of Control, POC)：指定區間內成交量最大的價格位。
    """
    if df.empty or len(df) < 5:
        return 0.0
    
    # 取最近一個月的數據 (約 22 個交易日)
    recent_df = df.tail(30).copy()
    if recent_df.empty:
        return 0.0

    price_min = recent_df['Low'].min()
    price_max = recent_df['High'].max()
    
    if price_max == price_min:
        return price_min

    # 建立價格區間 (Bins)
    bin_size = (price_max - price_min) / bins
    if bin_size <= 0:
        return price_min

    # 依照成交量分佈到價格區間
    recent_df['bin'] = ((recent_df['Close'] - price_min) / bin_size).astype(int).clip(0, bins - 1)
    
    # 依照 bin 累計成交量
    volume_profile = recent_df.groupby('bin')['Volume'].sum()
    
    if volume_profile.empty:
        return recent_df['Close'].iloc[-1]

    poc_bin = volume_profile.idxmax()
    poc_price = price_min + (poc_bin * bin_size) + (bin_size / 2)
    
    return safe_round(poc_price, 2)

def calculate_indicators(symbol: str) -> dict[str, Any]:
    """
    計算指定股票的所有量化指標。
    """
    symbol = symbol.upper()
    try:
        # 抓取 1 年數據以確保有足夠樣本計算 EMA 200
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y", interval="1d")
        
        if df.empty or len(df) < 20:
            return {"error": "數據不足，無法進行分析"}

        # 1. EMA 系統
        df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
        df['EMA60'] = df['Close'].ewm(span=60, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        last_price = df['Close'].iloc[-1]
        ema21 = df['EMA21'].iloc[-1]
        ema60 = df['EMA60'].iloc[-1]
        ema200 = df['EMA200'].iloc[-1]
        
        if last_price > ema21 > ema60 > ema200:
            ema_status = "多頭排列 (價>21>60>200)"
        elif last_price < ema21 < ema60 < ema200:
            ema_status = "空頭排列 (價<21<60<200)"
        else:
            ema_status = "均線糾結 / 趨勢不明"

        # 2. ATR (14)
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR14'] = tr.rolling(window=14).mean()
        atr = df['ATR14'].iloc[-1]

        # 3. RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI14'] = 100 - (100 / (1 + rs))
        rsi = df['RSI14'].iloc[-1]

        # 4. MACD (12, 26, 9)
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['Hist'] = df['MACD'] - df['Signal']
        
        macd_val = df['MACD'].iloc[-1]
        signal_val = df['Signal'].iloc[-1]
        hist_val = df['Hist'].iloc[-1]
        prev_hist = df['Hist'].iloc[-2]
        
        macd_status = ""
        if macd_val > signal_val:
            macd_status = "MACD金叉"
        else:
            macd_status = "MACD死叉"
            
        if hist_val > prev_hist:
            macd_status += " (動能增強)"
        else:
            macd_status += " (動能減弱)"

        # 5. VOL & OBV
        df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
        vol_last = df['Volume'].iloc[-1]
        vol_avg20 = df['Volume'].tail(20).mean()
        vol_ratio = vol_last / vol_avg20 if vol_avg20 > 0 else 0
        
        # 6. TD9 (Tom DeMark Sequential)
        df['TD_Buy'] = (df['Close'] < df['Close'].shift(4)).astype(int)
        df['TD_Sell'] = (df['Close'] > df['Close'].shift(4)).astype(int)
        
        buy_count = 0
        sell_count = 0
        for i in range(len(df)-1, -1, -1):
            if df['TD_Buy'].iloc[i] == 1:
                buy_count += 1
            else:
                break
        for i in range(len(df)-1, -1, -1):
            if df['TD_Sell'].iloc[i] == 1:
                sell_count += 1
            else:
                break
        
        td_status = "序列進行中"
        if buy_count > 0:
            if buy_count == 9:
                td_status = "🔥 買入結構 TD9 (強反轉預期)"
            elif buy_count > 9:
                td_status = f"買入結構 TD9+ ({buy_count})"
            else:
                td_status = f"買入結構 TD{buy_count}"
        elif sell_count > 0:
            if sell_count == 9:
                td_status = "💀 賣出結構 TD9 (強反轉預期)"
            elif sell_count > 9:
                td_status = f"賣出結構 TD9+ ({sell_count})"
            else:
                td_status = f"賣出結構 TD{sell_count}"
        else:
            td_status = "TD 序列中立"

        # 7. Fibonacci (這裡簡化為最近一季的高低點)
        high_3mo = df['High'].tail(60).max()
        low_3mo = df['Low'].tail(60).min()
        range_3mo = high_3mo - low_3mo
        target_1 = high_3mo + range_3mo * 1.0
        target_1618 = high_3mo + range_3mo * 1.618

        # 8. VWAP
        df['PV'] = df['Close'] * df['Volume']
        vwap = df['PV'].tail(20).sum() / df['Volume'].tail(20).sum() if df['Volume'].tail(20).sum() > 0 else last_price

        # 9. 精確支撐壓力 (Swing Highs/Lows 近 20 日)
        # 支撐：近 20 日最低點
        support = df['Low'].tail(20).min()
        # 壓力：近 20 日最高點
        resistance = df['High'].tail(20).max()

        # 10. POC (Point of Control) - 近 30 日
        poc = calculate_poc(df)

        # 11. Whale Volume Proxy (主力籌碼)
        whale_status = "中立"
        if vol_ratio > 1.5:
            if last_price > df['Open'].iloc[-1]:
                whale_status = "大買" if vol_ratio > 2.5 else "中買"
            else:
                whale_status = "大賣" if vol_ratio > 2.5 else "中賣"
        elif vol_ratio > 1.2:
            whale_status = "小買" if last_price > df['Open'].iloc[-1] else "小賣"

        # 12. SMC: Fair Value Gap (FVG)
        fvg_list = []
        for i in range(len(df)-1, len(df)-21, -1):
            if i < 2: break
            if df['Low'].iloc[i] > df['High'].iloc[i-2]:
                fvg_list.append({
                    "type": "看漲 FVG",
                    "range": f"${df['High'].iloc[i-2]:.2f} - ${df['Low'].iloc[i]:.2f}",
                    "low_b": float(df['High'].iloc[i-2]),
                    "high_b": float(df['Low'].iloc[i]),
                    "index": i
                })
            elif df['High'].iloc[i] < df['Low'].iloc[i-2]:
                fvg_list.append({
                    "type": "看跌 FVG",
                    "range": f"${df['Low'].iloc[i-2]:.2f} - ${df['High'].iloc[i]:.2f}",
                    "low_b": float(df['High'].iloc[i]),
                    "high_b": float(df['Low'].iloc[i-2]),
                    "index": i
                })
        
        latest_fvg = fvg_list[0] if fvg_list else {"type": "無明顯 FVG", "range": "N/A", "low_b": 0, "high_b": 0}

        # 13. SMC: Liquidity Sweep
        prev_low_20 = df['Low'].iloc[-21:-1].min()
        prev_high_20 = df['High'].iloc[-21:-1].max()
        curr_low = df['Low'].iloc[-1]
        curr_high = df['High'].iloc[-1]
        curr_close = df['Close'].iloc[-1]
        
        sweep_status = "無"
        if curr_low < prev_low_20 and curr_close > prev_low_20:
            sweep_status = "看漲流動性掃蕩 (掃低)"
        elif curr_high > prev_high_20 and curr_close < prev_high_20:
            sweep_status = "看跌流動性掃蕩 (掃高)"

        # 14. 建議停利位置 (Take Profit Targets)
        # 使用 ATR 2 倍與 3 倍，以及 Fib 1.272 作為目標
        tp_target_1 = last_price + (2 * atr) if last_price > ema21 else last_price - (2 * atr)
        tp_target_2 = last_price + (3 * atr) if last_price > ema21 else last_price - (3 * atr)
        # Fib 1.272 擴展位 (基於最近三個月波幅)
        tp_fib = low_3mo + range_3mo * 1.272 if last_price > ema21 else high_3mo - range_3mo * 0.272

        # 15. Attack Gauge
        score = 0
        if last_price > ema21: score += 1
        if last_price < ema21: score -= 1
        if macd_val > signal_val: score += 1
        if macd_val < signal_val: score -= 1
        if rsi > 50: score += 1
        if rsi < 50: score -= 1
        if last_price > vwap: score += 1
        if last_price < vwap: score -= 1
        
        attack_map = {
            4: "大買", 3: "中買", 2: "小買", 1: "小買",
            0: "觀察",
            -1: "小賣", -2: "小賣", -3: "中賣", -4: "大賣"
        }
        attack_status = attack_map.get(score, "觀察")

        return {
            "symbol": symbol,
            "last_price": safe_round(last_price, 2),
            "attack_status": attack_status,
            "whale_status": whale_status,
            "ema_status": ema_status,
            "vwap": safe_round(vwap, 2),
            "atr": safe_round(atr, 2),
            "macd_status": macd_status,
            "rsi": safe_round(rsi, 2),
            "td_status": td_status,
            "support": safe_round(support, 2),
            "resistance": safe_round(resistance, 2),
            "poc": poc,
            "vol_ratio": safe_round(vol_ratio, 2),
            "target_1": safe_round(target_1, 2),
            "target_1618": safe_round(target_1618, 2),
            "tp_targets": {
                "tp1": safe_round(tp_target_1, 2),
                "tp2": safe_round(tp_target_2, 2),
                "tp_fib": safe_round(tp_fib, 2)
            },
            "fvg": latest_fvg,
            "sweep": sweep_status
        }
    except Exception as e:
        logging.error(f"calculate_indicators error for {symbol}: {e}")
        return {"error": str(e)}
