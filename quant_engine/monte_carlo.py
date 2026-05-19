import numpy as np
import pandas as pd
import io
import logging


TRADING_DAYS = 252


def _fit_arch_garch_params(returns: np.ndarray) -> dict[str, float] | None:
    """使用 arch 套件正式擬合 GARCH(1,1)-t；失敗時回傳 None 走 fallback。"""
    if len(returns) < 80:
        return None
    try:
        from arch import arch_model

        scaled_returns = returns * 100  # arch 用百分比尺度較穩定
        model = arch_model(scaled_returns, mean="Constant", vol="GARCH", p=1, q=1, dist="t", rescale=False)
        fit = model.fit(disp="off", show_warning=False)
        params = fit.params
        omega = float(params.get("omega", np.var(scaled_returns) * 0.02)) / 10000
        alpha = float(params.get("alpha[1]", 0.08))
        beta = float(params.get("beta[1]", 0.90))
        nu = float(params.get("nu", 5.0))
        if alpha + beta >= 0.995:
            scale = 0.995 / (alpha + beta)
            alpha *= scale
            beta *= scale
        cond_vol = np.asarray(fit.conditional_volatility, dtype=float) / 100
        last_var = float(cond_vol[-1] ** 2) if len(cond_vol) else float(np.var(returns))
        return {
            "omega": max(omega, 1e-10),
            "alpha": max(alpha, 0.0),
            "beta": max(beta, 0.0),
            "last_var": max(last_var, 1e-10),
            "nu": max(nu, 3.1),
            "source": "arch GARCH(1,1)-t",
        }
    except Exception as exc:
        logging.warning("arch GARCH fit failed, fallback to lightweight params: %s", exc)
        return None


def _fit_garch_like_params(returns: np.ndarray) -> dict[str, float]:
    """輕量 GARCH(1,1) 近似參數；不新增 arch 依賴，避免部署負擔。"""
    if len(returns) < 30:
        vol = float(np.std(returns)) or 0.02
        return {"omega": vol**2 * 0.05, "alpha": 0.08, "beta": 0.90, "last_var": vol**2, "nu": 5.0, "source": "fallback GARCH-like"}

    variance = float(np.var(returns)) or 0.0004
    # 以保守且穩定的金融市場常用區間近似：alpha + beta < 1
    alpha = 0.08
    beta = 0.90
    omega = max(variance * (1 - alpha - beta), 1e-10)
    recent_var = float(np.var(returns[-20:])) if len(returns) >= 20 else variance
    return {"omega": omega, "alpha": alpha, "beta": beta, "last_var": max(recent_var, 1e-10), "nu": 5.0, "source": "fallback GARCH-like"}


def _robust_drift(log_returns: pd.Series) -> float:
    """降低歷史噪聲偏誤：混合中位數、截尾平均與保守 CAPM-like 年化上限。"""
    clean = log_returns.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return 0.06 / TRADING_DAYS
    q05, q95 = np.percentile(clean, [5, 95])
    clipped = clean.clip(q05, q95)
    historical_daily = 0.5 * float(clipped.mean()) + 0.5 * float(clean.median())
    # 保守長期股票風險溢酬近似：年化 6%，再與歷史資料混合。
    capm_like_daily = 0.06 / TRADING_DAYS
    blended_daily = 0.35 * historical_daily + 0.65 * capm_like_daily
    # 防止近期飆股/崩跌把一年預測拉到不合理區間。
    return float(np.clip(blended_daily, -0.20 / TRADING_DAYS, 0.20 / TRADING_DAYS))


def run_monte_carlo(df: pd.DataFrame, days: int = 252, simulations: int = 2000):
    """
    執行強化版蒙地卡羅：Student-t 肥尾 + GARCH-like 動態波動 + Merton Jump Diffusion。
    """
    if df.empty or len(df) < 20:
        return None
        
    # 1. 計算對數報酬率 (Log Returns)
    log_returns = np.log(df['Close'] / df['Close'].shift(1)).dropna()
    clean_returns = log_returns.replace([np.inf, -np.inf], np.nan).dropna().values
    if len(clean_returns) < 20:
        return None
    
    current_price = float(df['Close'].iloc[-1])
    daily_mu = _robust_drift(log_returns)
    params = _fit_arch_garch_params(clean_returns) or _fit_garch_like_params(clean_returns)
    base_daily_vol = float(np.std(clean_returns)) or 0.02

    # 2. 跳躍擴散參數：用歷史 3σ 以外事件估計跳躍頻率與幅度，資料不足時採保守預設。
    extreme_threshold = 3 * base_daily_vol
    jumps = clean_returns[np.abs(clean_returns - np.mean(clean_returns)) > extreme_threshold]
    jump_lambda_daily = float(np.clip(len(jumps) / max(len(clean_returns), 1), 0.002, 0.04))
    jump_mu = float(np.mean(jumps)) if len(jumps) else 0.0
    jump_sigma = float(np.std(jumps)) if len(jumps) > 1 else max(base_daily_vol * 2.5, 0.03)

    # 3. 模擬：Student-t 肥尾 + GARCH-like 波動率聚集 + Poisson 跳躍。
    price_paths = np.empty((days, simulations), dtype=float)
    prices = np.full(simulations, current_price, dtype=float)
    variances = np.full(simulations, params["last_var"], dtype=float)
    dof = float(params.get("nu", 5.0))  # Student-t 自由度，arch 可估計肥尾程度

    for day in range(days):
        z = np.random.standard_t(df=dof, size=simulations) / np.sqrt(dof / (dof - 2))
        sigma = np.sqrt(np.maximum(variances, 1e-10))
        jump_counts = np.random.poisson(jump_lambda_daily, size=simulations)
        jump_component = np.where(jump_counts > 0, np.random.normal(jump_mu, jump_sigma, simulations) * jump_counts, 0.0)
        simulated_returns = (daily_mu - 0.5 * variances) + sigma * z + jump_component
        prices = prices * np.exp(simulated_returns)
        price_paths[day, :] = prices
        variances = params["omega"] + params["alpha"] * np.square(simulated_returns) + params["beta"] * variances
    
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
        "cvar_95_pct": cvar_pct,
        "model": f"Student-t + {params.get('source', 'GARCH-like')} + Merton Jump Diffusion",
        "garch_source": str(params.get("source", "GARCH-like")),
        "annualized_drift_pct": daily_mu * TRADING_DAYS * 100,
        "annualized_vol_pct": base_daily_vol * np.sqrt(TRADING_DAYS) * 100,
        "jump_lambda_annual": jump_lambda_daily * TRADING_DAYS,
        "jump_sigma_pct": jump_sigma * 100,
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
    ax.fill_between(x, p5, p95, color=accent_color, alpha=0.1, label="90% 信心區間 (肥尾/跳躍修正)")
    ax.fill_between(x, p25, p75, color=accent_color, alpha=0.2, label="50% 核心預測範圍")
    ax.plot(x, p50, color=accent_color, linewidth=3, label="預期中位數走勢 (動態波動)")
    
    ax.axhline(current_price, color="#94A3B8", linestyle="--", alpha=0.6, label=f"目前價格 (${current_price:.2f})")
    
    ax.set_title(f"{ticker} 1年價格模擬 (Student-t + GARCH + Jump)", fontsize=20, fontweight='bold', color=fg_color, pad=20)
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
