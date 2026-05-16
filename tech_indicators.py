"""tech_indicators.py
量化指標計算核心，提供 EMA, ATR, RSI, MACD, OBV, TD9, Fibonacci, POC 等分析功能。
"""

import logging
import io
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from utils import safe_round, setup_matplotlib_cjk_font


# /tech 文字分析後的原始日K暫存，供同次請求繪圖復用，避免重抓資料
_TECH_DF_CACHE: dict[str, pd.DataFrame] = {}


def clear_tech_df_cache(symbol: str | None = None) -> None:
    """清理 /tech 圖表資料快取，避免長時間記憶體累積。"""
    if symbol:
        _TECH_DF_CACHE.pop(symbol.upper().strip(), None)
        return
    _TECH_DF_CACHE.clear()


def get_volume_price_judgement(df: pd.DataFrame) -> str:
    """量價評斷（9分類）。以明顯漲跌與量能起伏作判斷。"""
    if df is None or len(df) < 3:
        return "價平量平"

    close_now = float(df["Close"].iloc[-1])
    close_prev = float(df["Close"].iloc[-2])
    vol_now = float(df["Volume"].iloc[-1])
    vol_prev = float(df["Volume"].iloc[-2])
    vol_avg20 = float(df["Volume"].tail(20).mean() or 0)

    # 價格：用日變動率判定「漲/跌/平」，避免微幅雜訊
    price_pct = ((close_now - close_prev) / close_prev * 100) if close_prev else 0.0
    if price_pct >= 0.2:
        price_state = "漲"
    elif price_pct <= -0.2:
        price_state = "跌"
    else:
        price_state = "平"

    # 成交量：同時看「相對昨量」+「相對20日均量」
    vol_ratio_prev = (vol_now / vol_prev) if vol_prev > 0 else 1.0
    vol_ratio_avg = (vol_now / vol_avg20) if vol_avg20 > 0 else 1.0
    if vol_ratio_prev >= 1.08 and vol_ratio_avg >= 1.0:
        vol_state = "增"
    elif vol_ratio_prev <= 0.92 and vol_ratio_avg <= 1.0:
        vol_state = "縮"
    else:
        vol_state = "平"

    mapping = {
        ("漲", "增"): "價漲量漲",
        ("漲", "縮"): "價漲量縮",
        ("漲", "平"): "價漲量平",
        ("跌", "增"): "價跌量增",
        ("跌", "縮"): "價跌量縮",
        ("跌", "平"): "價跌量平",
        ("平", "增"): "價平量增",
        ("平", "縮"): "價平量縮",
        ("平", "平"): "價平量平",
    }
    return mapping.get((price_state, vol_state), "價平量平")


def generate_tech_chart_buffer(symbol: str, dpi: int = 130, theme: str = "dark") -> io.BytesIO:
    """生成 /tech 戰術圖表（90天計算，60天顯示），回傳 BytesIO。theme: dark|light"""
    try:
        import mplfinance as mpf
        import matplotlib as mpl
    except Exception as exc:
        raise RuntimeError("缺少 mplfinance 套件，請先安裝 requirements.txt") from exc

    # 統一中文字型策略（跨圖一致）
    setup_matplotlib_cjk_font(mpl)

    symbol = symbol.upper().strip()
    cached_df = _TECH_DF_CACHE.get(symbol)
    if cached_df is not None and not cached_df.empty:
        df = cached_df.copy()
    else:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="90d", interval="1d")

    # 圖表規格固定用最近 90 天資料做計算基底
    if len(df) > 90:
        df = df.tail(90).copy()
    if df.empty or len(df) < 30:
        raise ValueError("數據不足，無法生成技術圖表")

    df = df.copy()
    theme_name = (theme or "dark").strip().lower()
    if theme_name not in {"dark", "light"}:
        theme_name = "dark"
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    # TD9 序列標記（僅在計數 == 9 時打點）
    td_buy_raw = (df["Close"] < df["Close"].shift(4)).astype(int)
    td_sell_raw = (df["Close"] > df["Close"].shift(4)).astype(int)
    buy_markers = pd.Series(np.nan, index=df.index)
    sell_markers = pd.Series(np.nan, index=df.index)
    buy_count = 0
    sell_count = 0
    for i in range(len(df)):
        if int(td_buy_raw.iloc[i]) == 1:
            buy_count += 1
        else:
            buy_count = 0
        if int(td_sell_raw.iloc[i]) == 1:
            sell_count += 1
        else:
            sell_count = 0

        if buy_count == 9:
            buy_markers.iloc[i] = float(df["Low"].iloc[i]) * 0.995
        if sell_count == 9:
            sell_markers.iloc[i] = float(df["High"].iloc[i]) * 1.005

    # 成交量均線（先在原始 df 計算，確保 df_plot 截取後能完整顯示）
    df["VOL_MA20"] = df["Volume"].rolling(window=20).mean()
    # 僅顯示最後 60 根
    df_plot = df.tail(60).copy()

    # 灰色 VWAP 線：從更近期的趨勢底部（最近 20 根的最低 Low）開始累積
    anchor_label = df_plot["Low"].tail(20).idxmin() if len(df_plot) else None
    if anchor_label is None:
        anchor_pos = 0
    else:
        anchor_pos = int(df_plot.index.get_loc(anchor_label))
    vwap_series = pd.Series(np.nan, index=df_plot.index)
    if anchor_pos < len(df_plot):
        seg = df_plot.iloc[anchor_pos:].copy()
        pv = (seg["Close"] * seg["Volume"]).cumsum()
        vv = seg["Volume"].cumsum().replace(0, np.nan)
        vwap_series.iloc[anchor_pos:] = pv / vv

    buy_plot = buy_markers.reindex(df_plot.index)
    sell_plot = sell_markers.reindex(df_plot.index)

    ap = [
        mpf.make_addplot(df_plot["MA20"], color="#FFD166", width=1.35, panel=0),
        mpf.make_addplot(df_plot["EMA50"], color="#FF4D9D", width=1.35, panel=0),
        mpf.make_addplot(vwap_series, color="#AEB6BF", width=1.2, panel=0),
        mpf.make_addplot(df_plot["VOL_MA20"], color="#46C2FF", width=1.1, panel=1),
    ]
    # mplfinance 在全 NaN scatter 會觸發 zero-size array 錯誤，需先判斷再加入
    if not buy_plot.isna().all():
        ap.append(mpf.make_addplot(buy_plot, type="scatter", marker="^", color="#7CFC00", markersize=78))
    if not sell_plot.isna().all():
        ap.append(mpf.make_addplot(sell_plot, type="scatter", marker="v", color="#FF5C5C", markersize=78))

    # 最近一組「尚未完全填補」FVG 區
    fvg_zone = None
    fvg_candidates = detect_recent_fvgs(df, lookback=min(60, len(df) - 2))
    for fvg in fvg_candidates:
        low_b = float(fvg.get("low_b", 0) or 0)
        high_b = float(fvg.get("high_b", 0) or 0)
        idx = int(fvg.get("index", 0) or 0)
        after = df.iloc[idx + 1 :]
        if fvg.get("direction") == "BULLISH":
            filled = bool((after["Low"] <= low_b).any()) if not after.empty else False
        else:
            filled = bool((after["High"] >= high_b).any()) if not after.empty else False
        if not filled:
            fvg_zone = (low_b, high_b)
            break

    fill_between = None
    if fvg_zone:
        zone_low, zone_high = fvg_zone
        y1 = np.full(len(df_plot), zone_high)
        y2 = np.full(len(df_plot), zone_low)
        fill_between = dict(y1=y1, y2=y2, color="#2D6CDF", alpha=0.22)

    if theme_name == "light":
        mc = mpf.make_marketcolors(
            up="#0F9D58",
            down="#DB4437",
            edge={"up": "#0F9D58", "down": "#DB4437"},
            wick={"up": "#34A853", "down": "#EA4335"},
            volume={"up": "#0F9D58", "down": "#DB4437"},
            inherit=False,
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style="yahoo",
            facecolor="#F8FAFC",
            figcolor="#FFFFFF",
            edgecolor="#D1D5DB",
            gridcolor="#E5E7EB",
            gridstyle="--",
            y_on_right=False,
            rc={
                "axes.labelcolor": "#111827",
                "axes.titlecolor": "#0F172A",
                "xtick.color": "#334155",
                "ytick.color": "#334155",
                "font.size": 9,
            },
        )
    else:
        mc = mpf.make_marketcolors(
            up="#7CFC00",
            down="#FF5C5C",
            edge={"up": "#7CFC00", "down": "#FF5C5C"},
            wick={"up": "#B8FF8A", "down": "#FF9A9A"},
            volume={"up": "#7CFC00", "down": "#FF5C5C"},
            inherit=False,
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style="nightclouds",
            facecolor="#0F172A",
            figcolor="#0B1020",
            edgecolor="#334155",
            gridcolor="#2A3248",
            gridstyle="--",
            y_on_right=False,
            rc={
                "axes.labelcolor": "#E5E7EB",
                "axes.titlecolor": "#F8FAFC",
                "xtick.color": "#CBD5E1",
                "ytick.color": "#CBD5E1",
                "font.size": 9,
            },
        )

    buf = io.BytesIO()
    safe_dpi = max(72, min(int(dpi), 180))
    fig, axes = mpf.plot(
        df_plot,
        type="candle",
        volume=True,
        style=style,
        addplot=ap,
        fill_between=fill_between,
        title=f"{symbol}|SMC+TD9 Tactical Chart({theme_name})",
        ylabel="Price",
        ylabel_lower="Volume (K/M/B)",
        returnfig=True,
        closefig=True,
    )

    price_ax = axes[0]
    vol_ax = axes[2] if len(axes) >= 3 else (axes[1] if len(axes) > 1 else axes[0])

    # 左上角：出圖時間 + watermark
    plot_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 集中在左上角顯示
    price_ax.text(
        0.01,
        0.98,
        f"Time: {plot_ts}",
        transform=price_ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="white",
        bbox=dict(facecolor="black", alpha=0.5, edgecolor="none", pad=2),
    )
    # 將 MA/VWAP/量價評斷 標籤移至左上角
    vp_judgement = get_volume_price_judgement(df_plot)
    price_ax.text(0.01, 0.92, "MA20", transform=price_ax.transAxes, ha="left", va="top", fontsize=8, color="#FFD166", weight="bold")
    price_ax.text(0.01, 0.87, "EMA50", transform=price_ax.transAxes, ha="left", va="top", fontsize=8, color="#FF4D9D", weight="bold")
    price_ax.text(0.01, 0.82, "VWAP (anchor)", transform=price_ax.transAxes, ha="left", va="top", fontsize=8, color="#C7CED6", weight="bold")
    price_ax.text(0.01, 0.77, vp_judgement, transform=price_ax.transAxes, ha="left", va="top", fontsize=8, color="#7DD3FC", weight="bold")

    # 在 FVG 藍色區間中間加上 FVG 字樣
    if fvg_zone:
        zl, zh = fvg_zone
        # 移至圖表水平正中央
        price_ax.text(
            len(df_plot) // 2, (zl + zh) / 2, "FVG",
            color="#2D6CDF", fontsize=9, weight="bold",
            ha="center", va="center", alpha=0.7
        )

    # 成交量座標改成 K/M/B 單位
    from matplotlib.ticker import FuncFormatter

    def _fmt_volume(y, _):
        y = float(y)
        ay = abs(y)
        if ay >= 1_000_000_000:
            return f"{y/1_000_000_000:.1f}B"
        if ay >= 1_000_000:
            return f"{y/1_000_000:.1f}M"
        if ay >= 1_000:
            return f"{y/1_000:.1f}K"
        return f"{y:.0f}"

    vol_ax.yaxis.set_major_formatter(FuncFormatter(_fmt_volume))

    # TDST 支撐/壓力虛線
    tdst = calculate_tdst_levels(df)
    support_line = (tdst.get("support") or {}).get("price")
    resistance_line = (tdst.get("resistance") or {}).get("price")
    try:
        if support_line is not None:
            # 使用純綠色
            support_color = "#00FF00" if theme_name == "dark" else "#0F9D58"
            price_ax.axhline(float(support_line), linestyle="--", linewidth=1.15, color=support_color, alpha=0.95)
            # 在中間顯示標籤
            price_ax.text(
                len(df_plot)//2, float(support_line), "---Sup---",
                color=support_color, ha="center", va="center",
                fontsize=7, weight="bold", 
                bbox=dict(facecolor="#0B1020" if theme_name == "dark" else "#FFFFFF", alpha=0.8, edgecolor="none", pad=0)
            )
        if resistance_line is not None:
            # 使用鮮紅色
            resistance_color = "#FF0000" if theme_name == "dark" else "#DB4437"
            price_ax.axhline(float(resistance_line), linestyle="--", linewidth=1.15, color=resistance_color, alpha=0.95)
            # 在中間顯示標籤
            price_ax.text(
                len(df_plot)//2, float(resistance_line), "---Res---",
                color=resistance_color, ha="center", va="center",
                fontsize=7, weight="bold",
                bbox=dict(facecolor="#0B1020" if theme_name == "dark" else "#FFFFFF", alpha=0.8, edgecolor="none", pad=0)
            )
    except Exception:
        pass

    # TD9 反色 K 線效果 + 1~9 數字標記 + 發光
    from matplotlib.patches import Rectangle
    import matplotlib.patheffects as pe

    xvals = np.arange(len(df_plot))
    td_buy_plot = (df_plot["Close"] < df_plot["Close"].shift(4)).astype(int)
    td_sell_plot = (df_plot["Close"] > df_plot["Close"].shift(4)).astype(int)
    bcnt = scnt = 0
    for i in range(len(df_plot)):
        bcnt = bcnt + 1 if int(td_buy_plot.iloc[i]) == 1 else 0
        scnt = scnt + 1 if int(td_sell_plot.iloc[i]) == 1 else 0

        # 僅在計數為 9 時顯示數字
        if bcnt == 9:
            price_ax.text(
                xvals[i],
                float(df_plot["High"].iloc[i]) * 1.01,
                str(bcnt),
                color="#BF00FF",  # 亮紫色
                fontsize=7.5,
                ha="center",
                va="bottom",
                weight="bold",
                bbox=dict(facecolor="#0B1020", edgecolor="none", alpha=0.75, pad=0.3),
            ).set_path_effects([pe.withStroke(linewidth=2.6, foreground="#E0B0FF", alpha=0.8)])
        if scnt == 9:
            price_ax.text(
                xvals[i],
                float(df_plot["High"].iloc[i]) * 1.02,
                str(scnt),
                color="#BF00FF",  # 亮紫色
                fontsize=7.5,
                ha="center",
                va="bottom",
                weight="bold",
                bbox=dict(facecolor="#0B1020", edgecolor="none", alpha=0.75, pad=0.3),
            ).set_path_effects([pe.withStroke(linewidth=2.6, foreground="#E0B0FF", alpha=0.8)])

        if bcnt == 9 or scnt == 9:
            o = float(df_plot["Open"].iloc[i])
            c = float(df_plot["Close"].iloc[i])
            low = min(o, c)
            h = abs(c - o)
            if h == 0:
                h = max(float(df_plot["High"].iloc[i] - df_plot["Low"].iloc[i]) * 0.1, 0.01)
            # 上漲TD9（scnt==9）：綠框紅心；下跌TD9（bcnt==9）：紅框綠心
            edge = "lime" if scnt == 9 else "red"
            face = "red" if scnt == 9 else "lime"
            rect = Rectangle((xvals[i] - 0.35, low), 0.7, h, linewidth=1.6, edgecolor=edge, facecolor=face, alpha=0.25)
            rect.set_path_effects([pe.withStroke(linewidth=4.0, foreground=edge, alpha=0.32)])
            price_ax.add_patch(rect)

    fig.savefig(buf, format="png", dpi=safe_dpi, bbox_inches="tight")
    try:
        import matplotlib.pyplot as plt

        plt.close(fig)
    except Exception:
        pass
    buf.seek(0)
    return buf


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

        # 給圖表模組重用（同一個 /tech 請求就不必再抓一次）
        _TECH_DF_CACHE[symbol] = df.copy()

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
        volume_price_judgement = get_volume_price_judgement(df)

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
        # 趨勢分 (加入 21/60 雙均線判斷)
        if last_price > ema21: score += 1
        if last_price > ema60: score += 1
        if ema21 > ema60: score += 1
        
        # 動能分
        if macd_val > signal_val: score += 1
        if rsi > 50: score += 1
        if last_price > vwap: score += 1
        
        # 負向扣分
        if last_price < ema21: score -= 1
        if last_price < ema60: score -= 1
        if ema21 < ema60: score -= 1
        if macd_val < signal_val: score -= 1
        if rsi < 50: score -= 1
        if last_price < vwap: score -= 1

        attack_map = {
            6: "強力攻擊", 5: "大買", 4: "大買", 3: "中買", 2: "小買", 1: "小買",
            0: "觀察", -1: "小賣", -2: "小賣", -3: "中賣", -4: "大賣", -5: "大賣", -6: "強力拋售"
        }
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
            "volume_price_judgement": volume_price_judgement,
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
