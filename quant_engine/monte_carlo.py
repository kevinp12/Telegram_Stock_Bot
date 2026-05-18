import numpy as np
import pandas as pd
import io
import logging

def run_monte_carlo(df: pd.DataFrame, days: int = 252, simulations: int = 2000):
    """
    執行幾何布朗運動 (GBM) 蒙地卡羅模擬，包含漂移率限制與 VaR 修正。
    """
    if df.empty or len(df) < 20:
        return None
        
    # 1. 計算對數報酬率 (Log Returns)
    log_returns = np.log(df['Close'] / df['Close'].shift(1)).dropna()
    
    current_price = float(df['Close'].iloc[-1])
    daily_mu = log_returns.mean()
    daily_vol = log_returns.std()
    
    # 2. 年化並限制漂移率 (Drift Cap)
    # 將最大年化預期報酬限制在 15%，避免歷史強勢股在模擬中無限噴發
    annual_mu = min(daily_mu * 252, 0.15) 
    # 重新換算回每日模擬用的受限 mu
    restricted_daily_mu = annual_mu / 252
    
    # 3. 執行 GBM 模擬 (向量化加速)
    # 產生標準常態分佈隨機數 (days x simulations)
    Z = np.random.normal(0, 1, (days, simulations))
    
    # GBM 公式: P_t = P_0 * exp(cumsum((mu - 0.5*sigma^2) * dt + sigma * sqrt(dt) * Z))
    # 這裡 dt = 1 (1天)
    drift = (restricted_daily_mu - 0.5 * daily_vol**2)
    diffusion = daily_vol * Z
    price_paths = current_price * np.exp(np.cumsum(drift + diffusion, axis=0))
    
    # 4. 取得最終價格分佈
    final_prices = price_paths[-1, :]
    
    p50 = np.percentile(final_prices, 50)
    p95 = np.percentile(final_prices, 95)
    p5 = np.percentile(final_prices, 5)
    up_prob = (final_prices > current_price).sum() / simulations
    
    # 5. 修正 VaR 計算 (確保為衡量下行風險百分比)
    # VaR 95% = 價格中 5% 分位數相對於現價的跌幅
    var_95_pct = ((p5 - current_price) / current_price) * 100
    
    # 計算 CVaR (Expected Shortfall)
    cvar_prices = final_prices[final_prices <= p5]
    cvar_pct = ((cvar_prices.mean() - current_price) / current_price) * 100 if len(cvar_prices) > 0 else var_95_pct
    
    results = {
        "current_price": current_price,
        "mean_final_price": np.mean(final_prices),
        "median_final_price": p50,
        "pct_5": p5,
        "pct_25": np.percentile(final_prices, 25),
        "pct_75": np.percentile(final_prices, 75),
        "pct_95": p95,
        "prob_positive": up_prob,
        "var_95_pct": var_95_pct,
        "cvar_95_pct": cvar_pct
    }
    
    return results, price_paths

def generate_simulation_chart(price_paths: np.ndarray, current_price: float, ticker: str, theme: str = "dark") -> io.BytesIO | None:
    """生成具有漸變置信區間的蒙地卡羅模擬路徑圖。"""
    try:
        import matplotlib as mpl
        mpl.use('Agg')
        import matplotlib.pyplot as plt
        from utils import setup_matplotlib_cjk_font
    except ImportError:
        return None

    setup_matplotlib_cjk_font(mpl)
    
    is_dark = theme == "dark"
    bg_color = "#0F172A"
    fg_color = "#F8FAFC"
    grid_color = "#334155"
    accent_color = "#38BDF8"
    
    fig, ax = plt.subplots(figsize=(12, 8), facecolor=bg_color)
    ax.set_facecolor(bg_color)
    
    days = price_paths.shape[0]
    x = np.arange(1, days + 1)
    
    # 計算百分位數路徑
    p5 = np.percentile(price_paths, 5, axis=1)
    p25 = np.percentile(price_paths, 25, axis=1)
    p50 = np.percentile(price_paths, 50, axis=1)
    p75 = np.percentile(price_paths, 75, axis=1)
    p95 = np.percentile(price_paths, 95, axis=1)
    
    # 畫出區間
    ax.fill_between(x, p5, p95, color=accent_color, alpha=0.1, label="90% 信心區間 (GBM 修正)")
    ax.fill_between(x, p25, p75, color=accent_color, alpha=0.2, label="50% 核心預測範圍")
    ax.plot(x, p50, color=accent_color, linewidth=3, label="預期中位數走勢 (受限漂移率)")
    
    ax.axhline(current_price, color="#94A3B8", linestyle="--", alpha=0.6, label=f"目前價格 (${current_price:.2f})")
    
    ax.set_title(f"{ticker} 1年價格模擬 (漂移率上限 15%)", fontsize=20, fontweight='bold', color=fg_color, pad=20)
    ax.set_xlabel("未來交易日 (Days)", fontsize=14, color=fg_color)
    ax.set_ylabel("價格 (USD)", fontsize=14, color=fg_color)
    
    ax.grid(True, linestyle=":", alpha=0.3, color=grid_color)
    ax.tick_params(colors=fg_color, labelsize=11)
    ax.legend(loc="upper left", fontsize=12, facecolor=bg_color, edgecolor=grid_color, labelcolor=fg_color)
    
    for spine in ax.spines.values():
        spine.set_color(grid_color)
        
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    return buf
