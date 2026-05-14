# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NVDAClaude** — NVDA add-on that makes the Anthropic Claude desktop client (`claude.exe`, Electron/Chromium, window class `Chrome_WidgetWin_1`) more accessible.

Current scope (v0.1): keyboard navigation between chat messages. Code and Cowork surfaces are explicitly out of scope; gestures no-op there.

## Git

- Commit email: `stefan@slohmaier.de`
- Remote: `https://github.com/slohmaier/NVDAClaude`

## How the Claude desktop client exposes the chat to UIA

Before each turn there is a 1×1-pixel screen-reader-only Text element acting as anchor:

- User turn (DE): `ControlType=Text`, `ClassName=sr-only`, `Name="Du hast gesagt: …"`
- User turn (EN): same shape, `Name="You said: …"`
- Assistant turn (DE): `Name="Claude hat geantwortet: …"`
- Assistant turn (EN): `Name="Claude said: …"` or `"Claude responded: …"`

After each assistant turn a `StatusBar` element with `ClassName=sr-only` (empty name) marks "answer complete" (likely `role="status"`).

Outer container: `Group` with `Name="Hauptbereich"` / `"Main area"` wraps the scrollable chat. Per-message footer: `Group` `Name="Message actions"` (timestamp + feedback + copy).

Use `dumpUIA` to re-verify when Anthropic ships UI changes:

```powershell
python ..\dumpUIA\dumpUIA.py            # list windows, find Claude's HWND
python ..\dumpUIA\dumpUIA.py -w <hwnd> -j > claude.json
```

A captured dump from 2026-05-13 is preserved at `~/git/claude-uia.json` for reference.

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
- Navigation: `_collect_anchors(root)` walks descendants of the foreground window, filters STATICTEXT objects whose name starts with one of the configured prefixes, sorts by `location.top`. `_current_anchor_index` finds the user's position using the review cursor or focus top. `_move_to` scrolls into view + sets review position + speaks.
- "Read current message" / "Copy" use `_collect_message_text` which gathers Text/Link content between the current anchor and the next.
- Tuneables at the top of `claude.py`: `USER_PREFIXES`, `ASSISTANT_PREFIXES`, `MAIN_AREA_NAMES`, `MAX_WALK_DEPTH`.

## Future work

- **Code surface support**: needs a fresh `dumpUIA` capture while the desktop client is in Code mode. Add a `CodeSurface` navigator with its own anchor pattern.
- **Cowork surface support**: same — needs a capture.
- **Surface detection**: today, gestures simply fall through to "No messages on this surface" if no chat anchors are found. A more polished version could detect the surface by URL/heading and switch navigator implementations.
- **Streaming indicator**: the empty `StatusBar`-`sr-only` could be an "answer complete" event hook (v0.2).

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
