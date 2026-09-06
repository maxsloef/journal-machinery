#!/usr/bin/env python3
"""
File watcher for journal entries.
Triggers reviews based on file changes and @claude mention detection.

Runs forever under launchd (see templates/launchd/com.journal.watcher.plist).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from watchfiles import awatch, Change

from config import AUTO_REVIEWS_ENABLED

JOURNAL_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).parent / "state.json"
DEBOUNCE_SECONDS = 600         # 10 minutes for general edits
SHORT_DEBOUNCE_SECONDS = 30    # 30 seconds for @claude mentions
REVIEW_COOLDOWN_SECONDS = 10   # ignore changes for 10s after a review completes

# Files the watcher never treats as journal entries.
SKIP_FILES = {"CLAUDE.md"}

# Track last review completion time per file (to prevent self-triggering loops)
review_cooldowns: dict[str, datetime] = {}

# Patterns for detecting comments
COMMENT_PATTERN = re.compile(r'^(>+)\s*\[!comment\](?:\s*(\w+))?', re.MULTILINE)
MENTION_PATTERN = re.compile(r'@claude\b', re.IGNORECASE)
INLINE_CODE = re.compile(r'`[^`]*`')


def log(msg: str):
    print(f"[{datetime.now().isoformat()}] {msg}")


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"files": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def file_key(file_path: Path) -> str:
    """State is keyed by path relative to the journal, so a moved vault or a
    renamed home directory doesn't make every file look new."""
    try:
        return str(file_path.resolve().relative_to(JOURNAL_DIR.resolve()))
    except ValueError:
        return str(file_path)


def mention_signature(line: str) -> str:
    """Stable id for a mention line, so the same mention never fires twice
    even if the file is touched again before/without a reply."""
    return hashlib.sha256(line.strip().encode()).hexdigest()[:16]


# Git helper functions

def get_uncommitted_diff() -> str | None:
    """Diff of uncommitted changes to .md files."""
    try:
        result = subprocess.run(
            ["git", "-C", str(JOURNAL_DIR), "diff", "HEAD", "--", "*.md"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def find_unanswered_mentions(content: str) -> list[dict]:
    """
    Find @claude mentions in the file that don't have a Claude response.
    Returns list of {line_num, context, signature}.

    Skipped on purpose:
      - mentions inside inline code (`@claude`), e.g. docs describing the syntax
      - mentions inside Claude's own comment blocks (Claude quoting the tag)
    """
    lines = content.split('\n')
    unanswered = []

    # Author of the blockquote comment currently open at each nesting depth.
    authors_by_depth: dict[int, str | None] = {}

    for i, line in enumerate(lines):
        depth = len(re.match(r'^(>*)', line).group(1))
        if depth == 0:
            if line.strip():
                authors_by_depth.clear()
        else:
            header = COMMENT_PATTERN.match(line)
            if header:
                authors_by_depth[depth] = header.group(2)
                for d in [d for d in authors_by_depth if d > depth]:
                    del authors_by_depth[d]

        if not MENTION_PATTERN.search(INLINE_CODE.sub('', line)):
            continue

        # Whose block is this line in? Nearest open comment at depth <= this line's.
        current_author = None
        for d in sorted(authors_by_depth, reverse=True):
            if d <= depth:
                current_author = authors_by_depth[d]
                break
        if current_author == 'Claude':
            continue

        # Answered if the next comment header after this line is Claude's,
        # with only blank or blockquote lines in between.
        has_response = False
        for j in range(i + 1, len(lines)):
            next_line = lines[j]
            match = COMMENT_PATTERN.match(next_line)
            if match:
                has_response = match.group(2) == 'Claude'
                break
            elif next_line.strip() and not next_line.startswith('>'):
                break

        if not has_response:
            unanswered.append({
                'line_num': i,
                'context': line,
                'signature': mention_signature(line),
            })

    return unanswered


def analyze_file(file_path: Path, prev_state: dict) -> dict | None:
    """
    Analyze a file and determine what action to take.
    Returns {action, file, new_state, [context, signature]} or None.
    """
    if not file_path.exists() or file_path.suffix != '.md':
        return None
    if file_path.name.startswith('.') or file_path.name in SKIP_FILES:
        return None

    try:
        content = file_path.read_text()
    except OSError as e:
        # Evicted cloud-synced file, or a transient sync lock. No hash is
        # stored, so the file is re-analyzed on its next touch.
        log(f"Could not read {file_path.name}: {e}")
        return None

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    prev_file_state = prev_state.get('files', {}).get(file_key(file_path), {})

    if prev_file_state.get('contentHash') == content_hash:
        return None

    handled = set(prev_file_state.get('mentionsHandled', []))
    unanswered = [m for m in find_unanswered_mentions(content) if m['signature'] not in handled]

    if unanswered:
        latest = unanswered[-1]
        return {
            'action': 'mention',
            'file': str(file_path),
            'context': latest['context'],
            'signature': latest['signature'],
            'new_state': {
                'contentHash': content_hash,
                'mentionsHandled': sorted(handled | {latest['signature']}),
            },
        }

    return {
        'action': 'debounced',
        'file': str(file_path),
        'new_state': {'contentHash': content_hash},
    }


def run_review(mode: str, file: str = None, context: str = None, diff: str = None) -> bool:
    """Run review.py. Returns True if Claude responded."""
    cmd = [sys.executable, str(Path(__file__).parent / "review.py"), mode]
    if file:
        cmd.extend(["--file", file])
    if context:
        cmd.extend(["--context", context])
    if diff:
        cmd.extend(["--diff", diff])

    log(f"Running review ({mode})")
    result = subprocess.run(cmd)
    return result.returncode == 0  # 0 = responded, 2 = skipped


class DebounceTimer:
    """Per-file debounce timers."""

    def __init__(self, delay: float, name: str = "debounce"):
        self.delay = delay
        self.name = name
        self.timers: dict[str, asyncio.Task] = {}
        self.pending_data: dict[str, dict] = {}

    async def schedule(self, file_path: str, callback, data: dict = None):
        if file_path in self.timers:
            self.timers[file_path].cancel()
        if data:
            self.pending_data[file_path] = data

        async def delayed_callback():
            await asyncio.sleep(self.delay)
            del self.timers[file_path]
            extra_data = self.pending_data.pop(file_path, {})
            await callback(file_path, extra_data)

        self.timers[file_path] = asyncio.create_task(delayed_callback())
        log(f"{self.name} timer set for {Path(file_path).name} ({self.delay}s)")

    def cancel(self, file_path: str):
        if file_path in self.timers:
            self.timers[file_path].cancel()
            del self.timers[file_path]
        self.pending_data.pop(file_path, None)


class GlobalDebounceTimer:
    """Single global debounce timer that accumulates changed files."""

    def __init__(self, delay: float, name: str = "debounce"):
        self.delay = delay
        self.name = name
        self.timer: asyncio.Task | None = None
        self.pending_files: set[str] = set()

    async def schedule(self, file_path: str, callback):
        self.pending_files.add(file_path)
        if self.timer is not None:
            self.timer.cancel()

        async def delayed_callback():
            await asyncio.sleep(self.delay)
            files = self.pending_files.copy()
            self.pending_files.clear()
            self.timer = None
            await callback(files)

        self.timer = asyncio.create_task(delayed_callback())
        log(f"{self.name} timer reset ({self.delay}s) — {len(self.pending_files)} file(s) pending")

    def cancel(self, file_path: str):
        self.pending_files.discard(file_path)
        if not self.pending_files and self.timer is not None:
            self.timer.cancel()
            self.timer = None


async def main():
    log("Starting journal watcher")
    print(f"  Watching: {JOURNAL_DIR}")
    print(f"  General edit debounce: {DEBOUNCE_SECONDS}s")
    print(f"  Mention reply debounce: {SHORT_DEBOUNCE_SECONDS}s")
    print(f"  Auto reviews enabled: {AUTO_REVIEWS_ENABLED}")

    state = load_state()
    long_debounce = GlobalDebounceTimer(DEBOUNCE_SECONDS, name="general")
    short_debounce = DebounceTimer(SHORT_DEBOUNCE_SECONDS, name="reply")

    async def on_long_debounce_timeout(file_paths: set[str]):
        file_names = ", ".join(Path(f).name for f in sorted(file_paths))
        log(f"General review timeout for {file_names}")
        diff = get_uncommitted_diff()
        run_review('debounced', file=file_names, diff=diff)

        now = datetime.now()
        for fp in file_paths:
            review_cooldowns[fp] = now

        current = load_state()
        for fp in file_paths:
            current.setdefault('files', {}).setdefault(file_key(Path(fp)), {})['lastReview'] = now.isoformat()
        save_state(current)

    async def on_short_debounce_timeout(file_path: str, data: dict):
        log(f"Mention reply timeout for {Path(file_path).name}")
        diff = get_uncommitted_diff()
        run_review('mention', file=file_path, context=data.get('context'), diff=diff)
        review_cooldowns[file_path] = datetime.now()

    async for changes in awatch(JOURNAL_DIR, recursive=False):
        for change_type, file_path in changes:
            if not file_path.endswith('.md'):
                continue

            if change_type == Change.deleted:
                long_debounce.cancel(file_path)
                short_debounce.cancel(file_path)
                continue

            file_path_obj = Path(file_path)
            log(f"Change detected: {file_path_obj.name}")

            cooldown_time = review_cooldowns.get(file_path)
            if cooldown_time:
                elapsed = (datetime.now() - cooldown_time).total_seconds()
                if elapsed < REVIEW_COOLDOWN_SECONDS:
                    log(f"Skipping {file_path_obj.name} (in cooldown, {REVIEW_COOLDOWN_SECONDS - elapsed:.0f}s remaining)")
                    continue
                del review_cooldowns[file_path]

            analysis = analyze_file(file_path_obj, state)
            if analysis is None:
                continue

            action = analysis['action']
            file_state = state.setdefault('files', {}).setdefault(file_key(file_path_obj), {})
            file_state.update(analysis.get('new_state', {}))
            save_state(state)

            if action == 'mention':
                long_debounce.cancel(file_path)
                log(f"@claude mention detected in {file_path_obj.name}")
                await short_debounce.schedule(
                    file_path,
                    on_short_debounce_timeout,
                    {'context': analysis['context']}
                )

            elif action == 'debounced':
                if not AUTO_REVIEWS_ENABLED:
                    continue
                if file_path not in short_debounce.timers:
                    await long_debounce.schedule(file_path, on_long_debounce_timeout)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWatcher stopped")
