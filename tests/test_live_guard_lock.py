import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import honeycomb_execution_guard as guard


class TestLiveGuardLock(unittest.TestCase):
    def test_python_and_node_use_the_same_exclusive_lock(self):
        lock_path = guard.LOCK_PATH
        script = (
            "const fs=require('node:fs');"
            "try{const fd=fs.openSync(process.argv[1],'wx',0o600);"
            "fs.closeSync(fd);process.exit(0)}"
            "catch(error){process.exit(error.code==='EEXIST'?23:1)}"
        )
        with guard._FileGuard():
            result = subprocess.run(
                ["node", "-e", script, lock_path],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse(Path(lock_path).exists())

    def test_stale_lock_is_recovered(self):
        lock = Path(guard.LOCK_PATH)
        lock.write_text("dead-process\n", encoding="ascii")
        stale_time = time.time() - guard.LOCK_STALE_SECONDS - 5
        os.utime(lock, (stale_time, stale_time))

        with guard._FileGuard():
            self.assertTrue(lock.exists())

        self.assertFalse(lock.exists())

    def test_process_environment_overrides_dotenv_values(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "BINANCE_SAFE_WEIGHT_PER_MIN=100\nBINANCE_SAFE_ORDERS_PER_10S=10\n",
                encoding="utf-8",
            )
            with patch.object(guard, "ROOT", directory):
                with patch.dict(os.environ, {"BINANCE_SAFE_WEIGHT_PER_MIN": "200"}, clear=True):
                    loaded = guard._load_env_file()

        self.assertEqual(loaded["BINANCE_SAFE_WEIGHT_PER_MIN"], "200")
        self.assertEqual(loaded["BINANCE_SAFE_ORDERS_PER_10S"], "10")

    def test_non_finite_rate_limit_is_rejected(self):
        with patch.object(guard, "ENV", {"BINANCE_SAFE_WEIGHT_PER_MIN": "NaN"}):
            with self.assertRaisesRegex(RuntimeError, "finite positive number"):
                guard._positive_env_float("BINANCE_SAFE_WEIGHT_PER_MIN", 900)


if __name__ == "__main__":
    unittest.main()
