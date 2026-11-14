"""code-viz headless stand-in for ezgraphics (the GraphicsWindow library from Horstmann's Python
for Everyone, used in CS170), drawing with matplotlib instead of a tkinter window.

Full manual: the header of code-viz (`code-viz readme`, or README.md), section 7 (Figures).

tracers/driver.py puts /viz/tracers/pystubs first on PYTHONPATH, so `from ezgraphics import
GraphicsWindow` in an example loads this file. Each GraphicsWindow records what is drawn on its
canvas and, at win.wait(), win.close() or when the program ends, saves it as one figure through
cviz_mplbackend.save_figure (win.pause() saves a figure too, so an animation shows as frames, up to
the figure cap). Coordinates are canvas pixels with y growing downward, as in ezgraphics.
An endless animation is stopped after CVIZ_DRAW_MAX drawing calls (default 1000): every window is
saved as it is then, a note is printed, and the program ends normally. Supported on the canvas: setFill, setOutline, setColor, setLineWidth, setBackground, setTextFont
(kept but not applied), drawRect/drawRectangle, drawOval, drawLine, drawPoint, drawPolygon,
drawText, drawArc, clear, width, height. On the window: canvas, setTitle, wait, pause, close,
isValid. Anything else raises AttributeError.
"""
import atexit
import os
import sys

_calls = [0]    # drawing calls so far, across windows (an endless animation is stopped, see _stop)


def _stop():
    """An endless animation (`while True:` drawing frames) never reaches win.wait(): after
    CVIZ_DRAW_MAX drawing calls (default 1000) save every window as it is now and end the program
    normally, so the example shows its canvas at that point instead of timing out."""
    for w in _windows:
        if w._open:
            w.wait()
    print("(code-viz: stopped the drawing after %d drawing calls; the figure shows the canvas then)" % _calls[0])
    sys.exit(0)


def _c(c):
    if c is None:
        return None
    if isinstance(c, (tuple, list)) and len(c) == 3:
        return tuple(v / 255 for v in c)
    return c


class GraphicsCanvas:
    def __init__(self, w, h):
        self._w, self._h = w, h
        self.ops = []
        self.fill, self.outline, self.lw, self.bg = None, "black", 1, "white"

    def width(self):
        return self._w

    def height(self):
        return self._h

    def setFill(self, *c):
        self.fill = _c(c[0] if len(c) == 1 else c) if c else None

    def setOutline(self, *c):
        self.outline = _c(c[0] if len(c) == 1 else c) if c else None

    def setColor(self, *c):
        self.setFill(*c)
        self.setOutline(*c)

    def setLineWidth(self, w):
        self.lw = w

    def setBackground(self, *c):
        self.bg = _c(c[0] if len(c) == 1 else c)

    def setTextFont(self, *a, **k):
        pass

    def clear(self):
        self.ops = []

    def _add(self, kind, *args):
        self.ops.append((kind, args, self.fill, self.outline, self.lw))
        _calls[0] += 1
        if _calls[0] >= int(os.environ.get("CVIZ_DRAW_MAX", "1000")):
            _stop()

    def drawRect(self, x, y, w, h):
        self._add("rect", x, y, w, h)
    drawRectangle = drawRect

    def drawOval(self, x, y, w, h):
        self._add("oval", x, y, w, h)

    def drawArc(self, x, y, diameter, start, extent):
        self._add("arc", x, y, diameter, start, extent)

    def drawLine(self, x1, y1, x2, y2):
        self._add("line", x1, y1, x2, y2)

    def drawPoint(self, x, y):
        self._add("point", x, y)

    def drawPolygon(self, *pts):
        if len(pts) == 1:
            pts = pts[0]
        flat = [v for p in pts for v in (p if isinstance(p, (tuple, list)) else (p,))]
        self._add("poly", list(zip(flat[0::2], flat[1::2])))

    def drawText(self, x, y, text):
        self._add("text", x, y, str(text))

    def render(self):
        import matplotlib.pyplot as plt
        from matplotlib import patches
        fig, ax = plt.subplots(figsize=(self._w / 100, self._h / 100))
        fig.subplots_adjust(0, 0, 1, 1)
        ax.set_xlim(0, self._w)
        ax.set_ylim(self._h, 0)
        ax.set_facecolor(self.bg)
        ax.set_xticks([])
        ax.set_yticks([])
        for kind, a, fill, out, lw in self.ops:
            fc = fill if fill is not None else "none"
            ec = out if out is not None else "none"
            if kind == "rect":
                ax.add_patch(patches.Rectangle((a[0], a[1]), a[2], a[3], facecolor=fc, edgecolor=ec, linewidth=lw))
            elif kind == "oval":
                ax.add_patch(patches.Ellipse((a[0] + a[2] / 2, a[1] + a[3] / 2), a[2], a[3], facecolor=fc, edgecolor=ec, linewidth=lw))
            elif kind == "arc":
                ax.add_patch(patches.Arc((a[0] + a[2] / 2, a[1] + a[2] / 2), a[2], a[2], theta1=-(a[3] + a[4]), theta2=-a[3], edgecolor=ec, linewidth=lw))
            elif kind == "line":
                ax.plot([a[0], a[2]], [a[1], a[3]], color=ec if out is not None else "black", linewidth=lw)
            elif kind == "point":
                ax.plot([a[0]], [a[1]], ",", color=ec if out is not None else "black")
            elif kind == "poly":
                ax.add_patch(patches.Polygon(a[0], closed=True, facecolor=fc, edgecolor=ec, linewidth=lw))
            elif kind == "text":
                ax.text(a[0], a[1], a[2], color=ec if out is not None else "black", va="top")
        return fig


_windows = []


class GraphicsWindow:
    def __init__(self, width=400, height=400):
        self._canvas = GraphicsCanvas(width, height)
        self._open, self._saved = True, 0
        _windows.append(self)

    def canvas(self):
        return self._canvas

    def setTitle(self, title):
        self.title = title

    def isValid(self):
        return self._open

    def _save(self):
        import matplotlib.pyplot as plt
        import cviz_mplbackend
        if not self._canvas.ops:
            return
        fig = self._canvas.render()
        cviz_mplbackend.save_figure(fig)
        plt.close(fig)
        self._saved += 1

    def pause(self, *a):
        self._save()

    def wait(self):
        if self._open:
            self._save()
            self._open = False

    close = wait


def _at_exit():
    for w in _windows:
        if w._open and not w._saved:
            w.wait()


atexit.register(_at_exit)
