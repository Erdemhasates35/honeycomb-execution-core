#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
[ -f .env ] || { echo "NO_ENV"; exit 1; }
backup=".env.backup.$(date +%Y%m%d-%H%M%S)"
cp .env "$backup"
tmp=".env.normalized.$$"
awk '
  /^[[:space:]]*#/ {print; next}
  /^[[:space:]]*$/ {print; next}
  /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=/ {
    sub(/^[[:space:]]*/, "")
    print
    next
  }
' .env > "$tmp"
mv "$tmp" .env
chmod 600 .env
printf 'ENV_NORMALIZED backup=%s\n' "$backup"
awk '/^[A-Za-z_][A-Za-z0-9_]*=/{print NR ":" $1}' .env
