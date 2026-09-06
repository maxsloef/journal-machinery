#!/bin/bash
# Start an interactive Claude Code session with the full journal preloaded.
# Uses a fork of the overnight-review prompt from review.py.
#
# Usage: chat.sh [opening message]
#   If given, the opening message is appended to the journal dump so it lands
#   in the first turn instead of becoming a separate second message.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/compile_journal.sh" >/dev/null || echo "warning: some journal files could not be read; see /tmp/full_journal.txt" >&2

AUTHOR="$(cd "$SCRIPT_DIR" && python3 -c 'import config; print(config.JOURNAL_AUTHOR)')"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M %Z")
OPENER="${1:-}"

PROMPT_FILE=$(mktemp /tmp/journal-chat-prompt.XXXXXX)
trap 'rm -f "$PROMPT_FILE"' EXIT

{
  echo "## Full Journal"
  echo
  cat /tmp/full_journal.txt
  echo
  echo "---"
  echo
  echo "It is currently $TIMESTAMP. You are reviewing $AUTHOR's journal entries. The full journal is provided above for context."
  echo
  echo "There is a lot of context here — it can be easy to get lost in the volume. When commenting, make sure you are being accurate to what $AUTHOR actually wrote, not hallucinating or reconstructing details. Think carefully about the context and history, and focus on the specifics rather than getting overwhelmed by the volume. Prior Claude comments in the journal may also contain errors, so don't treat them as ground truth."
  echo
  echo "You are now being connected to $AUTHOR, the user."
  if [ -n "$OPENER" ]; then
    echo
    echo "---"
    echo
    echo "$AUTHOR's opening message:"
    echo
    echo "$OPENER"
  fi
} > "$PROMPT_FILE"

cd "$(dirname "$SCRIPT_DIR")"
claude < "$PROMPT_FILE"
