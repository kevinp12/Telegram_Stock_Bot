from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def setup_matplotlib_cjk_font(mpl_module) -> None:
    """統一設定 matplotlib 的中文字型與負號顯示。"""
    mpl_module.rcParams["font.family"] = "sans-serif"
    mpl_module.rcParams["font.sans-serif"] = [
        "PingFang TC",
        "Microsoft JhengHei",
        "Heiti TC",
        "Noto Sans CJK TC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    mpl_module.rcParams["axes.unicode_minus"] = False


def safe_round(value: Any, decimals: int = 2) -> Any:
    """安全地將數值四捨五入到指定位數 (使用 ROUND_HALF_UP)。"""
    if value is None or value == "N/A":
        return "N/A"
    try:
        # 使用 Decimal 進行精確的四捨五入 (ROUND_HALF_UP)
        d = Decimal(str(value))
        # 建立 quantize 的目標，例如 decimals=2 時為 '0.01'
        if decimals > 0:
            target = Decimal("0." + "0" * (decimals - 1) + "1")
        else:
            target = Decimal("1")
        return float(d.quantize(target, rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, Exception):
        return value
