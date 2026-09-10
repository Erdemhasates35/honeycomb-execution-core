#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/honeycomb-execution-core"
echo "===== GATE ====="
python3 -m py_compile live/kernel_hardened_sign.py agg_live_fix.py parliament_unlock.py || exit 1
python3 tests/test_kernel.py || exit 1
echo "GATE PASS"
