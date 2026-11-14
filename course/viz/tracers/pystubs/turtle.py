"""code-viz headless stand-in for the standard turtle module (no window, no tkinter).

Full manual: the header of code-viz (`code-viz readme`, or README.md), section 7 (Figures).

tracers/driver.py puts /viz/tracers/pystubs first on PYTHONPATH, so `import turtle` in an example
loads this file instead of the real module. It records the drawing (moves with the pen down, fills,
dots, text) and, at done()/mainloop()/exitonclick()/bye() or when the program ends, draws it with
matplotlib and saves it through cviz_mplbackend.save_figure, so the drawing appears in the
example's figures. Supported: Turtle() and the module-level functions forward/fd, backward/bk/back,
right/rt, left/lt, goto/setpos/setposition/teleport, setx, sety, setheading/seth, home, circle,
dot, penup/pu/up, pendown/pd/down, pencolor, fillcolor, color, pensize/width, begin_fill, end_fill,
write, position/pos, xcor, ycor, heading, isdown, and as no-ops speed, shape, showturtle/st,
hideturtle/ht, tracer, update, delay, bgpic, title, setup, Screen().bgcolor (kept), screensize.
Anything else raises AttributeError, so an example using it fails visibly instead of drawing wrong.
An endless drawing loop is stopped after CVIZ_DRAW_MAX moves (default 1000): the drawing so far is
saved, a note is printed, and the program ends normally.
"""
import atexit
import math
import os
import sys

_calls = [0]        # moves so far: an endless drawing loop is stopped after CVIZ_DRAW_MAX (1000)

_drawings = []      # every Turtle's segments: (xs, ys, color, width)
_fills = []         # (xs, ys, color)
_texts = []         # (x, y, text, color)
_dots = []          # (x, y, size, color)
_bg = ["white"]
_done = [False]


class Turtle:
    def __init__(self, *a, **k):
        self._x, self._y, self._h = 0.0, 0.0, 0.0
        self._down, self._pc, self._fc, self._w = True, "black", "black", 1
        self._fill = None
        _all.append(self)

    def _move(self, x, y):
        _calls[0] += 1
        if _calls[0] >= int(os.environ.get("CVIZ_DRAW_MAX", "1000")):
            done()
            print("(code-viz: stopped the drawing after %d moves; the figure shows it then)" % _calls[0])
            sys.exit(0)
        if self._down:
            _drawings.append(([self._x, x], [self._y, y], self._pc, self._w))
        if self._fill is not None:
            self._fill.append((x, y))
        self._x, self._y = float(x), float(y)

    def forward(self, d):
        r = math.radians(self._h)
        self._move(self._x + d * math.cos(r), self._y + d * math.sin(r))
    fd = forward

    def backward(self, d):
        self.forward(-d)
    bk = back = backward

    def right(self, a):
        self._h = (self._h - a) % 360
    rt = right

    def left(self, a):
        self._h = (self._h + a) % 360
    lt = left

    def goto(self, x, y=None):
        if y is None:
            x, y = x
        self._move(x, y)
    setpos = setposition = teleport = goto

    def setx(self, x):
        self._move(x, self._y)

    def sety(self, y):
        self._move(self._x, y)

    def setheading(self, a):
        self._h = a % 360
    seth = setheading

    def home(self):
        self._move(0, 0)
        self._h = 0.0

    def circle(self, radius, extent=360, steps=None):
        n = steps or max(12, int(abs(extent) / 6))
        step = extent / n
        length = 2 * math.pi * abs(radius) * abs(extent) / 360 / n
        for _ in range(n):
            self.left(step / 2 if radius >= 0 else -step / 2)
            self.forward(length)
            self.left(step / 2 if radius >= 0 else -step / 2)

    def dot(self, size=None, *color):
        _dots.append((self._x, self._y, size or max(self._w + 4, 2 * self._w), _color(color) or self._pc))

    def penup(self):
        self._down = False
    pu = up = penup

    def pendown(self):
        self._down = True
    pd = down = pendown

    def isdown(self):
        return self._down

    def pencolor(self, *c):
        if c:
            self._pc = _color(c)
        return self._pc

    def fillcolor(self, *c):
        if c:
            self._fc = _color(c)
        return self._fc

    def color(self, *c):
        if len(c) == 2:
            self._pc, self._fc = _color(c[:1]), _color(c[1:])
        elif c:
            self._pc = self._fc = _color(c)
        return self._pc, self._fc

    def pensize(self, w=None):
        if w is not None:
            self._w = w
        return self._w
    width = pensize

    def begin_fill(self):
        self._fill = [(self._x, self._y)]

    def end_fill(self):
        if self._fill and len(self._fill) > 2:
            _fills.append(([p[0] for p in self._fill], [p[1] for p in self._fill], self._fc))
        self._fill = None

    def write(self, text, move=False, align="left", font=None):
        _texts.append((self._x, self._y, str(text), self._pc))

    def position(self):
        return (round(self._x, 6), round(self._y, 6))
    pos = position

    def xcor(self):
        return self._x

    def ycor(self):
        return self._y

    def heading(self):
        return self._h

    def _noop(self, *a, **k):
        return None
    speed = shape = showturtle = st = hideturtle = ht = shapesize = turtlesize = _noop


def _color(c):
    if not c:
        return None
    if len(c) == 1:
        c = c[0]
    if isinstance(c, (tuple, list)) and len(c) == 3:
        return tuple(v / 255 if max(c) > 1 else v for v in c)
    return c


class _Screen:
    def bgcolor(self, *c):
        if c:
            _bg[0] = _color(c)
        return _bg[0]

    def _noop(self, *a, **k):
        return None
    tracer = update = delay = bgpic = title = setup = screensize = mainloop = listen = onkey = onclick = ontimer = _noop

    def exitonclick(self):
        done()
    bye = exitonclick


_all = []
_default = []
_screen = _Screen()


def Screen():
    return _screen


def _t():
    if not _default:
        _default.append(Turtle())
    return _default[0]


def done():
    if _done[0]:
        return
    _done[0] = True
    if not (_drawings or _fills or _texts or _dots):
        return
    import matplotlib.pyplot as plt
    import cviz_mplbackend
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_facecolor(_bg[0])
    for xs, ys, c in _fills:
        ax.fill(xs, ys, color=c)
    for xs, ys, c, w in _drawings:
        ax.plot(xs, ys, color=c, linewidth=w, solid_capstyle="round")
    for x, y, s, c in _dots:
        ax.plot([x], [y], "o", color=c, markersize=s / 2)
    for x, y, s, c in _texts:
        ax.text(x, y, s, color=c)
    ax.set_aspect("equal")
    ax.axis("off")
    cviz_mplbackend.save_figure(fig)
    plt.close(fig)


mainloop = exitonclick = bye = done
atexit.register(done)

_FUNCS = ("forward fd backward bk back right rt left lt goto setpos setposition teleport setx sety setheading "
          "seth home circle dot penup pu up pendown pd down isdown pencolor fillcolor color pensize width "
          "begin_fill end_fill write position pos xcor ycor heading speed shape showturtle st hideturtle ht "
          "shapesize turtlesize").split()


def _make(name):
    def f(*a, **k):
        return getattr(_t(), name)(*a, **k)
    f.__name__ = name
    return f


for _n in _FUNCS:
    globals()[_n] = _make(_n)


def bgcolor(*c):
    return _screen.bgcolor(*c)


def tracer(*a, **k):
    return None


update = delay = bgpic = title = setup = screensize = listen = onkey = onclick = ontimer = tracer
