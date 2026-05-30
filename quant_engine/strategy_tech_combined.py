import pandas as pd
import numpy as np

from . import data_loader


BT_MODEL_TEMPLATES = {
    1: {"name": "保守", "min_pos": 0.2, "mid_pos": 0.45, "max_pos": 0.65, "hard_stop": 0.86, "min_hold": 75},
    2: {"name": "普通", "min_pos": 0.25, "mid_pos": 0.55, "max_pos": 0.85, "hard_stop": 0.83, "min_hold": 90},
    3: {"name": "激進", "min_pos": 0.3, "mid_pos": 0.65, "max_pos": 0.9, "hard_stop": 0.80, "min_hold": 105},
}

def calculate_tech_signals(df: pd.DataFrame, model_id: int = 2) -> pd.DataFrame:
    """
    將 /tech 指標升級為「波段趨勢策略」：
    放寬進場條件以增加交易次數，出場改為長均線 + MACD 確認，並拉長鎖倉期。
    """
    if len(df) < 150:
        return pd.DataFrame()

    # 1. 指標計算
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['SMA_100'] = df['Close'].rolling(100).mean()
    df['SMA_150'] = df['Close'].rolling(150).mean()

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    
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
    df['Breakout_20'] = df['Close'] >= df['High'].rolling(20).max().shift(1) * 0.995
    df['Momentum_Recover'] = (df['EMA10'] > df['EMA20']) & (df['MACD'] > df['MACD'].shift(3))
    
    # 大盤濾網
    spy_df = data_loader.get_market_benchmark(years=12)
    df['Market_Filter'] = True
    if not spy_df.empty:
        # 大盤濾網放寬：SPY 站上 SMA200，或跌破但短期動能正在修復，也允許個股訊號觸發。
        spy_filter = (spy_df['Close'] > spy_df['SMA_200']) | (spy_df['Close'] > spy_df['Close'].rolling(20).mean())
        df['Market_Filter'] = spy_filter.reindex(df.index, method='ffill').fillna(True)

    # --- 進場邏輯 ---
    cond_ema_trend = (
        ((df['EMA20'] > df['EMA50']) & (df['Close'] > df['EMA20'] * 0.985))
        | ((df['EMA10'] > df['EMA20']) & (df['Close'] > df['EMA50'] * 0.97))
    )
    cond_fvg = df['FVG_Bull'].rolling(10).max() > 0
    cond_breakout_or_momentum = df['Breakout_20'] | df['Momentum_Recover']
    cond_rsi_safe = df['RSI'] < 78
    
    df['Raw_Buy_Signal'] = cond_ema_trend & (cond_fvg | cond_breakout_or_momentum) & cond_rsi_safe & df['Market_Filter']
    
    # --- 執行模擬 (自動市況切換：20%~80%，大熊市才接近空手) ---
    df['Position_Size'] = 0.0
    in_position = False
    entry_price = 0.0
    entry_index = 0

    model = BT_MODEL_TEMPLATES.get(int(model_id), BT_MODEL_TEMPLATES[2])
    min_pos = float(model["min_pos"])
    mid_pos = float(model["mid_pos"])
    max_pos = float(model["max_pos"])
    bear_pos = 0.0
    hard_stop_ratio = float(model["hard_stop"])
    min_hold_days = int(model.get("min_hold", 90))
    
    for i in range(150, len(df) - 1):
        market_ok = df.iat[i, df.columns.get_loc('Market_Filter')]
        close_price = df.iat[i, df.columns.get_loc('Close')]
        
        # 市況判斷：
        # - 大熊市：跌破 SMA150 且 EMA20<EMA50 且 MACD<0
        # - 偏多：站上 SMA100/SMA150 且 EMA20>EMA50
        # - 其他：中性
        ema20 = df.iat[i, df.columns.get_loc('EMA20')]
        ema50 = df.iat[i, df.columns.get_loc('EMA50')]
        sma100 = df.iat[i, df.columns.get_loc('SMA_100')]
        sma150 = df.iat[i, df.columns.get_loc('SMA_150')]
        macd_val = df.iat[i, df.columns.get_loc('MACD')]

        bear_market = (
            close_price < sma150
            and ema20 < ema50
            and macd_val < 0
            and (not market_ok)
        )
        bull_market = (
            close_price > sma100
            and close_price > sma150
            and ema20 > ema50
            and market_ok
        )

        # 低空手核心：只要不是大熊市，至少維持 20% 基礎倉位
        trend_ok = (
            close_price > sma100
            and close_price > sma150
            and market_ok
        )

        if not in_position:
            if df.iat[i, df.columns.get_loc('Raw_Buy_Signal')]:
                in_position = True
                entry_price = close_price
                entry_index = i
                # 有機會時投入 80%，避免過度保守
                df.iat[i+1, df.columns.get_loc('Position_Size')] = max_pos
            elif bear_market:
                # 大熊市才允許接近空手
                df.iat[i+1, df.columns.get_loc('Position_Size')] = bear_pos
            elif bull_market or trend_ok:
                df.iat[i+1, df.columns.get_loc('Position_Size')] = mid_pos
            else:
                df.iat[i+1, df.columns.get_loc('Position_Size')] = min_pos
        else:
            holding_days = i - entry_index
            hard_stop = close_price <= entry_price * hard_stop_ratio
            macd_negative = macd_val < 0
            below_long_ma = (
                close_price < sma100
                or close_price < sma150
            )
            long_exit = below_long_ma and macd_negative

            # 倉位分級：
            # 1) 強訊號：80%
            # 2) 偏多/趨勢在：50%
            # 3) 中性：20%
            # 4) 大熊市且滿足條件：0%
            # 買入後至少持有 75~105 個交易日，除非觸發極端停損。
            if hard_stop:
                in_position = False
                df.iat[i+1, df.columns.get_loc('Position_Size')] = 0
            elif df.iat[i, df.columns.get_loc('Raw_Buy_Signal')] and (trend_ok or bull_market):
                df.iat[i+1, df.columns.get_loc('Position_Size')] = max_pos
            elif bear_market and holding_days >= min_hold_days and long_exit:
                in_position = False
                df.iat[i+1, df.columns.get_loc('Position_Size')] = 0
            elif bull_market or trend_ok:
                df.iat[i+1, df.columns.get_loc('Position_Size')] = mid_pos
            else:
                # 中性市況保留 20% 觀察倉，避免長時間空手
                df.iat[i+1, df.columns.get_loc('Position_Size')] = min_pos
                
    # --- 計算報酬與成本 ---
    fee_rate = 0.0012 
    df['Strategy_Return'] = df['Position_Size'].shift(1) * df['Close'].pct_change()
    trades = (df['Position_Size'] != df['Position_Size'].shift(1).fillna(0))
    df['Strategy_Return'] = df['Strategy_Return'] - (trades * fee_rate)
    
    df.fillna(0, inplace=True)
    # 只要有倉位就視為在場，供回測交易統計使用
    df['Position'] = (df['Position_Size'] > 0).astype(int)
    df['BT_Model'] = int(model_id) if int(model_id) in BT_MODEL_TEMPLATES else 2
    df['BT_Model_Name'] = str(model["name"])
    return df
