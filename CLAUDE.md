# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NVDAClaude** — NVDA add-on that makes the Anthropic Claude desktop client (`claude.exe`) more accessible.

Current scope (v0.1, proposal stage): keyboard shortcuts to jump between chat messages.

## Git

- Commit email: `stefan@slohmaier.de`
- Remote: `https://github.com/slohmaier/NVDAClaude`

## How the Claude desktop client exposes the chat to UIA

The client is Electron/Chromium (`claude.exe`, window class `Chrome_WidgetWin_1`). The chat DOM is exposed via UIA; before each turn there is a 1×1-pixel `sr-only` Text element acting as anchor:

- User turn (DE): `ControlType=Text`, `ClassName=sr-only`, `Name="Du hast gesagt: …"`
- User turn (EN): same shape, `Name="You said: …"`
- Assistant turn (DE): `Name="Claude hat geantwortet: …"`
- Assistant turn (EN): `Name="Claude said: …"` or `"Claude responded: …"`

After each assistant turn a `StatusBar` element with `ClassName=sr-only` (empty name) marks "answer complete" (likely `role="status"`).

Outer container: `Group` `Name="Hauptbereich"` (localized) wraps the scrollable chat. Per-message footer: `Group` `Name="Message actions"` (timestamp + feedback buttons + copy).

Use `dumpUIA` to re-verify the structure when Anthropic ships UI changes:

```powershell
python ..\dumpUIA\dumpUIA.py            # list windows, find Claude's HWND
python ..\dumpUIA\dumpUIA.py -w <hwnd> -j > claude.json
```

A captured dump from 2026-05-13 is preserved at `~/git/claude-uia.json` for reference.

## Implementation pattern (proposed)

- **AppModule** at `addon/appModules/claude.py` (lowercase filename mandatory — NVDA lowercases the exe name before importing).
- Register `__gestures` dict on the `AppModule` subclass.
- Each gesture: enumerate descendants of the foreground window, filter Text objects whose `name` starts with a known turn prefix, sort by `location.top`, then `scrollIntoView()` + `setReviewPosition()` + speak.

Reference implementation patterns Stefan has used: `~/git/NVDAiCloudPasswordManager/addon/appModules/icloudpasswords.py` (AppModule with overlay classes).

## Build

(Once the SCons template is in place — same toolchain as Stefan's other addons:)

```powershell
scons          # build the .nvda-addon
scons install  # build + install into NVDA
scons pot      # regen translation template
```
