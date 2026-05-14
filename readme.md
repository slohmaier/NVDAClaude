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

| Surface | v0.3 status | Anchor mechanism |
|---|---|---|
| Chat | **Supported** | Screen-reader-only turn anchors for both speakers (`"You said: …"` / `"Claude said: …"` and DE equivalents) |
| Code | **Supported** | Per-turn terminator buttons (`"Fork from here"` / `"Pin as chapter"` and DE equivalents `"Von hier forken"` / `"Als Kapitel anheften"`) |
| Cowork | **Supported** | Chat-style user sr-only anchors only; assistant turns are synthesized from the gap, using the per-message `"Copy"` button as the end-of-user marker. Tool invocations are read as part of the response. |

Surface is auto-detected per gesture (single UIA tree walk, then chat → cowork → code in priority order). If none of the patterns are present the add-on announces "No messages on this surface" and does nothing.

## Locales

Recognized markers (configurable at the top of `addon/appModules/claude.py`):

**Chat surface (sr-only anchor prefixes):**

- User: `Du hast gesagt:`, `You said:`
- Assistant: `Claude hat geantwortet:`, `Claude said:`, `Claude responded:`

**Code surface (terminator button names — exact match):**

- User: `Von hier forken`, `Fork from here`
- Assistant: `Als Kapitel anheften`, `Pin as chapter`

**Cowork surface:** reuses the chat user prefixes above; the Copy button at the end of each user message is matched against `Copy` / `Kopieren`.

If your Claude UI is in another language, add the corresponding strings to the constant tuples. Pull requests welcome.

## Building

```powershell
scons          # build the .nvda-addon file
scons install  # build + install into NVDA
scons pot      # regenerate translation template
```

The build output is `NVDAClaude-<version>.nvda-addon`.

## License

GPL v2. See `COPYING.txt`.
