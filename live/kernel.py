#!/data/data/com.termux/files/usr/bin/python3
# Auto-materialize full kernel from base64 parts if needed
import base64, pathlib, sys
_here = pathlib.Path(__file__).resolve().parent
_parts = sorted(_here.glob("kernel.b64.*"))
if _parts:
    _data = base64.b64decode("".join(p.read_text().strip() for p in _parts))
    _impl = _here / "_kernel_impl.py"
    if not _impl.exists() or _impl.stat().st_size != len(_data):
        _impl.write_bytes(_data)
    import importlib.util
    _spec = importlib.util.spec_from_file_location("live._kernel_impl", _impl)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    LiveKernel = _mod.LiveKernel
    load_env = _mod.load_env
    ema = _mod.ema
    rsi = _mod.rsi
    atr = _mod.atr
    TokenBucket = getattr(_mod, "TokenBucket", None)
    SingleFlight = getattr(_mod, "SingleFlight", None)
else:
    raise ImportError("live/kernel.b64.* missing — run: python3 live/build_kernel.py")
