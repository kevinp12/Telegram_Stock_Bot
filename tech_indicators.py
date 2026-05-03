"""tech_indicators.py
量化指標計算核心，提供 EMA, ATR, RSI, MACD, OBV, TD9, Fibonacci 等分析功能。
"""
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Any
from utils import safe_round

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
        # 簡單實現：連續 9 根收盤價高於/低於 4 天前
        df['TD_Buy'] = (df['Close'] < df['Close'].shift(4)).astype(int)
        df['TD_Sell'] = (df['Close'] > df['Close'].shift(4)).astype(int)
        
        buy_count = 0
        sell_count = 0
        # 從最後一根往前回溯計算連續天數
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
        # 預估目標價：使用斐波那契擴展 1.0 與 1.618
        target_1 = high_3mo + range_3mo * 1.0
        target_1618 = high_3mo + range_3mo * 1.618

        # 8. VWAP (成交量加權平均價) - 這裡取近 20 日的簡化計算
        df['PV'] = df['Close'] * df['Volume']
        vwap = df['PV'].tail(20).sum() / df['Volume'].tail(20).sum() if df['Volume'].tail(20).sum() > 0 else last_price

        # 9. Support & Resistance (近 60 日)
        support = df['Low'].tail(60).min()
        resistance = df['High'].tail(60).max()

        # 10. Whale Volume Proxy (主力籌碼)
        whale_status = "中立"
        if vol_ratio > 1.5:
            if last_price > df['Open'].iloc[-1]:
                whale_status = "大買" if vol_ratio > 2.5 else "中買"
            else:
                whale_status = "大賣" if vol_ratio > 2.5 else "中賣"
        elif vol_ratio > 1.2:
            whale_status = "小買" if last_price > df['Open'].iloc[-1] else "小賣"

        # 11. Attack Gauge (綜合多空打分 -4 到 +4)
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
            "vol_ratio": safe_round(vol_ratio, 2),
            "target_1": safe_round(target_1, 2),
            "target_1618": safe_round(target_1618, 2)
        }
    except Exception as e:
        logging.error(f"calculate_indicators error for {symbol}: {e}")
        return {"error": str(e)}
