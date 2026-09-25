"""Minimal stand-in for the pieces of pytest these pure-engine tests use,
so they can run with plain `python3` when pytest itself isn't installed
(no network access in this environment to pip install it). Implements
exactly: raises(), fixture()/autouse (accepted but not auto-invoked —
harmless for tests that don't depend on the one autouse fixture in
conftest.py, which only matters for FastAPI-route tests), and mark.asyncio
(a marker the runner script below detects to know which tests to
asyncio.run()). NOT a general pytest replacement.
"""
import contextlib


class _RaisesContext:
    def __init__(self, expected):
        self.expected = expected
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected {self.expected} to be raised, but nothing was raised")
        if self.expected is not None and not issubclass(exc_type, self.expected):
            return False  # re-raise: wrong exception type
        self.value = exc_val
        return True  # suppress: expected exception


def raises(expected_exception=Exception):
    return _RaisesContext(expected_exception)


def fixture(*args, **kwargs):
    def decorator(fn):
        fn._is_fixture = True
        fn._fixture_kwargs = kwargs
        return fn
    if args and callable(args[0]):
        return decorator(args[0])
    return decorator


class _Mark:
    def __getattr__(self, name):
        def marker(fn=None, *a, **kw):
            if fn is None:
                return lambda f: marker(f)
            setattr(fn, f"_mark_{name}", True)
            return fn
        return marker


mark = _Mark()


class _Skip(Exception):
    pass


def skip(reason=""):
    raise _Skip(reason)


class _Approx:
    def __init__(self, expected, abs=None, rel=None):
        self.expected = expected
        self.abs = abs if abs is not None else 1e-6
        self.rel = rel

    def __eq__(self, actual):
        try:
            tol = self.abs
            if self.rel is not None:
                tol = max(tol, self.rel * abs(self.expected))
            return abs(actual - self.expected) <= tol
        except TypeError:
            return NotImplemented

    def __repr__(self):
        return f"approx({self.expected!r} +/- {self.abs!r})"


def approx(expected, rel=None, abs=None):
    return _Approx(expected, abs=abs, rel=rel)
