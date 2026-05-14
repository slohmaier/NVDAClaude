# Changelog

## 0.3.0 — unreleased

- **Cowork surface support.** Anthropic's Cowork view only ships the user turn anchor (`"Du hast gesagt: …"` / `"You said: …"` as a 1×1-pixel `sr-only` Text), not the assistant counterpart. The add-on now synthesizes Claude turns from the gap between consecutive user messages, using the per-message `"Copy"` button as the end-of-user marker. Tool invocations (`"Execute Shell Command"`, `"MacMini-Integration verwendet, geladene Tools"`, …) are read as part of the assistant response.
- **First-press behavior.** Pressing any navigation key while no turn has been visited yet now jumps to the latest message instead of computing position from NVDA's focus location. If Claude produces a new turn while the user is paused, the next gesture automatically snaps to that new latest.
- **Performance:** single UIA tree walk per gesture (down from two) and a 1.5 s cache of the result so rapid successive presses don't repeat the scan.
- **Internal:** `_Turn` now stores the raw `IUIAutomationElement` and precomputed `message_text`; NVDAObject wrapping is no longer attempted (Chromium DOM elements fail `UIA.__new__` with `E_INVALIDARG`).
- Diagnostic `NVDA+Alt+D` reports the Cowork collector too.
- Adjacent-duplicate suppression in message text (Cowork wraps tool buttons in sr-only StatusBars that re-emit the same text).

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
