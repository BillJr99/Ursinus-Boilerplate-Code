"""code-viz matplotlib backend: every figure a program shows (or leaves open at exit) becomes a PNG.

Full manual: the header of code-viz (`code-viz readme`, or README.md), section 7 (Figures).

How it is used: tracers/driver.py runs every Python example with MPLBACKEND=module://cviz_mplbackend,
PYTHONPATH=/viz/tracers:/viz/tracers/pystubs and CVIZ_FIGS=<a fresh folder for that example>. When the
program calls plt.show() (or exits with figures still open) each open figure is drawn with Agg and
written to CVIZ_FIGS as fig-NN.png, with a fig-NN.json beside it holding "at": how much printed
output came before it (so the viewer can show the figure at the right step of a stepped trace). The
driver reads the folder into the trace's "figures" list and removes it.

Determinism and size: a fixed DPI (CVIZ_FIG_DPI, default 72), no metadata (no Software tag, no
timestamp), at most CVIZ_FIG_MAX figures (default 8) per example, each at most 900 pixels wide (the
DPI is lowered for a larger figure). With no CVIZ_FIGS set it behaves like plain Agg.
"""
import atexit
import json
import os
import sys

from matplotlib.backend_bases import FigureManagerBase
from matplotlib.backends.backend_agg import FigureCanvasAgg

FigureCanvas = FigureCanvasAgg
FigureManager = FigureManagerBase

_count = [0]


def _out_so_far():
    out = sys.stdout
    try:
        return len(out.getvalue())          # pytrace prints into a StringIO
    except Exception:
        try:
            out.flush()
            return os.fstat(out.fileno()).st_size if not out.isatty() else 0
        except Exception:
            return 0


def save_figure(fig):
    """Write one figure as the next fig-NN.png in CVIZ_FIGS (also used by the turtle and ezgraphics
    stand-ins). Returns the path, or None when figures are not being collected or the cap is reached."""
    d = os.environ.get("CVIZ_FIGS")
    if not d or _count[0] >= int(os.environ.get("CVIZ_FIG_MAX", "8")):
        return None
    os.makedirs(d, exist_ok=True)
    dpi = float(os.environ.get("CVIZ_FIG_DPI", "72"))
    w = fig.get_figwidth()
    if w * dpi > 900:
        dpi = 900 / w
    _count[0] += 1
    path = os.path.join(d, f"fig-{_count[0]:02d}.png")
    fig.savefig(path, format="png", dpi=dpi, metadata={"Software": None})
    with open(path[:-4] + ".json", "w") as f:
        json.dump({"at": _out_so_far()}, f)
    return path


def _save_open():
    import matplotlib.pyplot as plt
    for num in plt.get_fignums():
        save_figure(plt.figure(num))
    plt.close("all")


def show(*args, **kwargs):
    _save_open()


atexit.register(_save_open)
