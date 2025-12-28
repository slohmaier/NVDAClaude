# Claude Desktop Accessibility Plugin for NVDA
# Copyright (C) 2024 Stefan Lohmaier
# This file is covered by the GNU General Public License.
# See the file COPYING.txt for more details.

"""
NVDA global plugin to make Claude Desktop more accessible.
Monitors Claude Desktop for status changes and speaks them,
then focuses the response when complete.
"""

import threading
import time
from typing import Optional
import weakref

import api
import appModuleHandler
import controlTypes
import eventHandler
import globalPluginHandler
import speech
import ui
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA


# Claude Desktop window class
CLAUDE_WINDOW_CLASS = "Chrome_WidgetWin_1"
CLAUDE_WINDOW_TITLE = "Claude"


class StatusMonitor:
	"""Monitors Claude Desktop for status changes and response completion."""

	def __init__(self, plugin: "GlobalPlugin"):
		self._plugin = weakref.ref(plugin)
		self._running = False
		self._thread: Optional[threading.Thread] = None
		self._last_status: Optional[str] = None
		self._was_generating = False
		self._poll_interval = 0.5  # seconds

	def start(self):
		"""Start the status monitoring thread."""
		if self._running:
			return
		self._running = True
		self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
		self._thread.start()
		log.debug("Claude Desktop status monitor started")

	def stop(self):
		"""Stop the status monitoring thread."""
		self._running = False
		if self._thread:
			self._thread.join(timeout=2.0)
			self._thread = None
		log.debug("Claude Desktop status monitor stopped")

	def _get_claude_window(self) -> Optional[NVDAObject]:
		"""Find the Claude Desktop window."""
		try:
			fg = api.getForegroundObject()
			if fg and self._is_claude_window(fg):
				return fg
			# Check if Claude is open but not focused
			desktop = api.getDesktopObject()
			if desktop:
				for child in desktop.children:
					if self._is_claude_window(child):
						return child
		except Exception as e:
			log.debugWarning(f"Error finding Claude window: {e}")
		return None

	def _is_claude_window(self, obj: NVDAObject) -> bool:
		"""Check if the given object is the Claude Desktop window."""
		try:
			if obj.windowClassName == CLAUDE_WINDOW_CLASS:
				name = obj.name or ""
				return CLAUDE_WINDOW_TITLE.lower() in name.lower()
		except Exception:
			pass
		return False

	def _find_status_elements(self, root: NVDAObject) -> list[NVDAObject]:
		"""Find status indicator elements in Claude Desktop."""
		status_elements = []
		try:
			self._traverse_for_status(root, status_elements, max_depth=10)
		except Exception as e:
			log.debugWarning(f"Error finding status elements: {e}")
		return status_elements

	def _traverse_for_status(self, obj: NVDAObject, results: list, depth: int = 0, max_depth: int = 10):
		"""Recursively traverse the UI tree looking for status indicators."""
		if depth > max_depth:
			return

		try:
			# Look for text elements that might contain status info
			name = obj.name or ""
			role = obj.role

			# Common status patterns in Claude Desktop
			status_keywords = [
				"thinking", "generating", "typing", "processing",
				"loading", "waiting", "sending", "responding",
				"claude is", "stop"
			]

			name_lower = name.lower()
			for keyword in status_keywords:
				if keyword in name_lower:
					results.append(obj)
					break

			# Also check for progress indicators
			if role in (controlTypes.Role.PROGRESSBAR, controlTypes.Role.ANIMATION):
				results.append(obj)

			# Traverse children
			for child in obj.children or []:
				self._traverse_for_status(child, results, depth + 1, max_depth)

		except Exception as e:
			log.debugWarning(f"Error traversing UI tree: {e}")

	def _get_current_status(self, window: NVDAObject) -> Optional[str]:
		"""Get the current status from Claude Desktop."""
		status_elements = self._find_status_elements(window)
		for elem in status_elements:
			try:
				name = elem.name
				if name:
					return name
			except Exception:
				pass
		return None

	def _is_generating(self, status: Optional[str]) -> bool:
		"""Check if Claude is currently generating a response."""
		if not status:
			return False
		status_lower = status.lower()
		generating_keywords = ["thinking", "generating", "typing", "processing", "stop"]
		return any(kw in status_lower for kw in generating_keywords)

	def _focus_response(self, window: NVDAObject):
		"""Focus the response area after generation completes."""
		try:
			# Try to find and focus the latest response
			self._find_and_focus_response(window)
		except Exception as e:
			log.debugWarning(f"Error focusing response: {e}")

	def _find_and_focus_response(self, root: NVDAObject, depth: int = 0, max_depth: int = 15):
		"""Find the response content area and focus it."""
		if depth > max_depth:
			return False

		try:
			# Look for document or text areas that might contain the response
			role = root.role
			if role in (controlTypes.Role.DOCUMENT, controlTypes.Role.EDITABLETEXT):
				# Try to focus this element
				if root.isFocusable:
					root.setFocus()
					# Move to the beginning of the response
					api.setNavigatorObject(root)
					speech.speakObject(root, reason=controlTypes.OutputReason.FOCUS)
					return True

			# Also look for group elements that might be message containers
			name = root.name or ""
			if "message" in name.lower() or "response" in name.lower():
				if root.isFocusable:
					root.setFocus()
					api.setNavigatorObject(root)
					speech.speakObject(root, reason=controlTypes.OutputReason.FOCUS)
					return True

			# Traverse children
			for child in root.children or []:
				if self._find_and_focus_response(child, depth + 1, max_depth):
					return True

		except Exception as e:
			log.debugWarning(f"Error in find_and_focus_response: {e}")

		return False

	def _monitor_loop(self):
		"""Main monitoring loop."""
		while self._running:
			try:
				window = self._get_claude_window()
				if window:
					current_status = self._get_current_status(window)
					is_generating = self._is_generating(current_status)

					# Announce status changes
					if current_status and current_status != self._last_status:
						# Queue the message to be spoken on the main thread
						self._speak_status(current_status)
						self._last_status = current_status

					# Check if generation just completed
					if self._was_generating and not is_generating:
						# Generation completed - focus the response
						self._on_generation_complete(window)

					self._was_generating = is_generating

			except Exception as e:
				log.debugWarning(f"Error in monitor loop: {e}")

			time.sleep(self._poll_interval)

	def _speak_status(self, status: str):
		"""Speak a status message (thread-safe)."""
		try:
			# Use wx.CallAfter to ensure we're on the main thread
			import wx
			wx.CallAfter(ui.message, status)
		except Exception as e:
			log.debugWarning(f"Error speaking status: {e}")

	def _on_generation_complete(self, window: NVDAObject):
		"""Called when Claude finishes generating a response."""
		try:
			import wx

			def _announce_and_focus():
				# Translators: Announced when Claude finishes generating a response
				ui.message(_("Response complete"))
				self._focus_response(window)

			wx.CallAfter(_announce_and_focus)
		except Exception as e:
			log.debugWarning(f"Error on generation complete: {e}")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""NVDA global plugin for Claude Desktop accessibility."""

	def __init__(self):
		super().__init__()
		self._status_monitor = StatusMonitor(self)
		self._status_monitor.start()
		log.info("Claude Desktop accessibility plugin loaded")

	def terminate(self):
		"""Clean up when the plugin is terminated."""
		self._status_monitor.stop()
		log.info("Claude Desktop accessibility plugin unloaded")
		super().terminate()

	def event_gainFocus(self, obj: NVDAObject, nextHandler):
		"""Handle focus events to detect when Claude Desktop is focused."""
		try:
			if self._is_claude_desktop(obj):
				log.debug("Claude Desktop focused")
		except Exception as e:
			log.debugWarning(f"Error in gainFocus event: {e}")
		nextHandler()

	def _is_claude_desktop(self, obj: NVDAObject) -> bool:
		"""Check if the focused object is part of Claude Desktop."""
		try:
			# Walk up the parent chain to find the top-level window
			current = obj
			for _ in range(20):  # Limit depth to avoid infinite loops
				if current is None:
					break
				if current.windowClassName == CLAUDE_WINDOW_CLASS:
					name = current.name or ""
					if CLAUDE_WINDOW_TITLE.lower() in name.lower():
						return True
				current = current.parent
		except Exception:
			pass
		return False
