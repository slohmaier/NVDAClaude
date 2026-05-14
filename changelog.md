# Changelog

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
