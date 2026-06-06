"""Math formula renderer — converts LaTeX $$...$$ / $...$ to PNG images.

Uses matplotlib's built-in mathtext, no LaTeX installation required.
"""

import re
import hashlib
from pathlib import Path

_MATH_DIR = None


def _get_math_dir() -> Path:
    global _MATH_DIR
    if _MATH_DIR is None:
        _MATH_DIR = Path(__file__).resolve().parent.parent.parent / ".temp" / "math"
        _MATH_DIR.mkdir(parents=True, exist_ok=True)
    return _MATH_DIR


def _render_to_png(formula: str) -> str | None:
    """Render a LaTeX formula to PNG using matplotlib mathtext.

    Returns the relative path to the PNG, or None on failure.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use("Agg")
    except ImportError:
        return None

    formula_key = hashlib.md5(formula.encode()).hexdigest()[:12]
    out_path = _get_math_dir() / f"f_{formula_key}.png"
    if out_path.exists():
        return str(out_path.resolve())  # relative to project root

    try:
        fig, ax = plt.subplots(figsize=(0.01, 0.01))
        ax.set_axis_off()
        ax.text(0, 0, f"${formula}$", fontsize=16, va="bottom", ha="left")
        fig.savefig(
            out_path, dpi=100,
            bbox_inches="tight", pad_inches=0.05,
            transparent=True,
        )
        plt.close(fig)
        if out_path.exists():
            return str(out_path.resolve())
        return None
    except Exception:
        plt.close("all")
        return None


def render_math(text: str) -> str:
    """Scan text for $$...$$ and $...$ formulas, replace with image refs.

    Falls back to raw LaTeX in backticks if rendering fails.
    """
    def _replace(m, display=False):
        formula = m.group(1).strip()
        if not formula:
            return m.group(0)
        img_path = _render_to_png(formula)
        if img_path:
            # Use working-dir-relative path for Flet Markdown to resolve
            abs_path = str(Path(img_path).resolve())
            return f"![]({abs_path})"
        return f"`${formula}$`"

    # Block formulas: $$...$$ (render same as inline for simplicity)
    text = re.sub(
        r"\$\$(.*?)\$\$",
        lambda m: _replace(m, display=True),
        text, flags=re.DOTALL,
    )
    # Inline formulas: $...$
    text = re.sub(
        r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)",
        lambda m: _replace(m, display=False),
        text,
    )
    return text
