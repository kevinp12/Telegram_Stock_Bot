import matplotlib
matplotlib.use('Agg')

import pandas as pd
import numpy as np
import io
import logging


TRADING_DAYS = 252


def _max_drawdown_duration(drawdown: pd.Series) -> int:
    """計算最長回撤修復時間：從跌破新高到再次創高的最長交易日數。"""
    max_duration = 0
    current_duration = 0
    for value in drawdown.fillna(0):
        if value < 0:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0
    return int(max_duration)


def _ulcer_index(drawdown: pd.Series) -> float:
    """Ulcer Index：回撤深度與持續時間的綜合壓力指標，單位為百分比。"""
    dd_pct = drawdown.fillna(0).clip(upper=0) * 100
    return float(np.sqrt(np.mean(np.square(dd_pct)))) if len(dd_pct) else 0.0


def calculate_metrics(df: pd.DataFrame):
    """計算詳細交易與風險指標：MDD、Duration、UI、Sharpe、Sortino、Calmar。"""
    if df.empty:
        return {"error": "資料為空"}, None

    trades = []
    current_trade = {}

    # 相容舊/新策略欄位，避免 KeyError: 'Position'
    if 'Position' not in df.columns:
        if 'Position_Size' in df.columns:
            df['Position'] = (pd.to_numeric(df['Position_Size'], errors='coerce').fillna(0) > 0).astype(int)
        else:
            df['Position'] = 0
    if 'Strategy_Return' not in df.columns:
        if 'Position_Size' in df.columns:
            df['Strategy_Return'] = pd.to_numeric(df['Position_Size'], errors='coerce').fillna(0).shift(1).fillna(0) * df['Close'].pct_change().fillna(0)
        else:
            df['Strategy_Return'] = 0.0

    pos_series = df['Position']
    prev_pos_series = pos_series.shift(1).fillna(0)
    
    for i in range(len(df)):
        date = df.index[i]
        curr_pos = pos_series.iloc[i]
        prev_pos = prev_pos_series.iloc[i]
        close_price = df['Close'].iloc[i]
        
        if curr_pos == 1 and prev_pos == 0:  # 買進
            current_trade = {'entry_date': date, 'entry_price': close_price}
        elif curr_pos == 0 and prev_pos == 1 and current_trade:  # 賣出
            current_trade['exit_date'] = date
            current_trade['exit_price'] = close_price
            current_trade['pnl_pct'] = (current_trade['exit_price'] / current_trade['entry_price']) - 1
            current_trade['hold_days'] = (current_trade['exit_date'] - current_trade['entry_date']).days
            trades.append(current_trade)
            current_trade = {}
            
    if not trades:
        return {"error": "回測期間無觸發任何交易"}, None
        
    df_trades = pd.DataFrame(trades)
    winning_trades = df_trades[df_trades['pnl_pct'] > 0]
    losing_trades = df_trades[df_trades['pnl_pct'] <= 0]
    
    # 計算權益曲線與 MDD
    # 機構級修正：手續費已在 strategy_long_term.py 中按單次成交精確扣除
    df['Strategy_CumReturn'] = (1 + df['Strategy_Return']).cumprod()
    df['Benchmark_CumReturn'] = (1 + df['Close'].pct_change().fillna(0)).cumprod()
    
    # Max Drawdown / Duration / Ulcer Index
    cum_max = df['Strategy_CumReturn'].cummax()
    df['Drawdown'] = (df['Strategy_CumReturn'] - cum_max) / cum_max
    max_drawdown = df['Drawdown'].min()
    drawdown_duration = _max_drawdown_duration(df['Drawdown'])
    ulcer_index = _ulcer_index(df['Drawdown'])
    
    # 風險調整後報酬：使用完整策略日報酬，空手日為 0，避免只看持倉日高估風險效率。
    daily_returns = df['Strategy_Return'].fillna(0)
    risk_free_daily = 0.02 / TRADING_DAYS
    if not daily_returns.empty:
        excess_returns = daily_returns - risk_free_daily
        ret_std = excess_returns.std()
        sharpe_ratio = np.sqrt(TRADING_DAYS) * excess_returns.mean() / ret_std if ret_std and ret_std != 0 else 0

        downside_returns = np.minimum(excess_returns, 0)
        downside_dev = np.sqrt(np.mean(np.square(downside_returns)))
        sortino_ratio = np.sqrt(TRADING_DAYS) * excess_returns.mean() / downside_dev if downside_dev and downside_dev != 0 else 0
    else:
        sharpe_ratio = 0
        sortino_ratio = 0

    years = max(len(df) / TRADING_DAYS, 1 / TRADING_DAYS)
    final_equity = float(df['Strategy_CumReturn'].iloc[-1])
    annual_return = (final_equity ** (1 / years) - 1) if final_equity > 0 else -1
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown < 0 else float('inf')

    metrics = {
        "total_trades": len(trades),
        "win_rate": len(winning_trades) / len(trades),
        "avg_win": winning_trades['pnl_pct'].mean() if not winning_trades.empty else 0,
        "avg_loss": losing_trades['pnl_pct'].mean() if not losing_trades.empty else 0,
        "avg_hold_days": df_trades['hold_days'].mean(),
        "total_return_pct": (df['Strategy_CumReturn'].iloc[-1] - 1) * 100,
        "benchmark_return_pct": (df['Benchmark_CumReturn'].iloc[-1] - 1) * 100,
        "annual_return_pct": annual_return * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "drawdown_duration_days": drawdown_duration,
        "ulcer_index": ulcer_index,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
    }
    
    avg_win = metrics['avg_win']
    avg_loss = abs(metrics['avg_loss'])
    metrics['payoff_ratio'] = avg_win / avg_loss if avg_loss != 0 else float('inf')
    
    return metrics, df_trades

def generate_backtest_chart(df: pd.DataFrame, ticker: str, theme: str = "dark") -> io.BytesIO | None:
    """生成美觀的回測圖表 (淨值曲線 + 回向回撤)。"""
    try:
        import matplotlib as mpl
        from matplotlib.gridspec import GridSpec
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from utils import setup_matplotlib_cjk_font
    except ImportError:
        return None

    setup_matplotlib_cjk_font(mpl)
    
    is_dark = theme == "dark"
    bg_color = "#0F172A" if is_dark else "#FFFFFF"
    fg_color = "#F8FAFC" if is_dark else "#1E293B"
    grid_color = "#334155" if is_dark else "#E2E8F0"
    accent_color = "#38BDF8"  # 亮藍
    bench_color = "#94A3B8"   # 灰藍
    dd_color = "#EF4444"      # 紅色
    
    fig = None
    try:
        fig = Figure(figsize=(14, 9), facecolor=bg_color)
        FigureCanvasAgg(fig)
        gs = GridSpec(2, 1, height_ratios=[3, 1], hspace=0.15)

        # 1. 權益曲線
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor(bg_color)

        strategy_cum = df['Strategy_CumReturn'] * 100
        benchmark_cum = df['Benchmark_CumReturn'] * 100

        ax1.plot(strategy_cum.index, strategy_cum, color=accent_color, linewidth=2.5, label="策略績效 (Strategy)")
        ax1.plot(benchmark_cum.index, benchmark_cum, color=bench_color, linewidth=1.5, linestyle="--", alpha=0.6, label="基準績效 (Buy & Hold)")

        # 填滿區域
        ax1.fill_between(strategy_cum.index, strategy_cum, 100, where=(strategy_cum >= 100), color=accent_color, alpha=0.1)

        # 標註買點
        buy_dates = df[(df['Position'] == 1) & (df['Position'].shift(1) == 0)].index
        if not buy_dates.empty:
            ax1.scatter(buy_dates, strategy_cum.loc[buy_dates], color="#4ADE80", marker="^", s=50, label="進場點", zorder=5)

        ax1.set_title(f"{ticker} 長線量化策略回測結果", fontsize=20, fontweight='bold', color=fg_color, pad=25)
        ax1.set_ylabel("資產價值 (起始=100)", fontsize=14, color=fg_color)
        ax1.legend(loc="upper left", fontsize=12, facecolor=bg_color, edgecolor=grid_color, labelcolor=fg_color)
        ax1.grid(True, linestyle=":", alpha=0.3, color=grid_color)
        ax1.tick_params(colors=fg_color, labelsize=11)

        # 2. Drawdown
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.set_facecolor(bg_color)

        dd_series = df['Drawdown'] * 100
        ax2.fill_between(dd_series.index, dd_series, 0, color=dd_color, alpha=0.3, label="最大回撤 (Drawdown)")
        ax2.plot(dd_series.index, dd_series, color=dd_color, linewidth=1, alpha=0.7)

        ax2.set_ylabel("回撤 (%)", fontsize=14, color=fg_color)
        ax2.set_ylim(dd_series.min() * 1.2, 5)
        ax2.grid(True, linestyle=":", alpha=0.3, color=grid_color)
        ax2.tick_params(colors=fg_color, labelsize=11)

        for ax in [ax1, ax2]:
            for spine in ax.spines.values():
                spine.set_color(grid_color)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=130, facecolor=bg_color)
        buf.seek(0)
        return buf
    finally:
        if fig is not None:
            try:
                fig.clf()
            except Exception:
                pass
