#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ ! -f .env ]; then
    echo "ENV=NOT_FOUND"
    exit 0
fi

cp .env \
".env.backup.$(date +%Y%m%d-%H%M%S)"

python - <<'PY'
from pathlib import Path
import re

path = Path(".env")
output = []
invalid = []

for number, line in enumerate(
    path.read_text(
        errors="replace"
    ).splitlines(),
    1
):

    line = line.rstrip("\r")

    if (
        not line.strip()
        or line.lstrip().startswith("#")
    ):
        output.append(line)
        continue

    match = re.match(
        r'^([A-Za-z_][A-Za-z0-9_]*)=\s+(.*)$',
        line
    )

    if match:
        line = (
            f"{match.group(1)}="
            f"{match.group(2)}"
        )

    if not re.match(
        r'^[A-Za-z_][A-Za-z0-9_]*=',
        line
    ):
        invalid.append(
            (
                number,
                line[:100]
            )
        )

    output.append(line)

path.write_text(
    "\n".join(output) + "\n"
)

print("ENV_FORMAT=REPAIRED")

if invalid:
    print(
        "ENV_INVALID_LINES=",
        invalid
    )
    raise SystemExit(31)
PY

echo "ENV_BACKUP_CREATED=YES"
