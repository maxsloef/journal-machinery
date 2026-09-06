#!/bin/bash
# Compiles all journal entries into /tmp/full_journal.txt so a review (or a
# chat.sh session, or a semantic-search subagent) can read the whole journal.
# Excludes CLAUDE.md.
#
# If a file reads as empty but has nonzero size (an evicted iCloud file, for
# example), a WARNING marker is written in its place instead of silently
# dropping the content, and the script exits 1 after finishing.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JOURNAL_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT="/tmp/full_journal.txt"
WARNINGS=0

rm -f "$OUTPUT"

for f in "$JOURNAL_DIR"/*.md; do
    name="$(basename "$f")"
    [ "$name" = "CLAUDE.md" ] && continue
    echo "=== $name ===" >> "$OUTPUT"
    if content="$(cat "$f" 2>/dev/null)"; then
        if [ -z "$content" ] && [ -s "$f" ]; then
            echo "[WARNING: $name read as empty but has nonzero size on disk. Content is MISSING from this compilation, probably an evicted cloud-synced file. Do not conclude this entry is empty.]" >> "$OUTPUT"
            WARNINGS=$((WARNINGS + 1))
        else
            printf '%s\n' "$content" >> "$OUTPUT"
        fi
    else
        echo "[WARNING: $name could not be read. Content is MISSING from this compilation.]" >> "$OUTPUT"
        WARNINGS=$((WARNINGS + 1))
    fi
    echo >> "$OUTPUT"
done

LINES=$(wc -l < "$OUTPUT" | tr -d " ")
echo "Compiled journal to $OUTPUT ($LINES lines)"
if [ "$WARNINGS" -gt 0 ]; then
    echo "WARNING: $WARNINGS file(s) could not be read; see markers in $OUTPUT" >&2
    exit 1
fi
