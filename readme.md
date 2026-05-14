# NVDAClaude

An NVDA add-on that makes the **Anthropic Claude desktop client** (`claude.exe`) more accessible for screen reader users.

Adds keyboard shortcuts to jump between chat messages — next/previous, user-only, Claude-only, top/bottom, focus the input field, read the current message in full, copy it to the clipboard. Works in the chat surface; the Code and Cowork surfaces are not yet supported (gestures no-op there).

## Why this exists

Anthropic already ships screen-reader-only turn anchors in the Claude chat DOM: a 1×1-pixel `sr-only` text element before each turn whose name begins with "You said: …" / "Claude said: …" (and localized variants — "Du hast gesagt: …", "Claude hat geantwortet: …"). NVDA can see them via UIA, but there is no built-in way to jump between them, especially when focus sits in the message input field (focus mode), where NVDA's browse-mode quick-nav keys don't apply.

NVDAClaude registers per-app gestures that walk the chat DOM, find these anchors, and move the review cursor (and speak) directly to them.

## Default shortcuts

When `claude.exe` is in the foreground:

| Shortcut | Action |
|---|---|
| `NVDA+Alt+J` | Next message (any speaker) |
| `NVDA+Alt+K` | Previous message |
| `NVDA+Alt+U` | Next user message |
| `NVDA+Alt+Shift+U` | Previous user message |
| `NVDA+Alt+A` | Next Claude response |
| `NVDA+Alt+Shift+A` | Previous Claude response |
| `NVDA+Alt+T` | First message |
| `NVDA+Alt+B` | Last message |
| `NVDA+Alt+I` | Focus the chat input |
| `NVDA+Alt+C` | Read the current message in full |
| `NVDA+Alt+Shift+C` | Copy the current message to the clipboard |

All shortcuts can be re-bound through NVDA's "Input gestures" dialog (category: "Claude").

## Supported surfaces

The Claude desktop client has three different UI surfaces:

| Surface | v0.1 status |
|---|---|
| Chat | **Supported** |
| Code | Not yet — gestures no-op |
| Cowork | Not yet — gestures no-op |

If a gesture fires in Code or Cowork, the add-on announces "No messages on this surface" and does nothing else.

## Locales

Recognized turn-anchor prefixes (set in `addon/appModules/claude.py`):

- User: `Du hast gesagt:`, `You said:`
- Assistant: `Claude hat geantwortet:`, `Claude said:`, `Claude responded:`

If your Claude UI is in another language, add the corresponding prefixes to `USER_PREFIXES` / `ASSISTANT_PREFIXES`. Pull requests welcome.

## Building

```powershell
scons          # build the .nvda-addon file
scons install  # build + install into NVDA
scons pot      # regenerate translation template
```

The build output is `NVDAClaude-<version>.nvda-addon`.

## License

GPL v2. See `COPYING.txt`.
