#!/data/data/com.termux/files/usr/bin/python3
import base64, pathlib
here = pathlib.Path(__file__).resolve().parent
parts = sorted(here.glob("kernel.b64.*"))
data = base64.b64decode("".join(p.read_text().strip() for p in parts))
(here / "_kernel_impl.py").write_bytes(data)
print("wrote _kernel_impl.py", len(data), "bytes")
