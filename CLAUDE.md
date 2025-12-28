# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NVDAClaude** - An NVDA screen reader add-on that makes Claude Desktop (Electron app) more accessible by:
- Speaking UI status updates (thinking, generating, processing)
- Announcing tool actions (reading file, searching, running command, etc.)
- Announcing when responses complete and focusing the response content

## Build Commands

```powershell
# Build the .nvda-addon package
scons

# Create development build with date-based version
scons dev=1

# Generate translation template
scons pot

# Clean build artifacts
scons -c
```

Requirements: Python 3.10+, SCons, GNU Gettext (for translations)

## Architecture

### Directory Structure
- `addon/globalPlugins/claudeDesktop.py` - Main plugin code with status monitoring and focus management
- `buildVars.py` - Add-on metadata (name, version, author, NVDA version requirements)
- `sconstruct` - SCons build configuration (inherited from nvaccess/addonTemplate)
- `site_scons/` - NVDA addon build tools

### Core Components

**StatusMonitor** (`claudeDesktop.py`): Background thread that:
1. Polls Claude Desktop window for status elements via UIA (0.3s interval)
2. Distinguishes main status (thinking, generating) from action indicators (reading, searching)
3. Tracks active actions in a set to only announce new ones
4. Speaks updates via `ui.message()` on main thread
5. Detects when generation completes and focuses response

**GlobalPlugin**: NVDA plugin entry point that:
- Starts/stops StatusMonitor on load/unload
- Handles focus events to detect Claude Desktop

### Claude Desktop Detection
- Window class: `Chrome_WidgetWin_1`
- Window title contains: `Claude`
- Uses Windows UI Automation to traverse element tree (up to 25 levels deep for Electron)

### Thread Safety
All UI interactions use `wx.CallAfter()` to ensure they run on NVDA's main thread.

## Key Patterns

- Main status keywords: "thinking", "generating", "stop"
- Action keywords: "reading", "writing", "searching", "running", "analyzing", etc.
- Tree traversal is depth-limited (25 levels for Electron app web content)
- Also checks for UIA live regions for dynamic updates
- Uses `weakref` for plugin reference to prevent circular references

## Electron App Limitations

Claude Desktop is an Electron app with Chromium webview. The inline action indicators
(rounded rectangles showing "Reading file...", etc.) may not always be fully exposed
via Windows UI Automation. The plugin uses multiple strategies:
1. Deep UIA tree traversal
2. Live region detection
3. Keyword matching on element names
