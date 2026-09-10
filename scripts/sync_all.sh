#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

touch .gitignore

for item in \
    ".env" \
    ".env.*" \
    "*.db" \
    "*.sqlite" \
    "*.sqlite3" \
    "logs/" \
    "runtime/" \
    "__pycache__/" \
    "node_modules/"
do

    grep -qxF \
        "$item" \
        .gitignore 2>/dev/null \
        || echo "$item" >> .gitignore

done

sort -u \
    .gitignore \
    -o .gitignore

git status --short

git add . \
    ':!.env' \
    ':!.env.*' \
    ':!*.db' \
    ':!*.sqlite' \
    ':!*.sqlite3' \
    ':!logs/' \
    ':!runtime/' \
    ':!__pycache__/' \
    ':!node_modules/'

git diff --cached --check

if git diff --cached --quiet; then

    echo \
    "COMMIT=NOTHING_TO_COMMIT"

else

    git commit \
        -m "chore: synchronize honeycomb control plane and engine inventory"

fi

if git remote get-url origin >/dev/null 2>&1; then

    branch="$(
        git branch --show-current
    )"

    git push \
        origin \
        "$branch"

    echo \
    "GITHUB_SYNC=PASS"

else

    echo \
    "GITHUB_SYNC=NO_ORIGIN"

fi
