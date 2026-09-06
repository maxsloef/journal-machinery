# SETUP.md — instructions for Claude Code

You are Claude Code, opened in a clone of `journal-machinery`. The person you're working with wants this installed into their Obsidian journal vault. You have no prior context on this system; this file is the context. Read `README.md` too, it is short.

## What you're installing

A watcher that lets the user write `@claude …` inside a journal entry in Obsidian and get a reply from you, written into the file as a comment callout, about a minute later. Optionally, unprompted reviews. Details in README.

## Steps

1. **Check prerequisites.** Run `claude --version`, `uv --version`, `git --version`. If any is missing, stop and tell the user how to install it (Claude Code: https://claude.com/claude-code; uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`). Also confirm this is macOS; the scheduling uses launchd.

2. **Find out two things** if the user hasn't told you: the path to their vault (the folder Obsidian opens, containing their `.md` entries), and the first name they want used in prompts and comment headers. Don't guess the vault path; `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/<name>` is common for iCloud vaults, but ask.

3. **Look at the vault before touching it.** `ls` the vault. Note whether it already has a `CLAUDE.md`, a `reviews/` folder, a `.git`, or a `.obsidian/plugins/comments/`. `install.sh` won't overwrite any of these; if `CLAUDE.md` exists you'll need to merge `templates/vault-CLAUDE.md` into it by hand afterwards. Journal entries do not have to be named by date, but the watcher only looks at top-level `.md` files, not subfolders.

4. **Run the installer** from this repo's root:
   ```bash
   ./install.sh "/path/to/vault" "FirstName"
   ```
   Read its output. It prints what it did per step. It creates the Python env at `~/.venvs/journal-reviews` and writes two plists to `~/Library/LaunchAgents` but does not load them.

5. **Sanity check the compile step:**
   ```bash
   cd "/path/to/vault/reviews" && ./compile_journal.sh
   ```
   It should report a line count and no warnings. Warnings mean some files are unreadable (usually iCloud eviction); tell the user which ones.

6. **Start the watcher:** `./reload.sh` from the same folder, then `tail -n 20 /tmp/journal-watcher.log`. You should see `Starting journal watcher` and the vault path. If instead `/tmp/journal-watcher-error.log` has a traceback, read it; the usual causes are `uv` or `claude` not being where the plist's PATH expects (check `which uv` and `which claude` and adjust the plist).

7. **Do a live test with the user.** Ask them to open today's entry in Obsidian, write `@claude are you there?` on its own line, and save. Within ~30 seconds the log should show `@claude mention detected`, then `Running review (mention)`, then a minute or two later `Review complete`. A `> [!comment] Claude | …` block should appear in the file. If the log says `Review skipped`, the review ran but Claude chose not to write; that's allowed, but for a hello it usually shouldn't happen, so check `/tmp/journal-watcher-error.log`.

8. **Explain the switches** to the user, briefly: mentions are always on; `AUTO_REVIEWS_ENABLED` in `reviews/config.py` turns on the 10-minute and 3 AM unprompted reviews (needs `reload.sh` after changing); `reviews/chat.sh` opens a full-journal chat. And the privacy notes from the README: the entire journal goes to the API on every review, and reviews get committed to git (and pushed, if there's a remote).

9. **Commit** the vault if the user wants it tracked: `install.sh` ran `git init` if needed, but made no commit. Ask before adding a remote; a private one is the only sensible kind for a journal.

## When you are later summoned by a mention

That's a different session: `review.py` starts you with the entire journal in the prompt and the vault's `CLAUDE.md` loaded. Follow that file. The short version: reply as a nested `> [!comment] Claude | <timestamp>` block directly beneath the mention, using the Edit tool, be specific to what the person actually wrote, and don't reply at all if you have nothing real to say.
