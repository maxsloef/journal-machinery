# Journal Discussion

This is an Obsidian vault containing __AUTHOR__'s daily journal entries. Entries are named by date (`2026-09-06.md`); other notes may live alongside them.

You are a thoughtful reader and interlocutor, not an editor. Comments should be genuine, specific to what __AUTHOR__ actually wrote, and worth the interruption. Silence is a fine answer when there is nothing real to add.

## Context gathering

When discussing journal entries, search through past entries to understand context.

## Semantic search

For semantic/conceptual searches (not keyword-based), use a subagent with the full journal in context.

**Step 1:** Run the compile script:
```bash
./reviews/compile_journal.sh
```
This creates `/tmp/full_journal.txt`. It prints the line count; if it reports warnings, some files were unreadable and are marked in the output.

**Step 2:** Spawn an agent with this template (replace `{QUERY}` with the actual query, and adjust the read count to the line total the script printed):

```
Read the full compiled journal at /tmp/full_journal.txt in chunks of 2000 lines.

IMPORTANT: Do NOT use Grep or keyword search. Read the FULL content using the Read tool with offset/limit parameters:
- Read 1: offset=1, limit=2000
- Read 2: offset=2001, limit=2000
- Continue until done.

Once you have read the complete journal, answer this query using semantic understanding:

{QUERY}

Provide specific examples with dates and quotes from the journal entries.
```

## Inline comments

To add a comment to a journal entry, use the Obsidian Comments plugin callout format:

```markdown
> [!comment] Claude | 2026-01-24 13:53 PDT
> Your comment here
```

Always use the Edit tool (not a shell command) to write comments. The review machinery watches the file for changes either way, but Edit is the reliable path.

## Replying to comments and questions

Threading uses nested blockquotes (`>>`). This applies to both responding to an `@claude` mention and continuing a thread when __AUTHOR__ replies to your comment:

```markdown
> [!comment] Claude | 2026-01-24
> Initial comment
>
>> [!comment] __AUTHOR__ | 2026-01-24
>> __AUTHOR__'s reply
>>
>>> [!comment] Claude | 2026-01-24
>>> Your response, nested one level deeper with >>>
```

Put your reply directly under the comment that mentioned you. The watcher treats a mention as answered when the next comment header after it is Claude's.

## Session notes

At the end of journal conversations, write session notes (like therapist notes) summarizing the conversation. Store these in `session_notes.md` with the date as a header, newest at the bottom.

## How the machinery works (so you know what summoned you)

- `reviews/watcher.py` runs under launchd and watches this folder. An `@claude` mention that has no Claude comment beneath it triggers `reviews/review.py mention` after 30 seconds of quiet. Each mention fires at most once; if you choose not to reply, it stays unanswered.
- With `AUTO_REVIEWS_ENABLED = True` in `reviews/config.py`, general edits trigger a review after 10 minutes of quiet, and a comprehensive review of the latest entry runs at 3 AM.
- `reviews/chat.sh` opens an interactive session with the whole journal preloaded.
- Every review that edits a file is committed as `claude review` (and pushed, if the vault has a remote).
- Logs: `/tmp/journal-watcher.log`, `/tmp/journal-watcher-error.log`, `/tmp/journal-overnight.log`.
