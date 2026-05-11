"""tech_indicators.py
量化指標計算核心，提供 EMA, ATR, RSI, MACD, OBV, TD9, Fibonacci, POC 等分析功能。
"""

import logging
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from utils import safe_round


def _format_price_zone(low: float, high: float) -> str:
    return f"${safe_round(low, 2):.2f} - ${safe_round(high, 2):.2f}"


def calculate_ma_trend_filter(df: pd.DataFrame) -> dict[str, Any]:
    """計算 MA20/MA50/MA200 趨勢濾網。"""
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA50"] = df["Close"].rolling(window=50).mean()
    df["MA200"] = df["Close"].rolling(window=200).mean()

    last_price = float(df["Close"].iloc[-1])
    ma20 = df["MA20"].iloc[-1]
    ma50 = df["MA50"].iloc[-1]
    ma200 = df["MA200"].iloc[-1]

    if pd.isna(ma20) or pd.isna(ma50) or pd.isna(ma200):
        return {
            "status": "資料不足，無法完成 MA20/50/200 趨勢濾網",
            "price": safe_round(last_price, 2),
            "ma20": "N/A",
            "ma50": "N/A",
            "ma200": "N/A",
            "bullish": False,
            "bearish": False,
        }

    ma20_f = float(ma20)
    ma50_f = float(ma50)
    ma200_f = float(ma200)
    bullish = last_price > ma20_f > ma50_f > ma200_f
    bearish = last_price < ma20_f < ma50_f < ma200_f
    if bullish:
        status = "🟢 多頭排列 (Price > MA20 > MA50 > MA200)"
    elif bearish:
        status = "🔴 空頭排列 (Price < MA20 < MA50 < MA200)"
    else:
        status = "⚪ 趨勢未共振 / MA 結構糾結"

    return {
        "status": status,
        "price": safe_round(last_price, 2),
        "ma20": safe_round(ma20_f, 2),
        "ma50": safe_round(ma50_f, 2),
        "ma200": safe_round(ma200_f, 2),
        "bullish": bullish,
        "bearish": bearish,
    }


def calculate_tdst_levels(df: pd.DataFrame) -> dict[str, Any]:
    """計算 TD Setup 9 與最新有效 TDST 支撐/壓力線。"""
    bullish_count = 0  # 連續收盤高於前第 4 根，用於 TDST Resistance
    bearish_count = 0  # 連續收盤低於前第 4 根，用於 TDST Support
    support_lines: list[dict[str, Any]] = []
    resistance_lines: list[dict[str, Any]] = []

    for i in range(4, len(df)):
        close = float(df["Close"].iloc[i])
        ref_close = float(df["Close"].iloc[i - 4])

        bullish_count = bullish_count + 1 if close > ref_close else 0
        bearish_count = bearish_count + 1 if close < ref_close else 0

        if bullish_count == 9:
            start = i - 8
            high = float(df["High"].iloc[start : i + 1].max())
            resistance_lines.append(
                {
                    "type": "TDST_RESISTANCE",
                    "price": safe_round(high, 2),
                    "source_index": int(i),
                    "age_bars": int(len(df) - 1 - i),
                }
            )

        if bearish_count == 9:
            start = i - 8
            low = float(df["Low"].iloc[start : i + 1].min())
            support_lines.append(
                {
                    "type": "TDST_SUPPORT",
                    "price": safe_round(low, 2),
                    "source_index": int(i),
                    "age_bars": int(len(df) - 1 - i),
                }
            )

    def _mark_valid(line: dict[str, Any] | None, side: str) -> dict[str, Any] | None:
        if not line:
            return None
        price = float(line["price"])
        start = int(line["source_index"]) + 1
        closes_after = df["Close"].iloc[start:] if start < len(df) else pd.Series(dtype=float)
        if side == "support":
            broken = bool((closes_after < price).any()) if not closes_after.empty else False
        else:
            broken = bool((closes_after > price).any()) if not closes_after.empty else False
        line = dict(line)
        line["valid"] = not broken
        line["status"] = "有效" if not broken else "已失效"
        return line

    latest_support = _mark_valid(support_lines[-1] if support_lines else None, "support")
    latest_resistance = _mark_valid(resistance_lines[-1] if resistance_lines else None, "resistance")

    return {
        "support": latest_support,
        "resistance": latest_resistance,
        "support_count": len(support_lines),
        "resistance_count": len(resistance_lines),
    }


def detect_fvg_at_index(df: pd.DataFrame, i: int) -> dict[str, Any] | None:
    """依照 Low[0] > High[2] / High[0] < Low[2] 偵測單根 FVG。"""
    if i < 2 or i >= len(df):
        return None

    curr_low = float(df["Low"].iloc[i])
    curr_high = float(df["High"].iloc[i])
    prev2_high = float(df["High"].iloc[i - 2])
    prev2_low = float(df["Low"].iloc[i - 2])

    if curr_low > prev2_high:
        low_b = prev2_high
        high_b = curr_low
        return {
            "type": "看漲 FVG",
            "direction": "BULLISH",
            "range": _format_price_zone(low_b, high_b),
            "low_b": low_b,
            "high_b": high_b,
            "index": int(i),
        }

    if curr_high < prev2_low:
        low_b = curr_high
        high_b = prev2_low
        return {
            "type": "看跌 FVG",
            "direction": "BEARISH",
            "range": _format_price_zone(low_b, high_b),
            "low_b": low_b,
            "high_b": high_b,
            "index": int(i),
        }

    return None


def detect_recent_fvgs(df: pd.DataFrame, lookback: int = 20) -> list[dict[str, Any]]:
    """偵測最近 lookback 根 K 棒內的 FVG，最新在前。"""
    fvg_list: list[dict[str, Any]] = []
    start = max(2, len(df) - lookback)
    for i in range(len(df) - 1, start - 1, -1):
        fvg = detect_fvg_at_index(df, i)
        if fvg:
            fvg_list.append(fvg)
    return fvg_list


def _level_near_zone(level: float, zone_low: float, zone_high: float, tolerance: float) -> tuple[bool, float]:
    if zone_low <= level <= zone_high:
        return True, 0.0
    distance = min(abs(level - zone_low), abs(level - zone_high))
    return distance <= tolerance, distance


def build_confluence_signal(
    ma_filter: dict[str, Any],
    current_fvg: dict[str, Any] | None,
    tdst: dict[str, Any],
    atr: float,
    last_price: float,
) -> dict[str, Any]:
    """建立 TDST × FVG × MA 趨勢濾網的共振交易訊號。"""
    tolerance = max(float(atr or 0) * 0.15, float(last_price or 0) * 0.002)

    def _empty_payload(reason: str) -> dict[str, Any]:
        return {
            "signal_type": "NONE",
            "direction": "NONE",
            "entry_zone": None,
            "entry_zone_text": "N/A",
            "stop_loss": None,
            "tdst_level": None,
            "tolerance": safe_round(tolerance, 2),
            "confluence_ok": False,
            "reasons": [reason],
        }

    empty_signal = {
        "signal_type": "NONE",
        "direction": "NONE",
        "entry_zone": None,
        "entry_zone_text": "N/A",
        "stop_loss": None,
        "tdst_level": None,
        "tolerance": safe_round(tolerance, 2),
        "confluence_ok": False,
        "reasons": ["尚未同時滿足 MA 趨勢、當前 FVG 與有效 TDST 共振。"],
    }

    if not current_fvg:
        return _empty_payload("當前 K 棒未形成新的 FVG，暫不觸發共振訊號。")

    zone_low = float(current_fvg["low_b"])
    zone_high = float(current_fvg["high_b"])

    if ma_filter.get("bullish") and current_fvg.get("direction") == "BULLISH":
        support = tdst.get("support")
        if support and support.get("valid"):
            support_price = float(support["price"])
            near, distance = _level_near_zone(support_price, zone_low, zone_high, tolerance)
            if near:
                return {
                    "signal_type": "STRONG_LONG",
                    "direction": "LONG",
                    "entry_zone": {
                        "low": safe_round(zone_low, 2),
                        "high": safe_round(zone_high, 2),
                        "text": _format_price_zone(zone_low, zone_high),
                    },
                    "entry_zone_text": _format_price_zone(zone_low, zone_high),
                    "stop_loss": safe_round(support_price - tolerance, 2),
                    "tdst_level": safe_round(support_price, 2),
                    "tolerance": safe_round(tolerance, 2),
                    "confluence_ok": True,
                    "reasons": [
                        "MA20/50/200 多頭排列，僅尋找做多訊號。",
                        f"當前 K 棒形成看漲 FVG：{current_fvg.get('range')}",
                        f"有效 TDST 支撐 {safe_round(support_price, 2)} 落在或貼近 FVG（距離 {safe_round(distance, 2)}）。",
                        "進場規劃：可於 FVG 區間內分批掛單做多。",
                    ],
                }

    if ma_filter.get("bearish") and current_fvg.get("direction") == "BEARISH":
        resistance = tdst.get("resistance")
        if resistance and resistance.get("valid"):
            resistance_price = float(resistance["price"])
            near, distance = _level_near_zone(resistance_price, zone_low, zone_high, tolerance)
            if near:
                return {
                    "signal_type": "STRONG_SHORT",
                    "direction": "SHORT",
                    "entry_zone": {
                        "low": safe_round(zone_low, 2),
                        "high": safe_round(zone_high, 2),
                        "text": _format_price_zone(zone_low, zone_high),
                    },
                    "entry_zone_text": _format_price_zone(zone_low, zone_high),
                    "stop_loss": safe_round(resistance_price + tolerance, 2),
                    "tdst_level": safe_round(resistance_price, 2),
                    "tolerance": safe_round(tolerance, 2),
                    "confluence_ok": True,
                    "reasons": [
                        "MA20/50/200 空頭排列，僅尋找做空訊號。",
                        f"當前 K 棒形成看跌 FVG：{current_fvg.get('range')}",
                        f"有效 TDST 壓力 {safe_round(resistance_price, 2)} 落在或貼近 FVG（距離 {safe_round(distance, 2)}）。",
                        "進場規劃：可於 FVG 區間內分批掛單做空。",
                    ],
                }

    return empty_signal


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

    price_min = recent_df["Low"].min()
    price_max = recent_df["High"].max()

    if price_max == price_min:
        return price_min

    # 建立價格區間 (Bins)
    bin_size = (price_max - price_min) / bins
    if bin_size <= 0:
        return price_min

    # 依照成交量分佈到價格區間
    recent_df["bin"] = ((recent_df["Close"] - price_min) / bin_size).astype(int).clip(0, bins - 1)

    # 依照 bin 累計成交量
    volume_profile = recent_df.groupby("bin")["Volume"].sum()

    if volume_profile.empty:
        return recent_df["Close"].iloc[-1]

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
        df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
        df["EMA60"] = df["Close"].ewm(span=60, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

        last_price = df["Close"].iloc[-1]
        ema21 = df["EMA21"].iloc[-1]
        ema60 = df["EMA60"].iloc[-1]
        ema200 = df["EMA200"].iloc[-1]

        if last_price > ema21 > ema60 > ema200:
            ema_status = "多頭排列 (價>21>60>200)"
        elif last_price < ema21 < ema60 < ema200:
            ema_status = "空頭排列 (價<21<60<200)"
        else:
            ema_status = "均線糾結 / 趨勢不明"

        # 2. ATR (14)
        high_low = df["High"] - df["Low"]
        high_close = np.abs(df["High"] - df["Close"].shift())
        low_close = np.abs(df["Low"] - df["Close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR14"] = tr.rolling(window=14).mean()
        atr = df["ATR14"].iloc[-1]

        # 3. RSI (14)
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["RSI14"] = 100 - (100 / (1 + rs))
        rsi = df["RSI14"].iloc[-1]

        # 4. MACD (12, 26, 9)
        exp1 = df["Close"].ewm(span=12, adjust=False).mean()
        exp2 = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = exp1 - exp2
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["Hist"] = df["MACD"] - df["Signal"]

        macd_val = df["MACD"].iloc[-1]
        signal_val = df["Signal"].iloc[-1]
        hist_val = df["Hist"].iloc[-1]
        prev_hist = df["Hist"].iloc[-2]

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
        df["OBV"] = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
        vol_last = df["Volume"].iloc[-1]
        vol_avg20 = df["Volume"].tail(20).mean()
        vol_ratio = vol_last / vol_avg20 if vol_avg20 > 0 else 0

        # 6. TD9 (Tom DeMark Sequential)
        df["TD_Buy"] = (df["Close"] < df["Close"].shift(4)).astype(int)
        df["TD_Sell"] = (df["Close"] > df["Close"].shift(4)).astype(int)

        buy_count = 0
        sell_count = 0
        for i in range(len(df) - 1, -1, -1):
            if df["TD_Buy"].iloc[i] == 1:
                buy_count += 1
            else:
                break
        for i in range(len(df) - 1, -1, -1):
            if df["TD_Sell"].iloc[i] == 1:
                sell_count += 1
            else:
                break

        td_status = "序列進行中"
        if buy_count > 0:
            if buy_count == 9:
                td_status = "🔥 下跌TD9 (強反轉預期)"
            elif buy_count > 9:
                td_status = f"下跌TD9+ ({buy_count})"
            else:
                td_status = f"下跌TD{buy_count}"
        elif sell_count > 0:
            if sell_count == 9:
                td_status = "💀 上漲TD9 (強反轉預期)"
            elif sell_count > 9:
                td_status = f"上漲TD9+ ({sell_count})"
            else:
                td_status = f"上漲TD{sell_count}"
        else:
            td_status = "TD 序列中立"

        # 7. Fibonacci (這裡簡化為最近一季的高低點)
        high_3mo = df["High"].tail(60).max()
        low_3mo = df["Low"].tail(60).min()
        range_3mo = high_3mo - low_3mo
        target_1 = high_3mo + range_3mo * 1.0
        target_1618 = high_3mo + range_3mo * 1.618

        # 8. VWAP
        df["PV"] = df["Close"] * df["Volume"]
        vwap = df["PV"].tail(20).sum() / df["Volume"].tail(20).sum() if df["Volume"].tail(20).sum() > 0 else last_price

        # 9. 精確支撐壓力 (Swing Highs/Lows 近 20 日)
        # 支撐：近 20 日最低點
        support = df["Low"].tail(20).min()
        # 壓力：近 20 日最高點
        resistance = df["High"].tail(20).max()

        # 10. POC (Point of Control) - 近 30 日
        poc = calculate_poc(df)

        # 11. Whale Volume Proxy (主力籌碼)
        whale_status = "中立"
        if vol_ratio > 1.5:
            if last_price > df["Open"].iloc[-1]:
                whale_status = "大買" if vol_ratio > 2.5 else "中買"
            else:
                whale_status = "大賣" if vol_ratio > 2.5 else "中賣"
        elif vol_ratio > 1.2:
            whale_status = "小買" if last_price > df["Open"].iloc[-1] else "小賣"

        # 12. SMC: Fair Value Gap (FVG)
        fvg_list = detect_recent_fvgs(df, lookback=20)

        latest_fvg = fvg_list[0] if fvg_list else {"type": "無明顯 FVG", "range": "N/A", "low_b": 0, "high_b": 0}

        # 13. SMC: Liquidity Sweep
        prev_low_20 = df["Low"].iloc[-21:-1].min()
        prev_high_20 = df["High"].iloc[-21:-1].max()
        curr_low = df["Low"].iloc[-1]
        curr_high = df["High"].iloc[-1]
        curr_close = df["Close"].iloc[-1]

        sweep_status = "無"
        if curr_low < prev_low_20 and curr_close > prev_low_20:
            sweep_status = "看漲流動性掃蕩 (掃低)"
        elif curr_high > prev_high_20 and curr_close < prev_high_20:
            sweep_status = "看跌流動性掃蕩 (掃高)"

        # 14. 建議停利位置 (Take Profit Targets)
        # 短線採 2x ATR；波段採 3x ATR 與 Fib Ext 中「距離更遠」的一個，避免波段目標短於短線目標。
        is_bullish_context = last_price > ema21
        tp_target_1 = last_price + (2 * atr) if is_bullish_context else last_price - (2 * atr)
        tp_target_2 = last_price + (3 * atr) if is_bullish_context else last_price - (3 * atr)
        fib_ext = low_3mo + range_3mo * 1.272 if is_bullish_context else high_3mo - range_3mo * 0.272
        tp_fib = max(tp_target_2, fib_ext) if is_bullish_context else min(tp_target_2, fib_ext)

        # 15. Attack Gauge
        score = 0
        if last_price > ema21:
            score += 1
        if last_price < ema21:
            score -= 1
        if macd_val > signal_val:
            score += 1
        if macd_val < signal_val:
            score -= 1
        if rsi > 50:
            score += 1
        if rsi < 50:
            score -= 1
        if last_price > vwap:
            score += 1
        if last_price < vwap:
            score -= 1

        attack_map = {4: "大買", 3: "中買", 2: "小買", 1: "小買", 0: "觀察", -1: "小賣", -2: "小賣", -3: "中賣", -4: "大賣"}
        attack_status = attack_map.get(score, "觀察")

        # 16. 文件需求：MA20/50/200 + TDST + 當前 FVG 共振狙擊訊號
        ma_filter = calculate_ma_trend_filter(df)
        tdst_levels = calculate_tdst_levels(df)
        current_fvg = detect_fvg_at_index(df, len(df) - 1)
        confluence_signal = build_confluence_signal(
            ma_filter=ma_filter,
            current_fvg=current_fvg,
            tdst=tdst_levels,
            atr=float(atr) if not pd.isna(atr) else 0.0,
            last_price=float(last_price),
        )

        # 供 bot / API 直接使用的標準化輸出格式
        confluence_payload = {
            "signal_type": confluence_signal.get("signal_type", "NONE"),
            "direction": confluence_signal.get("direction", "NONE"),
            "entry_zone": confluence_signal.get("entry_zone"),
            "entry_zone_text": confluence_signal.get("entry_zone_text", "N/A"),
            "stop_loss": confluence_signal.get("stop_loss"),
            "tdst_level": confluence_signal.get("tdst_level"),
            "tolerance": confluence_signal.get("tolerance"),
            "confluence_ok": bool(confluence_signal.get("confluence_ok", False)),
            "reasons": confluence_signal.get("reasons", []),
        }

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
            "tp_targets": {"tp1": safe_round(tp_target_1, 2), "tp2": safe_round(tp_target_2, 2), "tp_fib": safe_round(tp_fib, 2)},
            "fvg": latest_fvg,
            "fvg_list": fvg_list[:5],
            "current_fvg": current_fvg,
            "sweep": sweep_status,
            "ma_filter": ma_filter,
            "tdst": tdst_levels,
            "confluence_signal": confluence_signal,
            "confluence_payload": confluence_payload,
        }
    except Exception as e:
        logging.error(f"calculate_indicators error for {symbol}: {e}")
        return {"error": str(e)}
