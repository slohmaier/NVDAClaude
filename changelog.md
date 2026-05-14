# Changelog

## 0.2.0 — unreleased

- Adds support for the **Code surface** (Claude Code sessions in the desktop client).
  - Per-turn terminator buttons are used as anchors:
    - `"Von hier forken"` / `"Fork from here"` — end of user message
    - `"Als Kapitel anheften"` / `"Pin as chapter"` — end of Claude response
  - The navigation lands on the first content element of the turn (the prose, or the activity summary if Claude opened the turn with tool use).
  - "Read in full" includes activity summaries (e.g. "Ran 13 commands, …") but skips the per-message footer buttons.
- Refactored internals around a surface-agnostic `_Turn` model. Surface auto-detected: Chat anchors take precedence, Code anchors are tried as fallback. Cowork is still no-op.

## 0.1.0 — unreleased

- Initial release.
- App module for `claude.exe` adds keyboard navigation between chat messages:
  - `NVDA+Alt+J` / `K` — next / previous message
  - `NVDA+Alt+U` / `Shift+U` — next / previous user message
  - `NVDA+Alt+A` / `Shift+A` — next / previous Claude response
  - `NVDA+Alt+T` / `B` — first / last message
  - `NVDA+Alt+I` — focus chat input
  - `NVDA+Alt+C` — read current message in full
  - `NVDA+Alt+Shift+C` — copy current message to clipboard
- Uses the screen-reader-only turn anchors that Anthropic already ships in
  the chat DOM (`"You said: …"` / `"Claude said: …"` and their localized
  variants).
- German and English locale anchors recognized; add new prefixes in
  `addon/appModules/claude.py` for other languages.
- Code and Cowork surfaces are not yet supported — gestures no-op there.
