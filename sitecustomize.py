# Honeycomb additive runtime hook.
# Python's site module imports sitecustomize automatically when this repo is on sys.path.
# Nothing here replaces an engine; it only installs the shared Binance guard.
try:
    import honeycomb_execution_guard  # noqa: F401
except Exception as _exc:
    # Never hide a real engine import failure. The guard is best-effort at interpreter boot;
    # explicit Termux validation reports the exception separately.
    print("[HONEYCOMB-GUARD] boot warning: %s" % _exc, flush=True)
