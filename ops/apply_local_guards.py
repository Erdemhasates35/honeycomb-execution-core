#!/usr/bin/env python3
"""Kirli yerel kernel ve helix dosyasina kapi ekler. Emir gondermez."""
import base64
import sys
from pathlib import Path

CLASS = base64.b64decode('Y2xhc3MgUGFydGlhbFByb2ZpdEVuZ2luZToKICAgICIiIgogICAgS2FkZW1lbGkga8Sxc21pIGvDonIgYWxtYTogcG96aXN5b24gVFAneWUgZG/En3J1IGlsZXJsZWRpa8OnZSBrYWxhbgogICAgbWlrdGFyxLFuIGJpciBrxLFzbcSxbsSxIEdFUsOHRUsgUMSwWUFTQSBFTVLEsFlMRSBrYXBhdMSxcCBrw6JyxLEgcmVhbGl6ZQogICAgZWRlciwgZ2VyaSBrYWxhbsSxIFRQL1NMIGtvcnVtYXPEsXlsYSDDp2FsxLHFn21heWEgZGV2YW0gZWRlci4gTWV2Y3V0CiAgICBrZXJuZWwuY2xvc2VfbWFya2V0KCkvcGxhY2VfcHJvdGVjdCgpIG1ldG9kbGFyxLEga3VsbGFuxLFsxLFyIChoacOnYmlyCiAgICBlbWlyL2ltemEgbWFudMSxxJ/EsSBidXJhZGEgVEVLUkFSIFlBWklMTUFESSkuCgogICAgw5ZORU1MxLA6IGtlcm5lbC5jbG9zZV9tYXJrZXQoKSBrZW5kaSBpw6dpbmRlIGNhbmNlbF9hbGwoKSDDp2HEn8SxcsSxeW9yLAogICAgYnUgZGEga2FsYW4gcG96aXN5b251biBUUC9TTCBrb3J1bWFzxLFuxLEgZGEgc2lsaXlvciDigJQgYnUgecO8emRlbiBoZXIKICAgIGvEsXNtaSBrYXBhdG1hZGFuIHNvbnJhIHBsYWNlX3Byb3RlY3QoKSBpbGUga29ydW1hIGthbGFuIG1pa3RhciBpw6dpbgogICAgWUVOxLBERU4ga3VydWx1eW9yIChjbG9zZVBvc2l0aW9uPXRydWUgdGlwaSBlbWlybGVyIHphdGVuIG1pa3RhcgogICAgYmVsaXJ0bWV6LCBrYWxhbiBuZSBrYWRhcnNhIG9udSBrYXBhdMSxcikuCgogICAgVmFyc2F5xLFsYW46IFRQIG1lc2FmZXNpbmluICU1MCdzaW5kZSBrYWxhbsSxbiAlMzUnaSwgJTgwJ2luZGUgeWluZQogICAga2FsYW7EsW4gJTM1J2kgcmVhbGl6ZSBlZGlsaXIg4oCUIHBvemlzeW9udW4gdGFtYW3EsSB0ZWsgYmlyIFRQCiAgICBzZXZpeWVzaW5lIGJhxJ9sxLEga2FsbWF6LCAiYXoga8OicmRhIGVya2VuIGthcGF0LCBwb3RhbnNpeWVsaSB0YW1hbWVuCiAgICBrYcOnxLFybWEiIGRlbmdlc2luaSBrdXJhci4KICAgICIiIgogICAgREVGQVVMVF9TVEFHRVMgPSBbKDAuNTAsIDAuMzUpLCAoMC44MCwgMC4zNSldICAjIChpbGVybGVtZSwga2FsYW7EsW4ga2FwYXTEsWxhY2FrIHnDvHpkZXNpKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBrZXJuZWwsIHN0YWdlcz1Ob25lLCBsb2dfZm49Tm9uZSk6CiAgICAgICAgc2VsZi5rZXJuZWwgPSBrZXJuZWwKICAgICAgICBzZWxmLnN0YWdlcyA9IHN0YWdlcyBvciBzZWxmLkRFRkFVTFRfU1RBR0VTCiAgICAgICAgc2VsZi5sb2cgPSBsb2dfZm4gb3IgKGxhbWJkYSBtOiBOb25lKQogICAgICAgIHNlbGYuX3BvczogRGljdFtzdHIsIERpY3Rbc3RyLCBBbnldXSA9IHt9CiAgICAgICAgc2VsZi5fbG9jayA9IHRocmVhZGluZy5Mb2NrKCkKCiAgICBkZWYgcmVnaXN0ZXIoc2VsZiwgc3ltYm9sLCBzaWRlLCBlbnRyeSwgdHAsIHNsLCBxdHksIHBvc19zaWRlPU5vbmUpOgogICAgICAgIHdpdGggc2VsZi5fbG9jazoKICAgICAgICAgICAgc2VsZi5fcG9zW3N5bWJvbF0gPSB7CiAgICAgICAgICAgICAgICAic2lkZSI6IHNpZGUsICJlbnRyeSI6IGVudHJ5LCAidHAiOiB0cCwgInNsIjogc2wsCiAgICAgICAgICAgICAgICAicXR5X3JlbWFpbmluZyI6IHF0eSwgInN0YWdlIjogMCwgInBvc19zaWRlIjogcG9zX3NpZGUsCiAgICAgICAgICAgICAgICAicmVhbGl6ZWRfbmV0IjogMC4wLAogICAgICAgICAgICB9CgogICAgZGVmIGZvcmdldChzZWxmLCBzeW1ib2wpOgogICAgICAgIHdpdGggc2VsZi5fbG9jazoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3Bvcy5wb3Aoc3ltYm9sLCBOb25lKQoKICAgIGRlZiBnZXQoc2VsZiwgc3ltYm9sKSAtPiBPcHRpb25hbFtEaWN0W3N0ciwgQW55XV06CiAgICAgICAgd2l0aCBzZWxmLl9sb2NrOgogICAgICAgICAgICByZXR1cm4gZGljdChzZWxmLl9wb3Nbc3ltYm9sXSkgaWYgc3ltYm9sIGluIHNlbGYuX3BvcyBlbHNlIE5vbmUKCiAgICBkZWYgdXBkYXRlKHNlbGYsIHN5bWJvbCwgY3VycmVudF9wcmljZSkgLT4gT3B0aW9uYWxbRGljdFtzdHIsIEFueV1dOgogICAgICAgIHdpdGggc2VsZi5fbG9jazoKICAgICAgICAgICAgcG9zID0gc2VsZi5fcG9zLmdldChzeW1ib2wpCiAgICAgICAgaWYgbm90IHBvcyBvciBwb3NbInF0eV9yZW1haW5pbmciXSA8PSAwIG9yIHBvc1sic3RhZ2UiXSA+PSBsZW4oc2VsZi5zdGFnZXMpOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGVudHJ5LCBzaWRlLCB0cCA9IHBvc1siZW50cnkiXSwgcG9zWyJzaWRlIl0sIHBvc1sidHAiXQogICAgICAgIGRpc3QgPSBhYnModHAgLSBlbnRyeSkKICAgICAgICBpZiBkaXN0IDw9IDA6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgcHJvZ3Jlc3MgPSAoY3VycmVudF9wcmljZSAtIGVudHJ5KSAvIGRpc3QgaWYgc2lkZSA9PSAiTE9ORyIgZWxzZSAoZW50cnkgLSBjdXJyZW50X3ByaWNlKSAvIGRpc3QKICAgICAgICB0aHJlc2gsIGNsb3NlX2ZyYWMgPSBzZWxmLnN0YWdlc1twb3NbInN0YWdlIl1dCiAgICAgICAgaWYgcHJvZ3Jlc3MgPCB0aHJlc2g6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGNsb3NlX3F0eSA9IHBvc1sicXR5X3JlbWFpbmluZyJdICogY2xvc2VfZnJhYwogICAgICAgIHRyeToKICAgICAgICAgICAgZmlsbCA9IHNlbGYua2VybmVsLmNsb3NlX21hcmtldChzeW1ib2wsIHNpZGUsIGNsb3NlX3F0eSwgcG9zLmdldCgicG9zX3NpZGUiKSkKICAgICAgICAgICAgbmV0ID0gZmxvYXQoZmlsbC5nZXQoInJwIiwgMC4wKSkgLSBmbG9hdChmaWxsLmdldCgiY29tbWlzc2lvbiIsIDAuMCkpCiAgICAgICAgICAgIHdpdGggc2VsZi5fbG9jazoKICAgICAgICAgICAgICAgIGlmIHN5bWJvbCBub3QgaW4gc2VsZi5fcG9zOgogICAgICAgICAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgICAgICAgICBzZWxmLl9wb3Nbc3ltYm9sXVsicXR5X3JlbWFpbmluZyJdID0gbWF4KDAuMCwgc2VsZi5fcG9zW3N5bWJvbF1bInF0eV9yZW1haW5pbmciXSAtIGZpbGxbInF0eSJdKQogICAgICAgICAgICAgICAgc2VsZi5fcG9zW3N5bWJvbF1bInN0YWdlIl0gKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fcG9zW3N5bWJvbF1bInJlYWxpemVkX25ldCJdICs9IG5ldAogICAgICAgICAgICAgICAgcmVtYWluaW5nID0gc2VsZi5fcG9zW3N5bWJvbF1bInF0eV9yZW1haW5pbmciXQogICAgICAgICAgICAgICAgc3RhZ2VfZG9uZSA9IHNlbGYuX3Bvc1tzeW1ib2xdWyJzdGFnZSJdCiAgICAgICAgICAgIGlmIHJlbWFpbmluZyA+IDA6CiAgICAgICAgICAgICAgICBzZWxmLmtlcm5lbC5wbGFjZV9wcm90ZWN0KHN5bWJvbCwgc2lkZSwgZW50cnksIHRwLCBwb3NbInNsIl0sIHBvcy5nZXQoInBvc19zaWRlIikpCiAgICAgICAgICAgIHNlbGYubG9nKAogICAgICAgICAgICAgICAgZiJLSVNNSSBLQVIgQUwge3NpZGV9IHtzeW1ib2x9IHwgaWxlcmxlbWU9e3Byb2dyZXNzKjEwMDouMGZ9JSB8IGthcGF0xLFsYW49e2ZpbGxbJ3F0eSddOi42Z30gIgogICAgICAgICAgICAgICAgZiIoa2FkZW1lIHtzdGFnZV9kb25lfS97bGVuKHNlbGYuc3RhZ2VzKX0pIHwgbmV0PXtuZXQ6Ky40Zn0gfCBrYWxhbj17cmVtYWluaW5nOi42Z30iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIHsicXR5X2Nsb3NlZCI6IGZpbGxbInF0eSJdLCAibmV0IjogbmV0LCAicmVtYWluaW5nIjogcmVtYWluaW5nLCAic3RhZ2UiOiBzdGFnZV9kb25lfQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5sb2coZiJLSVNNSSBLQVIgQUwgSEFUQSB7c3ltYm9sfToge2V9IikKICAgICAgICAgICAgcmV0dXJuIE5vbmUK').decode()
ROOTS = [
    Path.home() / "honeycomb-execution-core",
    Path.home() / "honeycomb" / "honeycomb-execution-core",
]
QTY_OLD = (
    "        if q < f[\"minQty\"]:\n"
    "            raise RuntimeError(\"qty below min %s < %s\" % (q, f[\"minQty\"]))"
)
QTY_NEW = (
    "        if q <= 0:\n"
    "            raise RuntimeError(\"bakiye veya miktar 0 — emir yok\")\n"
    + QTY_OLD
)
SW_OLD = (
    "            return kernel_obj.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)\n"
    "        except Exception:\n"
    "            pass"
)
SW_NEW = (
    "            return kernel_obj.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)\n"
    "        except RuntimeError:\n"
    "            raise\n"
    "        except Exception:\n"
    "            pass"
)

def patch(path, old, new, label):
    if not path.exists():
        return
    text = path.read_text(errors="replace")
    if old not in text:
        print("atla", label, path)
        return
    path.write_text(text.replace(old, new, 1))
    print("yama", label, path)

def main():
    seen = False
    for root in ROOTS:
        kernel = root / "live" / "kernel.py"
        if not kernel.exists():
            print("yok", root)
            continue
        seen = True
        text = kernel.read_text(errors="replace")
        if "class PartialProfitEngine" not in text:
            if not text.endswith("\n"):
                text += "\n"
            kernel.write_text(text + "\n" + CLASS)
            print("sinif", kernel)
        else:
            print("sinif var", kernel)
        patch(kernel, QTY_OLD, QTY_NEW, "miktar")
        patch(root / "helix_sovereign_pro.py", SW_OLD, SW_NEW, "yutma")
        sys.path.insert(0, str(root))
        for name in list(sys.modules):
            if name == "live" or name.startswith("live."):
                del sys.modules[name]
        try:
            from live.kernel import PartialProfitEngine, LiveKernel
            print("import OK", root, PartialProfitEngine.__name__)
        except Exception as exc:
            print("import FAIL", root, type(exc).__name__, exc)
        finally:
            if sys.path and sys.path[0] == str(root):
                sys.path.pop(0)
    if not seen:
        raise SystemExit("klon yok")

if __name__ == "__main__":
    main()
