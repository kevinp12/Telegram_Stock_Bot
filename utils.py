from decimal import ROUND_HALF_UP, Decimal
from typing import Any


_CJK_FONT_CANDIDATES = [
    "Heiti TC",
    "PingFang HK",
    "PingFang TC",
    "Hiragino Sans CNS",
    "Arial Unicode MS",
    "Songti SC",
]


def _pick_available_cjk_font() -> str:
    """挑選目前環境真的存在的 CJK 字型名稱。"""
    try:
        from matplotlib import font_manager as fm

        available = {f.name for f in fm.fontManager.ttflist}
        for name in _CJK_FONT_CANDIDATES:
            if name in available:
                return name
    except Exception:
        pass
    return "DejaVu Sans"


def setup_matplotlib_cjk_font(mpl_module) -> None:
    """統一設定 matplotlib 的中文字型與負號顯示。"""
    cjk_font = _pick_available_cjk_font()
    mpl_module.rcParams["font.family"] = "sans-serif"
    # 把第一優先直接鎖定為「本機確定存在」的字型，避免 fallback 到不支援中文字型
    mpl_module.rcParams["font.sans-serif"] = [cjk_font, "DejaVu Sans"]
    mpl_module.rcParams["axes.unicode_minus"] = False


def get_matplotlib_cjk_rc() -> dict:
    """提供可注入 style/rc 的統一中文字型設定。"""
    cjk_font = _pick_available_cjk_font()
    return {
        "font.family": "sans-serif",
        "font.sans-serif": [cjk_font, "DejaVu Sans"],
        "axes.unicode_minus": False,
    }


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
