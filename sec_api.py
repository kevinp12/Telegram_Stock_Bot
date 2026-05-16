"""sec_api.py
所有 SEC EDGAR 財報抓取與解析邏輯。
遵守 SEC 官方存取規範，提供免費、即時且穩定的數據來源。
"""

import logging
import time
import requests
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# SEC API 規範：必須提供明確的 User-Agent，否則會收到 403 Forbidden。
# 格式範例：MyTelegramQuantBot/1.0 (huangkevinp12@gmail.com)
# --------------------------------------------------------------------------
SEC_HEADERS = {
    "User-Agent": "MyTelegramQuantBot/1.0 (huangkevinp12@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov"
}

SEC_DATA_HEADERS = {
    "User-Agent": SEC_HEADERS["User-Agent"],
    "Accept-Encoding": SEC_HEADERS["Accept-Encoding"],
    "Host": "data.sec.gov",
}

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# 本地快取，減少重複請求 CIK 對照表
_CIK_MAP: Dict[str, str] = {}
_CIK_MAP_LOADED_AT: float = 0.0
CIK_MAP_TTL_SECONDS = 6 * 60 * 60

def _load_cik_map(force_refresh: bool = False) -> None:
    """從 SEC 官方獲取所有上市公司的 Ticker 與 CIK 映射關係。"""
    global _CIK_MAP, _CIK_MAP_LOADED_AT
    now = time.time()
    if not force_refresh and _CIK_MAP and (now - _CIK_MAP_LOADED_AT) < CIK_MAP_TTL_SECONDS:
        return
    try:
        response = requests.get(SEC_TICKER_MAP_URL, headers=SEC_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        new_map: Dict[str, str] = {}
        # 映射格式：{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        for entry in data.values():
            ticker = str(entry["ticker"]).upper().strip()
            cik_str = str(entry["cik_str"]).zfill(10)  # CIK 必須補滿 10 位數
            new_map[ticker] = cik_str
        _CIK_MAP = new_map
        _CIK_MAP_LOADED_AT = now
    except Exception as exc:
        logging.error(f"Failed to load SEC CIK map: {exc}")

def get_cik(ticker: str) -> Optional[str]:
    """透過 Ticker 獲取 CIK 編碼。"""
    _load_cik_map()
    return _CIK_MAP.get(ticker.upper())

def get_financial_diagnostics(ticker: str) -> Dict[str, Any]:
    """回傳 SEC 財報可用性診斷資訊，供 /fin 錯誤訊息顯示。"""
    symbol = (ticker or "").upper().strip()
    result: Dict[str, Any] = {
        "symbol": symbol,
        "ok": False,
        "reason": "unknown",
        "cik": None,
        "http_status": None,
        "details": {},
    }
    cik = get_cik(symbol)
    result["cik"] = cik
    if not cik:
        result["reason"] = "cik_not_found"
        return result

    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        response = requests.get(url, headers=SEC_DATA_HEADERS, timeout=15)
        result["http_status"] = response.status_code
        if response.status_code != 200:
            result["reason"] = "companyfacts_http_error"
            return result

        facts = response.json().get('facts', {}).get('us-gaap', {})
        pools = {
            "revenue": (['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'TotalRevenuesAndOtherIncome'], 'USD'),
            "net_income": (['NetIncomeLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic', 'NetIncomeLossAvailableToCommonStockholdersDiluted', 'ProfitLoss'], 'USD'),
            "eps": (['EarningsPerShareDiluted', 'EarningsPerShareBasic', 'CommonStockEarningsPerShareDiluted', 'NetIncomeLossAvailableToCommonStockholdersBasicPerCommonShare'], 'USD/shares'),
        }
        missing = []
        for key, (tags, unit) in pools.items():
            df = parse_facts_tag(facts, tags, unit)
            if df.empty:
                missing.append(key)
                result["details"][key] = {"rows": 0, "latest_end": None}
            else:
                result["details"][key] = {
                    "rows": int(len(df)),
                    "latest_end": str(pd.to_datetime(df['end']).max().date()),
                }

        if missing:
            result["reason"] = f"missing_core_data:{','.join(missing)}"
            return result

        result["ok"] = True
        result["reason"] = "ok"
        return result
    except Exception as exc:
        result["reason"] = f"exception:{exc}"
        return result

def parse_facts_tag(facts_data: dict, tags: list, unit_type: str = 'USD') -> pd.DataFrame:
    """從 SEC facts 中嘗試多個常見的 XBRL 會計標籤"""
    best_df = pd.DataFrame()
    best_last_end = pd.Timestamp.min

    for tag in tags:
        if tag in facts_data:
            units = facts_data[tag].get('units', {})
            if unit_type in units:
                df = pd.DataFrame(units[unit_type])

                # 預處理日期
                df['end'] = pd.to_datetime(df['end'])
                if 'start' in df.columns and 'end' in df.columns:
                    df['start'] = pd.to_datetime(df['start'])
                    df['days'] = (df['end'] - df['start']).dt.days
                    # 放寬過濾範圍 (60~110天)，確保能抓到 NVDA 等非標準週期的季報
                    # 同時優先保留單季數據，剔除全年(365天)累計數據
                    df = df[(df['days'] >= 60) & (df['days'] <= 110)].copy()
                else:
                    df['days'] = 0 # 瞬間值標籤 (如股數)

                # 篩選標準報表 (不分大小寫，包含修正案 /A)
                df = df[df['form'].str.contains('10-Q|10-K', na=False, case=False)].copy()

                if not df.empty:
                    last_end = df['end'].max()
                    # 挑選「最新結束日」最大的標籤；若相同則保留筆數較多者
                    if last_end > best_last_end or (last_end == best_last_end and len(df) > len(best_df)):
                        best_df = df
                        best_last_end = last_end
    return best_df

def fetch_sec_financials(ticker: str) -> Optional[pd.DataFrame]:
    """從 SEC 抓取最新財報並清洗為標準 DataFrame"""
    cik = get_cik(ticker)
    if not cik:
        return None

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        response = requests.get(url, headers=SEC_DATA_HEADERS, timeout=15)
        if response.status_code != 200:
            # 資料新鮮度策略：若 companyfacts 失敗，強制刷新 CIK map 後重試一次
            _load_cik_map(force_refresh=True)
            fresh_cik = _CIK_MAP.get(ticker.upper(), cik)
            retry_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{fresh_cik}.json"
            retry_resp = requests.get(retry_url, headers=SEC_DATA_HEADERS, timeout=15)
            if retry_resp.status_code != 200:
                logging.warning(
                    "SEC companyfacts request failed for %s (cik=%s retry_cik=%s): HTTP %s/%s",
                    ticker,
                    cik,
                    fresh_cik,
                    response.status_code,
                    retry_resp.status_code,
                )
                return None
            response = retry_resp
            cik = fresh_cik
        
        facts = response.json().get('facts', {}).get('us-gaap', {})
        
        # 營收標籤池
        rev_tags = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'TotalRevenuesAndOtherIncome']
        # 淨利標籤池
        ni_tags = ['NetIncomeLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic', 'NetIncomeLossAvailableToCommonStockholdersDiluted', 'ProfitLoss']
        # 毛利與營業利益（用於組成圖）
        gp_tags = ['GrossProfit']
        op_tags = ['OperatingIncomeLoss']
        
        df_rev = parse_facts_tag(facts, rev_tags, 'USD')
        df_ni = parse_facts_tag(facts, ni_tags, 'USD')
        df_gp = parse_facts_tag(facts, gp_tags, 'USD')
        df_op = parse_facts_tag(facts, op_tags, 'USD')
        # 優先抓取稀釋後 EPS，並擴大標籤池
        df_eps = parse_facts_tag(facts, [
            'EarningsPerShareDiluted', 
            'EarningsPerShareBasic', 
            'CommonStockEarningsPerShareDiluted',
            'NetIncomeLossAvailableToCommonStockholdersBasicPerCommonShare'
        ], 'USD/shares')

        if df_rev.empty or df_ni.empty or df_eps.empty:
            logging.warning(f"SEC 核心數據缺失 {ticker}: 營收={len(df_rev)}, 淨利={len(df_ni)}, EPS={len(df_eps)}")
            return None

        def _clean_and_align(df, name):
            if df is None or df.empty: return pd.DataFrame(columns=['end', name])
            # 保留最新申報版本
            df = df.sort_values(by=['end', 'filed'])
            # NVDA 等公司結算日可能在週末或週一，統一將日期調整至該月最後一天
            # 使用 normalize() 確保時間戳完全一致，避免合併失敗
            df['end'] = (df['end'] + pd.offsets.MonthEnd(0)).dt.normalize()
            return df.drop_duplicates(subset=['end'], keep='last')[['end', 'val']].rename(columns={'val': name})

        df_rev = _clean_and_align(df_rev, 'revenue')
        df_ni = _clean_and_align(df_ni, 'net_income')
        df_eps = _clean_and_align(df_eps, 'eps')
        df_gp = _clean_and_align(df_gp, 'gross_profit') if not df_gp.empty else pd.DataFrame()
        df_op = _clean_and_align(df_op, 'op_income') if not df_op.empty else pd.DataFrame()

        # 合併數據 (使用 outer join 避免單一日期微差導致整季資料消失)
        df_final = df_rev.merge(df_ni, on='end', how='outer').merge(df_eps, on='end', how='outer')
        if not df_gp.empty:
            df_final = df_final.merge(df_gp, on='end', how='left')
        if not df_op.empty:
            df_final = df_final.merge(df_op, on='end', how='left')

        df_final = df_final.dropna(subset=['revenue', 'net_income', 'eps'])
        df_final = df_final.sort_values(by='end', ascending=True)
        
        # 計算成長率
        df_final['rev_growth'] = df_final['revenue'].pct_change() * 100
        
        return df_final
    except Exception as e:
        logging.error(f"SEC API error for {ticker}: {e}")
        return None

def get_sec_fundamentals_legacy(ticker: str) -> Dict[str, Any]:
    """維持舊介面的包裝函數。"""
    df = fetch_sec_financials(ticker)
    if df is None or df.empty:
        return {"error": "No SEC data"}
    
    # 將 DataFrame 轉回舊格式清單以相容於其他模組
    latest = df.iloc[::-1].head(8) # 最近 8 季
    revenue_list = [{"end": str(d.date()), "val": v} for d, v in zip(latest.end, latest.revenue)]
    net_income_list = [{"end": str(d.date()), "val": v} for d, v in zip(latest.end, latest.net_income)]
    eps_list = [{"end": str(d.date()), "val": v} for d, v in zip(latest.end, latest.eps)]
    
    return {
        "ticker": ticker.upper(),
        "company_name": ticker.upper(),
        "revenue": revenue_list,
        "net_income": net_income_list,
        "eps": eps_list,
    }