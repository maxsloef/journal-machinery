"""Shared config for the journal review system.

install.sh fills in JOURNAL_AUTHOR. Everything else is safe to edit by hand.
"""

# The journal author's first name, as it appears in comment headers
# (`> [!comment] NAME | date`) and in the prompts Claude receives.
JOURNAL_AUTHOR = "__AUTHOR__"

# Model requested for every review. `fable[1m]` = Fable with the 1M context
# window, which is what makes "load the entire journal into the prompt" work.
MODEL = "fable[1m]"

# When False, the watcher won't trigger debounced general-edit reviews and the
# scheduled overnight review will exit immediately. @claude mention replies are
# unaffected and continue to work. Start with False; flip it on once mention
# replies feel right.
AUTO_REVIEWS_ENABLED = False
