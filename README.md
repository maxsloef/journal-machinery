# journal-machinery

Tooling that lets Claude Code live inside an Obsidian journal: it watches the vault, replies inline when you write `@claude`, can review entries on its own if you let it, and can open a chat with the whole journal already in context.

Extracted from Max's journal repo (September 2026) so a friend can run the same setup. Nothing from the journal itself is here, only the code.

## What you get

| Piece | What it does |
|---|---|
| `reviews/watcher.py` | Runs forever under launchd. Watches the vault's top-level `.md` files. An unanswered `@claude` mention triggers a reply after 30 seconds of quiet. |
| `reviews/review.py` | The agent. Compiles the whole journal into one prompt, runs Claude with `permission_mode=auto` in the vault, and commits whatever it wrote. Modes: `mention`, `debounced`, `overnight`. |
| `reviews/config.py` | Your name, the model (`fable[1m]`), and the `AUTO_REVIEWS_ENABLED` switch. |
| `reviews/compile_journal.sh` | Concatenates every entry into `/tmp/full_journal.txt`. Used by the agent, by `chat.sh`, and by the semantic-search recipe in the vault's `CLAUDE.md`. |
| `reviews/chat.sh` | `chat.sh "opening message"` starts an interactive Claude Code session with the full journal preloaded. |
| `reviews/reload.sh` | Reloads both launchd agents. |
| `templates/vault-CLAUDE.md` | Becomes `<vault>/CLAUDE.md`: tells Claude how comments and threads are formatted, how to search, and to write session notes. |
| `templates/launchd/*.plist` | The watcher (always on) and the 3 AM overnight review. |
| `obsidian/plugins/comments/` | The [Comments](https://github.com/JasperSurmont/obsidian-comments) plugin (MIT) that renders the `> [!comment]` callouts. |
| `install.sh` | Puts all of the above where it belongs. |

## Prerequisites

- macOS (launchd is used for scheduling).
- [Claude Code](https://claude.com/claude-code) installed and logged in, with access to Fable. `claude --version` should work in a terminal.
- [uv](https://docs.astral.sh/uv/) on your PATH.
- `git`.
- Obsidian, with Community plugins enabled in Settings.

## Install

The intended path is to open Claude Code in this folder and say "set this up for my vault at ~/path/to/vault". It will follow `SETUP.md`. By hand, it's:

```bash
./install.sh /path/to/vault "YourFirstName"
cd /path/to/vault/reviews
./compile_journal.sh          # sanity check
./reload.sh                   # start the watcher
tail -f /tmp/journal-watcher.log
```

Then write `@claude hello?` at the bottom of today's entry, save, and wait about a minute. A `> [!comment] Claude | …` block should appear beneath it.

## How the comment format works

Comments are Obsidian callouts. Replies nest one level deeper:

```markdown
Something I wrote. @claude what do you make of this?

> [!comment] Claude | 2026-09-06 11:02 PDT
> Reply.
>
>> [!comment] Ada | 2026-09-06
>> Follow-up question. @claude?
>>
>>> [!comment] Claude | 2026-09-06 11:20 PDT
>>> Reply to the follow-up.
```

A mention counts as answered when the next comment header after it belongs to Claude. Mentions inside backticks, and inside Claude's own comments, are ignored. Each distinct mention fires once; if Claude decides it has nothing to add, it stays quiet and won't be re-asked unless you write a new mention.

## The switches

`reviews/config.py`:

- `AUTO_REVIEWS_ENABLED = False` (default). Mentions always work. Set to `True` to also get a review after 10 minutes of quiet editing and a fuller review of the latest entry every night at 3 AM. Restart the watcher after changing it (`reload.sh`).
- `MODEL = "fable[1m]"`. The 1M-context variant is what makes "the whole journal in one prompt" workable. Once the journal outgrows that, the compile step needs a windowing strategy; that is not built yet.

## Where things land

- Logs: `/tmp/journal-watcher.log`, `/tmp/journal-watcher-error.log`, `/tmp/journal-overnight.log`.
- Watcher state (content hashes, handled mentions): `<vault>/reviews/state.json`, gitignored.
- Every review that edits a file is committed as `claude review`. If the vault has a git remote, it is pushed. Consider a **private** remote as a backup, or none at all.

## Privacy notes worth saying out loud

- Each review sends the entire journal to the Claude API. That is the point of the design, but it is the whole journal every time.
- If Fable's input classifier declines a request, the SDK falls back to another model; when that happens, the reply gets a visible footnote saying which model served it.
- Cloud-synced vaults (iCloud Drive especially) can evict files. The compile script inserts a loud `[WARNING: … MISSING]` marker instead of silently treating those entries as empty, and the watcher skips unreadable files until they're touched again.

## Differences from Max's copy (for backporting)

Bugs listed in the source repo's `CLAUDE.md` operating notes were fixed here rather than copied:

1. `review.py` decides "Claude responded" by hashing `*.md` before and after the run, not by watching for the `Edit` tool. Under auto mode the harness sometimes edits through Bash, which the old check missed, so replies were written but never committed.
2. `watcher.py` skips `CLAUDE.md`, strips inline code before matching `@claude`, ignores mentions inside Claude's own comment blocks, and records a signature for each mention it has fired on. No more zombie replies to months-old tags after a sync sweep.
3. `watcher.py` keys `state.json` by path relative to the vault, so a moved vault or renamed home directory doesn't make everything look new.
4. `watcher.py` catches `OSError` on read (evicted iCloud files crashed the old watcher, and each KeepAlive restart dropped pending timers).
5. `compile_journal.sh` warns instead of silently emitting empty entries, and exits 1 if any file was unreadable.
6. `review.py` finds the `claude` CLI via PATH with `~/.local/bin` as fallback, only pushes if a remote exists, and logs git failures instead of swallowing them.
7. The author's name and the model come from `config.py` instead of being hardcoded.
