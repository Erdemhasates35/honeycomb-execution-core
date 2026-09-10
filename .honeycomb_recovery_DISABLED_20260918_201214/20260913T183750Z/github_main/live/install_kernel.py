#!/data/data/com.termux/files/usr/bin/python3
import base64, pathlib
here = pathlib.Path(__file__).resolve().parent
parts = sorted(here.glob("kernel.b64.*"))
if not parts:
    raise SystemExit("missing kernel.b64.*")
data = base64.b64decode("".join(p.read_text().strip() for p in parts))
target = here / "kernel.py"
target.write_bytes(data)
print("WROTE", target, len(data), "bytes; has LiveKernel =", b"class LiveKernel" in data)
