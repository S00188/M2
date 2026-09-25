"""Runner for the pure-engine test files using the pytest shim in
pytest_shim/ (for when pytest/fastapi/sqlalchemy aren't installed and
there's no network access to install them — exactly the environment this
was written in). Imports each test module, calls every top-level test_*
function (asyncio.run for coroutine functions), and prints a pytest-style
summary line.

This does NOT replace the real test suite — the moment pytest and this
project's actual dependencies (fastapi, sqlalchemy, aiosqlite, ...) are
installed, just run `pytest -q` from backend/ as normal and ignore this
entirely. This only covers the test files under app/game_engine/ that
have zero third-party dependencies; anything touching the API, database,
Telegram bot, or WebSocket layer needs the real suite.

Usage: `python3 tools/run_pure_engine_tests_offline.py` from backend/.
"""
import sys, os, asyncio, traceback, importlib

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pytest_shim"))

MODULES = [
    "tests.test_voting",
    "tests.test_discussion_chat_and_stats",
    "tests.test_mafia_chat",
    "tests.test_compositions_and_roles",
    "tests.test_win_conditions",
    "tests.test_night_resolution",
    "tests.test_phase_automation",
    "tests.test_anticheat_and_views",
    "tests.test_admin_controls",
    "tests.test_second_audit_fixes",
]

passed, failed, errors = [], [], []

for modname in MODULES:
    try:
        mod = importlib.import_module(modname)
    except Exception as e:
        errors.append((modname, "<import>", e, traceback.format_exc()))
        continue
    for name in dir(mod):
        if not name.startswith("test_"):
            continue
        fn = getattr(mod, name)
        if not callable(fn):
            continue
        full = f"{modname}.{name}"
        try:
            if asyncio.iscoroutinefunction(fn):
                asyncio.run(fn())
            else:
                fn()
            passed.append(full)
        except AssertionError as e:
            failed.append((full, e, traceback.format_exc()))
        except Exception as e:
            errors.append((full, "<call>", e, traceback.format_exc()))

print(f"\n=== {len(passed)} passed, {len(failed)} failed, {len(errors)} errored (out of {len(passed)+len(failed)+len(errors)} collected) ===\n")
for full, e, tb in failed:
    print(f"FAILED {full}: {e}")
    print(tb)
for full, stage, e, tb in errors:
    print(f"ERROR {full} [{stage}]: {e}")
    print(tb)

sys.exit(0 if not failed and not errors else 1)
