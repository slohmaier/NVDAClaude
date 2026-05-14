# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NVDAClaude** — NVDA add-on that makes the Anthropic Claude desktop client (`claude.exe`, Electron/Chromium, window class `Chrome_WidgetWin_1`) more accessible.

Current scope (v0.2): keyboard navigation between messages on both the **Chat** and **Code** surfaces. **Cowork** surface is not yet supported; gestures no-op there.

## Git

- Commit email: `stefan@slohmaier.de`
- Remote: `https://github.com/slohmaier/NVDAClaude`

## How the Claude desktop client exposes its surfaces to UIA

Both surfaces share the outer scaffolding: `Group Name="Hauptbereich"` / `"Main area"` wraps the scrollable conversation area, with the sidebar (chat history / session list) sitting outside it.

### Chat surface

Before each turn there is a 1×1-pixel screen-reader-only Text element acting as anchor:

- User turn (DE): `ControlType=Text`, `ClassName=sr-only`, `Name="Du hast gesagt: …"`
- User turn (EN): same shape, `Name="You said: …"`
- Assistant turn (DE): `Name="Claude hat geantwortet: …"`
- Assistant turn (EN): `Name="Claude said: …"` or `"Claude responded: …"`

After each assistant turn a `StatusBar` element with `ClassName=sr-only` (empty name) marks "answer complete" (likely `role="status"`).

Per-message footer: `Group Name="Message actions"` (timestamp + feedback + copy).

### Code surface

No `sr-only` anchors. Instead, every turn ends with a deterministic two-button footer:

| Button name (DE / EN) | Meaning |
|---|---|
| `Nachricht kopieren` / `Copy message` | Universal copy button — appears on every turn |
| `Von hier forken` / `Fork from here` | **Only on user turns** — used as the per-turn speaker marker |
| `Als Kapitel anheften` / `Pin as chapter` | **Only on Claude turns** — used as the per-turn speaker marker |

Claude turns are often prefixed with one or more activity-summary `Button` elements with names like `"Ausgeführt 13 Befehle, …"` / `"Ran 13 commands, …"`. These describe tool use and we treat them as part of the turn content.

Per-turn layout (in document order):

```
[optional activity buttons]    # only on Claude turns
[content Text / Hyperlinks / lists]
"Nachricht kopieren"           # universal end-of-message button
"Von hier forken" | "Als Kapitel anheften"   # speaker marker
[timestamp Group]              # e.g. "2h ago"
```

### Re-verifying with dumpUIA

```powershell
python ..\dumpUIA\dumpUIA.py                    # list windows, find Claude's HWND
python ..\dumpUIA\dumpUIA.py -w <hwnd> -j > x.json
```

Reference dumps preserved at:
- `~/git/claude-uia.json` (Chat surface, 2026-05-13)
- `~/git/claude-code-uia.json` (Code surface, 2026-05-14)

## Code structure

```
addon/appModules/claude.py   # AppModule with all gestures (single file)
buildVars.py                 # addon metadata (name, version, license, …)
sconstruct                   # SCons build entry point (copied from template)
site_scons/                  # SCons helper tools (copied from template)
manifest.ini.tpl             # manifest template, populated by SCons
addon/doc/en/readme.md       # copied from project-root readme.md at build time
```

Reference implementation patterns Stefan has used: `~/git/NVDAiCloudPasswordManager/addon/appModules/icloudpasswords.py` (AppModule with overlay classes — different pattern; this addon doesn't need overlay classes).

## AppModule design

- Filename must be lowercase (`claude.py`) — NVDA lowercases the exe name before importing.
- Each gesture is a `@script`-decorated method on `AppModule`.
- Internally, turns are normalized into `_Turn(speaker, nav_obj, start_top, end_top)`. Each surface has its own collector (`_collect_chat_turns`, `_collect_code_turns`); `_collect_turns` tries chat first, falls back to code.
- `_move_to(obj)` scrolls into view + sets review position + speaks.
- `_collect_message_text(turn, root)` gathers all content between `turn.start_top` and `turn.end_top`, skipping 1×1 sr-only fillers and the universal footer buttons (`Nachricht kopieren`, `Als Kapitel anheften`, `Von hier forken`, EN equivalents).
- Tuneables at the top of `claude.py`:
  - `CHAT_USER_PREFIXES`, `CHAT_ASSISTANT_PREFIXES` — sr-only anchor prefixes
  - `CODE_USER_TERMINATORS`, `CODE_ASSISTANT_TERMINATORS` — exact-match button names
  - `CODE_ACTIVITY_PREFIXES` — only used for documentation, not currently filtered
  - `MAIN_AREA_NAMES`, `MAX_WALK_DEPTH`

## Future work

- **Cowork surface support**: needs a fresh `dumpUIA` capture while the desktop client is in Cowork mode. Add a `_collect_cowork_turns` after the same pattern.
- **Stronger surface detection**: today the dispatcher just tries chat then code. If a future surface looks accidentally like one of them (e.g. a button accidentally named "Pin as chapter") we'd misroute. A canonical signal — Hauptbereich's first descendant's class name, or an aria-label on the chat container — would be more robust.
- **Streaming indicator**: the empty `StatusBar`-`sr-only` on the Chat surface could be an "answer complete" event hook.
- **Filtering activity buttons on Code**: currently "read full message" includes the "Ran 13 commands, …" activity summary; if too verbose, add an option to skip lines starting with `CODE_ACTIVITY_PREFIXES`.

## Build

```powershell
scons          # build the .nvda-addon
scons install  # build + install into NVDA
scons pot      # regen translation template
```

After install, restart NVDA. Inspect `nvda.log` for `NVDAClaude:` debug lines.

## Code style

- Tabs for indentation (configured in `pyproject.toml`).
- Line length: 110.
- pyright strict, ruff lint.
