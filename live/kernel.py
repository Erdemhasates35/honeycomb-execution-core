#!/data/data/com.termux/files/usr/bin/python3
"""Loader: assemble from kernel.part* then re-export."""
from pathlib import Path
import importlib.util
_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("kernel.part*"))
if _parts:
    _text = "".join(p.read_text() for p in _parts)
    _impl = _here / "_kernel_impl.py"
    if not _impl.exists() or _impl.read_text() != _text:
        _impl.write_text(_text)
    _spec = importlib.util.spec_from_file_location("live._kernel_impl", _impl)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    LiveKernel = _mod.LiveKernel
    load_env = _mod.load_env
    ema = _mod.ema
    rsi = _mod.rsi
    atr = _mod.atr
else:
    raise ImportError("missing live/kernel.part* — run: python3 live/assemble_kernel.py")
