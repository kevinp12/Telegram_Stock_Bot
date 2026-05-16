import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any


_CJK_FONT_CANDIDATES = [
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "Heiti TC",
    "PingFang HK",
    "PingFang TC",
    "Hiragino Sans CNS",
    "Arial Unicode MS",
    "Songti SC",
]

_EMOJI_FONT_CANDIDATES = [
    "Noto Color Emoji",
    "Noto Emoji",
    "Segoe UI Emoji",
    "Apple Color Emoji",
]


_PROJECT_ROOT = Path(__file__).resolve().parent
_PROJECT_FONT_DIRS = [
    _PROJECT_ROOT / "fonts",
    _PROJECT_ROOT / "assets" / "fonts",
]


def _register_project_fonts() -> None:
    """註冊專案內可攜式字型，讓 GCP 無系統字型時仍可顯示中文。"""
    try:
        from matplotlib import font_manager as fm

        extra_font_dir = os.getenv("CJK_FONT_DIR", "").strip()
        font_dirs = list(_PROJECT_FONT_DIRS)
        if extra_font_dir:
            font_dirs.insert(0, Path(extra_font_dir))

        loaded = 0
        for font_dir in font_dirs:
            if not font_dir.exists() or not font_dir.is_dir():
                continue
            for ext in ("*.ttf", "*.otf", "*.ttc"):
                # 遞迴掃描，支援像 fonts/Noto_Sans_TC/static/*.ttf 這種巢狀結構
                for fp in font_dir.rglob(ext):
                    try:
                        fm.fontManager.addfont(str(fp))
                        loaded += 1
                    except Exception:
                        continue

        if loaded > 0:
            # 重新建立字型清單快取，確保本次進程立即可用
            fm._load_fontmanager(try_read_cache=False)
    except Exception:
        pass


def _pick_available_cjk_font() -> str:
    """挑選目前環境真的存在的 CJK 字型名稱。"""
    try:
        from matplotlib import font_manager as fm

        _register_project_fonts()

        available = {f.name for f in fm.fontManager.ttflist}
        for name in _CJK_FONT_CANDIDATES:
            if name in available:
                return name
    except Exception:
        pass
    return "DejaVu Sans"


def _pick_available_emoji_fonts() -> list[str]:
    """挑選目前環境可用的 emoji 字型清單（依偏好順序）。"""
    try:
        from matplotlib import font_manager as fm

        _register_project_fonts()
        available = {f.name for f in fm.fontManager.ttflist}
        return [name for name in _EMOJI_FONT_CANDIDATES if name in available]
    except Exception:
        return []


def debug_cjk_font_loading() -> dict[str, Any]:
    """回傳字型載入診斷資訊，方便在 GCP 排查路徑/字型是否命中。"""
    info: dict[str, Any] = {
        "cjk_font_dir_env": os.getenv("CJK_FONT_DIR", "").strip(),
        "project_font_dirs": [str(p) for p in _PROJECT_FONT_DIRS],
        "scanned_files": [],
        "picked_font": None,
        "emoji_fonts": [],
        "env_dir_exists": False,
        "env_dir_is_dir": False,
        "scan_counts": {},
    }
    try:
        for base in [Path(info["cjk_font_dir_env"])] if info["cjk_font_dir_env"] else []:
            info["env_dir_exists"] = base.exists()
            info["env_dir_is_dir"] = base.is_dir()
            count = 0
            if base.exists() and base.is_dir():
                for ext in ("*.ttf", "*.otf", "*.ttc"):
                    matched = list(base.rglob(ext))
                    info["scanned_files"].extend(str(p) for p in matched)
                    count += len(matched)
            info["scan_counts"][str(base)] = count
        for base in _PROJECT_FONT_DIRS:
            count = 0
            if base.exists() and base.is_dir():
                for ext in ("*.ttf", "*.otf", "*.ttc"):
                    matched = list(base.rglob(ext))
                    info["scanned_files"].extend(str(p) for p in matched)
                    count += len(matched)
            info["scan_counts"][str(base)] = count
    except Exception:
        pass

    info["picked_font"] = _pick_available_cjk_font()
    info["emoji_fonts"] = _pick_available_emoji_fonts()
    # 去重避免重複列出
    info["scanned_files"] = sorted(set(info["scanned_files"]))
    return info


def setup_matplotlib_cjk_font(mpl_module=None) -> None:
    """統一設定 matplotlib 的中文字型與負號顯示。

    兼容兩種呼叫方式：
    - setup_matplotlib_cjk_font(mpl)
    - setup_matplotlib_cjk_font()  # 自動 import matplotlib
    """
    if mpl_module is None:
        try:
            import matplotlib as mpl_module  # type: ignore
        except Exception:
            return

    cjk_font = _pick_available_cjk_font()
    emoji_fonts = _pick_available_emoji_fonts()
    mpl_module.rcParams["font.family"] = "sans-serif"
    # 把第一優先直接鎖定為「本機確定存在」的字型，避免 fallback 到不支援中文字型
    mpl_module.rcParams["font.sans-serif"] = [cjk_font, *emoji_fonts, "DejaVu Sans"]
    mpl_module.rcParams["axes.unicode_minus"] = False


def get_matplotlib_cjk_rc() -> dict:
    """提供可注入 style/rc 的統一中文字型設定。"""
    cjk_font = _pick_available_cjk_font()
    emoji_fonts = _pick_available_emoji_fonts()
    return {
        "font.family": "sans-serif",
        "font.sans-serif": [cjk_font, *emoji_fonts, "DejaVu Sans"],
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
