"""code-viz: make Python examples repeatable (loaded at interpreter start, because tracers/driver.py
puts /viz/tracers/pystubs on PYTHONPATH). Full manual: the header of code-viz, section 6 (Stable
traces).

What it does, unless CVIZ_REAL_RUN=1 is set:
  * random: seeded with CVIZ_SEED (default 0) at start, so random.random(), shuffle, choice ... give
    the same values on every run. PYTHONHASHSEED=0 (set by the driver) already fixes set order.
  * numpy: when numpy is imported, numpy.random.seed(CVIZ_SEED) runs right after it (an import hook),
    and so does the legacy global generator; np.random.default_rng() without a seed is not affected.
  * the wall clock: time.time(), time.time_ns(), datetime.datetime.now()/utcnow()/today() and
    datetime.date.today() start at CVIZ_EPOCH (default 2026-01-05 09:00:00 UTC, a Monday) when the
    program starts and then advance at the real rate, so dates and times print the same and
    elapsed times stay real. time.monotonic() and time.perf_counter() are left alone (asyncio and
    timing examples depend on them); what they measure still varies a little from run to run, and
    code-viz's settle step keeps the committed trace when only such numbers differ (section 6).
"""
import os
import sys

if os.environ.get("CVIZ_REAL_RUN") != "1":
    import time as _time

    _seed = int(os.environ.get("CVIZ_SEED", "0"))
    _epoch = float(os.environ.get("CVIZ_EPOCH", "1767603600"))   # 2026-01-05 09:00:00 UTC
    _start_real, _start_mono = _time.time(), _time.monotonic()

    def _now():
        return _epoch + (_time.monotonic() - _start_mono)

    _time.time = _now
    _time.time_ns = lambda: int(_now() * 1e9)

    import random as _random
    _random.seed(_seed)

    import datetime as _dt

    class _DateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime.fromtimestamp(_now(), tz) if tz else _dt.datetime.fromtimestamp(_now())

        @classmethod
        def utcnow(cls):
            return _dt.datetime.fromtimestamp(_now(), _dt.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    class _Date(_dt.date):
        @classmethod
        def today(cls):
            return _dt.date.fromtimestamp(_now())

    _dt.datetime = _DateTime
    _dt.date = _Date

    class _SeedNumpy:
        """Import hook: seed numpy's legacy global generator right after numpy is imported."""
        def find_spec(self, name, path=None, target=None):
            if name != "numpy":
                return None
            sys.meta_path.remove(self)
            try:
                import importlib.util
                spec = importlib.util.find_spec(name)
            finally:
                sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return None
            loader = spec.loader
            orig = loader.exec_module

            def exec_module(module):
                orig(module)
                try:
                    module.random.seed(_seed)
                except Exception:
                    pass
                if self in sys.meta_path:
                    sys.meta_path.remove(self)
            loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _SeedNumpy())
