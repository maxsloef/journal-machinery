#!/usr/bin/env python3
"""
Journal review agent using the Claude Agent SDK.
Provides async feedback on journal entries.

Modes:
  mention    reply to an @claude mention (invoked by watcher.py)
  debounced  review recent edits after a quiet period (watcher.py, if AUTO_REVIEWS_ENABLED)
  overnight  comprehensive review of the latest entry (launchd, if AUTO_REVIEWS_ENABLED)

Exit codes: 0 = Claude edited the journal, 2 = Claude chose not to respond.
"""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

from config import AUTO_REVIEWS_ENABLED, JOURNAL_AUTHOR, MODEL

JOURNAL_DIR = Path(__file__).resolve().parent.parent
REQUESTED_MODEL_BASE = MODEL.split("[")[0]  # "fable[1m]" -> "fable"


def get_timestamp() -> str:
    """Current timestamp with local timezone, e.g. 2026-09-06 10:30 PDT."""
    now = datetime.now()
    tz_name = time.tzname[time.localtime().tm_isdst]
    return now.strftime(f"%Y-%m-%d %H:%M {tz_name}")


def log(msg: str):
    print(f"[{datetime.now().isoformat()}] {msg}")


def load_full_journal() -> str:
    """Compile and load the full journal content. A nonzero exit from the
    compile script means some files were unreadable; the output still contains
    WARNING markers in their place, so we proceed but say so."""
    compile_script = Path(__file__).parent / "compile_journal.sh"
    result = subprocess.run([str(compile_script)], capture_output=True, text=True)
    if result.returncode != 0:
        log(f"compile_journal.sh warnings: {result.stderr.strip()}")
    return Path("/tmp/full_journal.txt").read_text()


def find_claude_cli() -> str | None:
    """Locate the claude CLI. The SDK needs an explicit path under launchd,
    where PATH is minimal."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")):
        if candidate.exists():
            return str(candidate)
    return None


def has_git_remote() -> bool:
    result = subprocess.run(["git", "-C", str(JOURNAL_DIR), "remote"], capture_output=True, text=True)
    return bool(result.stdout.strip())


def commit_changes():
    """Commit (and push, if there is a remote) all changes after a review.
    Failures are logged, not raised: a review that landed in the file is a
    success even if git is unhappy."""
    git = ["git", "-C", str(JOURNAL_DIR)]
    try:
        subprocess.run(git + ["add", "-A"], capture_output=True, check=True, text=True)
        subprocess.run(git + ["commit", "-m", "claude review"], capture_output=True, check=True, text=True)
        log("Committed review changes")
    except subprocess.CalledProcessError as e:
        log(f"git commit failed: {(e.stderr or e.stdout or '').strip()}")
        return
    if has_git_remote():
        try:
            subprocess.run(git + ["push"], capture_output=True, check=True, text=True)
            log("Pushed review changes")
        except subprocess.CalledProcessError as e:
            log(f"git push failed: {(e.stderr or '').strip()}")


def detect_fallback(models_seen: set[str]) -> str | None:
    """Given the set of models that actually served turns, return the name of
    the fallback model if the requested model was NOT used, else None.

    We request e.g. `fable[1m]`; the served model string looks like
    `claude-fable-5-1` or, on classifier fallback, `claude-opus-…`. Anything
    without the requested base name means Fable's input classifier tripped
    and the request fell back to another model."""
    non_requested = sorted(m for m in models_seen if REQUESTED_MODEL_BASE not in m)
    return non_requested[0] if non_requested else None


def snapshot_md_files() -> dict[Path, str]:
    """Hash every top-level .md file in the journal. Used to detect which files
    the agent edited, regardless of which tool it used to edit them (Edit,
    Write, or a shell command) and regardless of git tracking state."""
    snapshot = {}
    for path in JOURNAL_DIR.glob("*.md"):
        try:
            snapshot[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue  # evicted cloud file etc.; treat as unreadable both times
    return snapshot


def changed_files(before: dict[Path, str], after: dict[Path, str]) -> list[Path]:
    return sorted(p for p, h in after.items() if before.get(p) != h)


def annotate_fallback(file_path: Path, fallback_model: str):
    """Append a footnote inside the last `Claude` comment block in the file,
    noting that Fable's classifier tripped and the reply was served by a
    fallback model."""
    try:
        lines = file_path.read_text().split("\n")
    except OSError:
        return

    header_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^>+\s*\[!comment\]\s*Claude\b", line):
            header_idx = i
    if header_idx is None:
        return

    end_idx = header_idx
    for j in range(header_idx, len(lines)):
        if lines[j].startswith(">"):
            end_idx = j
        else:
            break

    prefix = re.match(r"^(>+)", lines[header_idx]).group(1)
    footnote = f"{prefix} ⚠️ *Served by `{fallback_model}` — Fable input classifier tripped on this content; fell back.*"
    lines[end_idx + 1:end_idx + 1] = [prefix, footnote]
    file_path.write_text("\n".join(lines))


def format_diff_context(diff: str | None) -> str:
    if not diff:
        return ""
    return f"""
## Changes Since Last Review

```diff
{diff}
```

Focus your comments on these recent changes.
"""


async def run_review(mode: str, file: str = None, context: str = None, diff: str = None, instructions: str = None):
    """Run a journal review with the specified mode."""

    timestamp = get_timestamp()
    diff_context = format_diff_context(diff)

    log("Loading full journal...")
    full_journal = load_full_journal()
    log(f"Loaded {len(full_journal)} chars")

    journal_context = f"""## Full Journal

{full_journal}

---

"""

    base_instructions = f"""It is currently {timestamp}. You are reviewing {JOURNAL_AUTHOR}'s journal entries. The full journal is provided above for context.

Do not respond if you have nothing valuable to add — trivial changes, nothing meaningful to say, or you've already commented on the relevant content.
Use the Edit tool to respond in the file.

There is a lot of context here — it can be easy to get lost in the volume. When commenting, make sure you are being accurate to what {JOURNAL_AUTHOR} actually wrote, not hallucinating or reconstructing details. Think carefully about the context and history, and focus on the specifics rather than getting overwhelmed by the volume. Prior Claude comments in the journal may also contain errors, so don't treat them as ground truth.
"""

    if mode == "debounced":
        prompt = f"""{journal_context}{base_instructions}
{diff_context}
Review the journal entry named {file}.
Add up to a few thoughtful, genuine inline comments."""

    elif mode == "overnight":
        prompt = f"""{journal_context}{base_instructions}
{diff_context}
Perform a comprehensive overnight review of the most recent journal entry.
Add thoughtful, genuine, expansive comments."""

    elif mode == "mention":
        prompt = f"""{journal_context}{base_instructions}
{diff_context}
Respond to an @claude mention in the journal entry named {file}.

The comment with the mention (and any thread context):
{context}
"""

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        return

    if instructions:
        prompt += f"\n\nAdditional instructions:\n{instructions}"

    stderr_lines = []

    def capture_stderr(line: str):
        stderr_lines.append(line)
        print(f"[stderr] {line}", file=sys.stderr)

    cli_path = find_claude_cli()
    if cli_path is None:
        print("Could not find the `claude` CLI on PATH or in ~/.local/bin", file=sys.stderr)
        sys.exit(1)

    options = ClaudeAgentOptions(
        model=MODEL,
        permission_mode="auto",
        cwd=str(JOURNAL_DIR),
        stderr=capture_stderr,
        effort="max",
        cli_path=cli_path,
    )

    log(f"Starting {mode} review")
    if file:
        print(f"  File: {file}")
    if diff:
        print(f"  Diff: {len(diff)} chars")

    before = snapshot_md_files()
    edit_tool_seen = False
    models_seen: set[str] = set()
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                if message.model:
                    models_seen.add(message.model)
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"  Claude: {block.text[:200]}...")
                    elif isinstance(block, ToolUseBlock):
                        print(f"  Tool: {block.name}")
                        if block.name in ("Edit", "Write", "MultiEdit"):
                            edit_tool_seen = True

    except Exception as e:
        print(f"Error during review: {e}", file=sys.stderr)
        if stderr_lines:
            print(f"Captured stderr ({len(stderr_lines)} lines):", file=sys.stderr)
            for line in stderr_lines:
                print(f"  {line}", file=sys.stderr)
        raise

    log(f"Model(s) used: {sorted(models_seen) or 'unknown'}")
    fallback_model = detect_fallback(models_seen)
    if fallback_model:
        log(f"⚠️ Classifier tripped — fell back to {fallback_model}")

    # "Did Claude respond?" is decided by whether any journal file actually
    # changed, not by which tool it used. Under permission_mode="auto" the
    # harness sometimes steers edits through Bash, which the old
    # Edit-tool-only check missed.
    edited = changed_files(before, snapshot_md_files())
    if not edited:
        if edit_tool_seen:
            log("Edit tool was called but no .md file changed")
        log("Review skipped - Claude did not edit the journal")
        sys.exit(2)

    log(f"Edited: {', '.join(p.name for p in edited)}")
    if fallback_model:
        for path in edited:
            annotate_fallback(path, fallback_model)
    commit_changes()
    log("Review complete")


def main():
    parser = argparse.ArgumentParser(description="Journal review agent")
    parser.add_argument("mode", choices=["debounced", "overnight", "mention"], help="Review mode")
    parser.add_argument("--file", "-f", help="Journal file to review")
    parser.add_argument("--context", "-c", help="Thread context for mention mode")
    parser.add_argument("--diff", "-d", help="Git diff to include in context")
    parser.add_argument("--instructions", "-i", help="Extra instructions to append to the prompt")

    args = parser.parse_args()

    if args.mode in ["debounced", "mention"] and not args.file:
        parser.error(f"{args.mode} mode requires --file")

    if args.mode == "mention" and not args.context:
        parser.error("mention mode requires --context")

    if args.mode == "overnight" and not AUTO_REVIEWS_ENABLED:
        log("Overnight review skipped: AUTO_REVIEWS_ENABLED is False")
        return

    asyncio.run(run_review(
        mode=args.mode,
        file=args.file,
        context=args.context,
        diff=args.diff,
        instructions=args.instructions,
    ))


if __name__ == "__main__":
    main()
