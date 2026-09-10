#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$HOME/honeycomb-execution-core"
REPO="Erdemhasates35/quantum-nexus-os"
REMOTE="https://github.com/${REPO}.git"

cd "$ROOT"

STAMP="$(date '+%Y%m%d_%H%M%S')"
SYNC="$ROOT/runtime/sync"
MANIFEST="$SYNC/honeycomb-manifest-${STAMP}.txt"
REPORT="$SYNC/honeycomb-sync-${STAMP}.txt"

mkdir -p "$SYNC" "$ROOT/runtime" "$ROOT/logs"

echo "======================================================"
echo " QUANTUM NEXUS / HONEYCOMB FULL SOURCE SYNCHRONIZER"
echo "======================================================"
echo "ROOT   : $ROOT"
echo "REPO   : $REPO"
echo "STAMP  : $STAMP"
echo

# ------------------------------------------------------
# 0 — NEVER TOUCH / NEVER UPLOAD
# ------------------------------------------------------

cat > "$ROOT/.gitignore.honeycomb" <<'GITIGNORE'
.env
.env.*
!.env.example
*.secret
*.pem
*.key
*.crt
*.p12
*.pfx
credentials.json
service-account*.json
token*.json
secrets*
runtime/
logs/
*.log
*.db
*.sqlite
*.sqlite3
node_modules/
.venv/
venv/
__pycache__/
.pytest_cache/
.coverage
dist/
build/
.next/
.expo/
.DS_Store
GITIGNORE

if [ -f "$ROOT/.gitignore" ]; then
    cp "$ROOT/.gitignore" "$ROOT/.gitignore.backup.$STAMP"
    cat "$ROOT/.gitignore.honeycomb" >> "$ROOT/.gitignore"
else
    cp "$ROOT/.gitignore.honeycomb" "$ROOT/.gitignore"
fi

# Deduplicate .gitignore without destroying existing rules
awk 'NF && !seen[$0]++' "$ROOT/.gitignore" > "$SYNC/.gitignore.tmp"
mv "$SYNC/.gitignore.tmp" "$ROOT/.gitignore"

echo "[PASS] secret/runtime exclusion configured"

# ------------------------------------------------------
# 1 — BACKUP CURRENT GIT STATE
# ------------------------------------------------------

if [ -d "$ROOT/.git" ]; then
    git status --short > "$SYNC/pre-sync-status.txt" || true
    git diff > "$SYNC/pre-sync.diff" || true
    git diff --cached > "$SYNC/pre-sync-staged.diff" || true

    echo "[PASS] current Git state captured"
else
    echo "[INFO] Git repository not initialized"
    git init
fi

# ------------------------------------------------------
# 2 — REMOTE
# ------------------------------------------------------

if git remote get-url origin >/dev/null 2>&1; then
    CURRENT_REMOTE="$(git remote get-url origin)"
    echo "CURRENT_REMOTE=$CURRENT_REMOTE"
else
    git remote add origin "$REMOTE"
    echo "[PASS] origin added"
fi

# ------------------------------------------------------
# 3 — FULL SOURCE INVENTORY
# ------------------------------------------------------

echo
echo "=== DISCOVERING ALL ENGINES / ADAPTERS / STRATEGIES ==="

find "$ROOT" -type f \
    ! -path "$ROOT/.git/*" \
    ! -path "$ROOT/runtime/sync/*" \
    ! -path "$ROOT/runtime/*" \
    ! -path "$ROOT/logs/*" \
    ! -path "$ROOT/node_modules/*" \
    ! -path "$ROOT/.venv/*" \
    ! -path "$ROOT/venv/*" \
    ! -name '.env' \
    ! -name '.env.*' \
    ! -name '*.db' \
    ! -name '*.sqlite' \
    ! -name '*.sqlite3' \
    | sort > "$MANIFEST"

TOTAL="$(wc -l < "$MANIFEST" | tr -d ' ')"

echo "TOTAL_SOURCE_FILES=$TOTAL"

# ------------------------------------------------------
# 4 — ENGINE DISCOVERY
# ------------------------------------------------------

{
echo
echo "========== PYTHON =========="
find . -type f -name '*.py' \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    ! -path './logs/*' \
    ! -path './.venv/*' \
    ! -path './venv/*' \
    | sort

echo
echo "========== JAVASCRIPT/TYPESCRIPT =========="
find . -type f \( -name '*.js' -o -name '*.jsx' -o -name '*.ts' -o -name '*.tsx' \) \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    ! -path './logs/*' \
    ! -path './node_modules/*' \
    | sort

echo
echo "========== GO =========="
find . -type f -name '*.go' \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    | sort

echo
echo "========== RUST =========="
find . -type f \( -name '*.rs' -o -name 'Cargo.toml' \) \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    | sort

echo
echo "========== SHELL =========="
find . -type f \( -name '*.sh' -o -name '*.bash' \) \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    | sort

echo
echo "========== CONFIG =========="
find . -type f \
    \( -name '*.yaml' -o -name '*.yml' -o -name '*.json' -o -name '*.toml' \) \
    ! -path './.git/*' \
    ! -path './runtime/*' \
    ! -path './node_modules/*' \
    ! -name 'package-lock.json' \
    | sort

} > "$SYNC/technology-inventory.txt"

# ------------------------------------------------------
# 5 — NAME-BASED ENGINE DETECTION
# ------------------------------------------------------

grep -Ein \
    'engine|alpha|nexus|honeycomb|arbitrage|execution|bridge|adapter|strategy|signal|risk|brain|agent|parliament|orchestrator|market|binance|jupiter|flash|ws|websocket' \
    "$MANIFEST" \
    > "$SYNC/engine-candidates.txt" || true

# ------------------------------------------------------
# 6 — SOURCE CONTENT SIGNATURES
# ------------------------------------------------------

echo
echo "=== SHA256 SOURCE MANIFEST ==="

(
    cd "$ROOT"

    while IFS= read -r f; do
        [ -f "$f" ] || continue

        case "$f" in
            ./.env|./.env.*|./runtime/*|./logs/*|./*.db|./*.sqlite*)
                continue
                ;;
        esac

        sha256sum "$f"
    done < "$MANIFEST"
) > "$SYNC/source-sha256.txt"

echo "[PASS] SHA256 source manifest generated"

# ------------------------------------------------------
# 7 — ENV STRUCTURE — NAMES ONLY
# ------------------------------------------------------

if [ -f "$ROOT/.env" ]; then
    sed -E \
        's/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*).*/\1=<SET>/' \
        "$ROOT/.env" \
        | grep -E '^[A-Za-z_][A-Za-z0-9_]*=<SET>$' \
        | sort -u \
        > "$SYNC/env-variable-inventory.txt"
fi

echo "[PASS] ENV variable inventory generated without values"

# ------------------------------------------------------
# 8 — DEPENDENCY INVENTORY
# ------------------------------------------------------

{
    echo "=== Python ==="
    [ -f requirements.txt ] && cat requirements.txt || true
    [ -f pyproject.toml ] && grep -E \
        'dependencies|requires|fastapi|flask|requests|websocket|redis|psycopg|pydantic' \
        pyproject.toml || true

    echo
    echo "=== Node ==="
    [ -f package.json ] && cat package.json || true

    echo
    echo "=== Go ==="
    [ -f go.mod ] && cat go.mod || true
} > "$SYNC/dependency-inventory.txt"

# ------------------------------------------------------
# 9 — LOCAL SERVICE INVENTORY
# ------------------------------------------------------

{
    echo "=== PROCESSES ==="
    ps -ef 2>/dev/null | grep -E \
        'python|uvicorn|gunicorn|node|npm|go|engine|nexus|honeycomb' \
        | grep -v grep || true

    echo
    echo "=== PORTS ==="
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp 2>/dev/null || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null || true
    fi

    echo
    echo "=== REDIS ==="
    if command -v redis-cli >/dev/null 2>&1; then
        redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null || true
    fi
} > "$SYNC/runtime-inventory.txt"

# ------------------------------------------------------
# 10 — GIT FETCH
# ------------------------------------------------------

echo
echo "=== GIT REMOTE SYNC ==="

git fetch origin --prune || true

DEFAULT_BRANCH="$(git remote show origin 2>/dev/null \
    | sed -n 's/.*HEAD branch: //p' \
    | head -1)"

[ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH="main"

echo "DEFAULT_BRANCH=$DEFAULT_BRANCH"

# ------------------------------------------------------
# 11 — PRESERVE EXISTING LOCAL WORK
# ------------------------------------------------------

git status --short > "$SYNC/final-before-stage.txt" || true

# IMPORTANT:
# We DO NOT run git add -A.
# Deleted files are intentionally NOT staged.
# Existing files and new files are staged individually.

echo
echo "=== STAGING MODIFIED + NEW FILES ONLY ==="

MODIFIED="$(git diff --name-only 2>/dev/null || true)"
STAGED="$(git diff --cached --name-only 2>/dev/null || true)"
NEW="$(git ls-files --others --exclude-standard 2>/dev/null || true)"

{
    printf '%s\n' "$MODIFIED"
    printf '%s\n' "$NEW"
} | sed '/^$/d' | sort -u > "$SYNC/files-to-sync.txt"

while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "$f" ] || continue
    git add -- "$f"
done < "$SYNC/files-to-sync.txt"

# Keep already staged changes
# Never stage deletions
git diff --cached --name-status > "$SYNC/staged-files.txt"

echo "[PASS] local changes staged without staging deletions"

# ------------------------------------------------------
# 12 — COMMIT
# ------------------------------------------------------

if git diff --cached --quiet; then
    echo "[INFO] No new local changes to commit"
else
    git commit -m \
        "sync: import full Honeycomb execution stack from Termux" \
        || true
fi

# ------------------------------------------------------
# 13 — PUSH
# ------------------------------------------------------

CURRENT_BRANCH="$(git branch --show-current)"

if [ -z "$CURRENT_BRANCH" ]; then
    CURRENT_BRANCH="$DEFAULT_BRANCH"
    git checkout -B "$CURRENT_BRANCH"
fi

echo
echo "CURRENT_BRANCH=$CURRENT_BRANCH"

if git push -u origin "$CURRENT_BRANCH"; then
    echo "GITHUB_PUSH=PASS"
else
    echo
    echo "GITHUB_PUSH=AUTH_OR_REMOTE_REQUIRED"
    echo "SOURCE_FILES_REMAIN_LOCAL=TRUE"
fi

# ------------------------------------------------------
# 14 — FINAL STATE
# ------------------------------------------------------

{
    echo "========== FINAL SYNC REPORT =========="
    date
    echo
    echo "ROOT=$ROOT"
    echo "REPOSITORY=$REPO"
    echo "BRANCH=$CURRENT_BRANCH"
    echo "SOURCE_FILES=$TOTAL"
    echo
    echo "=== STATUS ==="
    git status --short || true
    echo
    echo "=== LAST COMMIT ==="
    git log -1 --oneline || true
    echo
    echo "=== ENGINE CANDIDATES ==="
    cat "$SYNC/engine-candidates.txt"
    echo
    echo "=== RUNTIME ==="
    cat "$SYNC/runtime-inventory.txt"
} > "$REPORT"

echo
echo "======================================================"
echo " FULL SOURCE INVENTORY + SYNC COMPLETE"
echo "======================================================"
echo "SOURCE FILES : $TOTAL"
echo "MANIFEST     : $MANIFEST"
echo "REPORT       : $REPORT"
echo "GITHUB       : $(git remote get-url origin 2>/dev/null || echo NONE)"
echo
echo "ENGINE CANDIDATES:"
cat "$SYNC/engine-candidates.txt"
echo
echo "FINAL GIT STATUS:"
git status --short || true
echo
echo "NOT UPLOADED:"
echo ".env / secrets / runtime / logs / databases"
echo "======================================================"
