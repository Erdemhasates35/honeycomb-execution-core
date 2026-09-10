#!/data/data/com.termux/files/usr/bin/python3
from pathlib import Path
here = Path(__file__).resolve().parent
parts = sorted(here.glob("kernel.part*"))
text = "".join(p.read_text() for p in parts)
(here / "kernel.py").write_text(text)
print("assembled kernel.py", len(text))
