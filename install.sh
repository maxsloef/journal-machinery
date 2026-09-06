#!/bin/bash
# Install the journal machinery into an Obsidian vault.
#
# Usage: ./install.sh /path/to/vault "FirstName"
#
# What it does (each step is idempotent and says what it did):
#   1. copies reviews/ into <vault>/reviews and sets JOURNAL_AUTHOR
#   2. writes <vault>/CLAUDE.md from the template (skips if one exists)
#   3. installs the Obsidian Comments plugin into <vault>/.obsidian
#   4. adds .gitignore entries and runs `git init` if the vault isn't a repo
#   5. creates the Python env with uv (~/.venvs/journal-reviews)
#   6. renders the two launchd plists into ~/Library/LaunchAgents
# It does NOT load the launchd agents. Run <vault>/reviews/reload.sh for that.

set -euo pipefail

VAULT="${1:-}"
AUTHOR="${2:-}"
if [ -z "$VAULT" ] || [ -z "$AUTHOR" ]; then
  echo "usage: $0 /path/to/vault \"FirstName\"" >&2
  exit 1
fi
if [ ! -d "$VAULT" ]; then
  echo "error: $VAULT is not a directory" >&2
  exit 1
fi
VAULT="$(cd "$VAULT" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"

for tool in uv git claude python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: '$tool' not found on PATH. See README.md → Prerequisites." >&2
    exit 1
  fi
done
UV="$(command -v uv)"

echo "==> 1. reviews/"
if [ -d "$VAULT/reviews" ]; then
  echo "    $VAULT/reviews already exists; leaving it alone. Delete it and re-run to reinstall."
else
  mkdir -p "$VAULT/reviews"
  cp "$HERE"/reviews/{review.py,watcher.py,config.py,compile_journal.sh,chat.sh,reload.sh,pyproject.toml,uv.lock,.python-version,.gitignore} "$VAULT/reviews/"
  chmod +x "$VAULT"/reviews/*.py "$VAULT"/reviews/*.sh
  sed -i '' "s/__AUTHOR__/$AUTHOR/" "$VAULT/reviews/config.py"
  echo "    installed; JOURNAL_AUTHOR = \"$AUTHOR\""
fi

echo "==> 2. CLAUDE.md"
if [ -f "$VAULT/CLAUDE.md" ]; then
  echo "    $VAULT/CLAUDE.md already exists; not overwriting."
  echo "    Merge templates/vault-CLAUDE.md into it by hand (replace __AUTHOR__ with $AUTHOR)."
else
  sed "s/__AUTHOR__/$AUTHOR/g" "$HERE/templates/vault-CLAUDE.md" > "$VAULT/CLAUDE.md"
  echo "    written"
fi

echo "==> 3. Obsidian Comments plugin"
mkdir -p "$VAULT/.obsidian/plugins/comments"
cp "$HERE"/obsidian/plugins/comments/{main.js,manifest.json,styles.css} "$VAULT/.obsidian/plugins/comments/"
CP="$VAULT/.obsidian/community-plugins.json"
python3 - "$CP" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
plugins = json.loads(p.read_text()) if p.exists() else []
if "comments" not in plugins:
    plugins.append("comments")
    p.write_text(json.dumps(plugins, indent=2) + "\n")
    print("    enabled in community-plugins.json")
else:
    print("    already enabled")
PY
echo "    (Obsidian: Settings → Community plugins must be turned on for it to load)"

echo "==> 4. git"
GI="$VAULT/.gitignore"
touch "$GI"
for line in ".DS_Store" ".venv" "reviews/__pycache__/" "reviews/*.log" "reviews/state.json" ".obsidian/workspace.json" ".obsidian/workspace-mobile.json"; do
  grep -qxF "$line" "$GI" || echo "$line" >> "$GI"
done
if git -C "$VAULT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "    vault is already a git repo"
else
  git -C "$VAULT" init -q
  echo "    ran git init (reviews commit as 'claude review'; add a private remote later if you want backups)"
fi

echo "==> 5. Python environment"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/journal-reviews"
(cd "$VAULT/reviews" && "$UV" sync -q)
echo "    $UV_PROJECT_ENVIRONMENT"

echo "==> 6. launchd plists"
mkdir -p "$HOME/Library/LaunchAgents"
for name in com.journal.watcher com.journal.overnight-review; do
  sed -e "s|__VAULT__|$VAULT|g" -e "s|__HOME__|$HOME|g" -e "s|__UV__|$UV|g" \
    "$HERE/templates/launchd/$name.plist" > "$HOME/Library/LaunchAgents/$name.plist"
  echo "    $HOME/Library/LaunchAgents/$name.plist"
done

cat <<MSG

Done. Next:
  1. Sanity check:   cd "$VAULT/reviews" && ./compile_journal.sh
  2. Start watcher:  "$VAULT/reviews/reload.sh"
  3. Watch logs:     tail -f /tmp/journal-watcher.log
  4. Test: put "@claude are you there?" in a journal entry, wait ~30s + a review.
MSG
