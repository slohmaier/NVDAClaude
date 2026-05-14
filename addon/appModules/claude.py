# NVDAClaude — App module for the Anthropic Claude desktop client (claude.exe).
# Copyright (C) 2026 Stefan Lohmaier <stefan@slohmaier.de>
# Licensed under the GNU General Public License v2.
#
# Provides keyboard navigation between chat messages by locating the
# screen-reader-only turn anchors that Anthropic already ships in the
# Chromium DOM ("You said: …" / "Claude said: …" and their localized
# counterparts).

from __future__ import annotations

from typing import Iterator, List, Optional, Tuple

import api
import appModuleHandler
import controlTypes
import speech
import textInfos
import ui
from logHandler import log
from NVDAObjects import NVDAObject
from scriptHandler import script

try:
	from builtins import _  # type: ignore[attr-defined]
except ImportError:
	def _(x):
		return x


# --------------------------------------------------------------------------
# Turn-anchor prefixes
# --------------------------------------------------------------------------
# Each turn (one user message or one assistant message) in the Claude chat
# DOM is preceded by a 1x1 px screen-reader-only <span> exposed to UIA as a
# Text element whose Name starts with one of these prefixes. They are the
# basis for next/previous-message navigation. Add new prefixes here when
# new UI locales are encountered.

USER_PREFIXES: Tuple[str, ...] = (
	"Du hast gesagt:",   # de
	"You said:",         # en
)

ASSISTANT_PREFIXES: Tuple[str, ...] = (
	"Claude hat geantwortet:",  # de
	"Claude said:",             # en (older)
	"Claude responded:",        # en (newer)
)

ALL_PREFIXES: Tuple[str, ...] = USER_PREFIXES + ASSISTANT_PREFIXES

# Localized names of the main chat container <main role="main">. Used to
# scope the descendant walk so we don't recurse into the sidebar.
MAIN_AREA_NAMES: Tuple[str, ...] = (
	"Hauptbereich",  # de
	"Main area",     # en
	"Main",          # en (fallback)
)

# How deep we recurse below the main area. The chat DOM is typically
# 8–12 levels deep; 25 is comfortably above the worst case.
MAX_WALK_DEPTH = 25


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _safe_attr(obj: NVDAObject, name: str, default=None):
	try:
		return getattr(obj, name, default)
	except Exception:
		return default


def _walk_descendants(obj: NVDAObject, max_depth: int = MAX_WALK_DEPTH) -> Iterator[NVDAObject]:
	"""Yield every descendant of ``obj`` in document order.

	Uses ``firstChild`` / ``next`` to traverse so it works for both UIA and
	IA2 backends. Bounded by ``max_depth`` to keep walks cheap and to avoid
	pathological loops if a backend ever returns a self-referential tree.
	"""
	if obj is None or max_depth < 0:
		return
	try:
		child = obj.firstChild
	except Exception:
		child = None
	while child is not None:
		yield child
		yield from _walk_descendants(child, max_depth - 1)
		try:
			child = child.next
		except Exception:
			break


def _name_starts_with(obj: NVDAObject, prefixes: Tuple[str, ...]) -> bool:
	try:
		name = obj.name or ""
	except Exception:
		return False
	return any(name.startswith(p) for p in prefixes)


def _find_main_area(root: NVDAObject) -> Optional[NVDAObject]:
	"""Locate the main chat region (``<main>``) inside the Claude window.

	Falls back to ``root`` if no match — the walk then becomes whole-window
	scope, which is slower but still correct.
	"""
	for obj in _walk_descendants(root, max_depth=15):
		try:
			if obj.role == controlTypes.Role.GROUP and obj.name in MAIN_AREA_NAMES:
				return obj
		except Exception:
			continue
	return None


def _collect_anchors(
	root: NVDAObject,
	prefixes: Tuple[str, ...] = ALL_PREFIXES,
) -> List[NVDAObject]:
	"""Return all turn anchors matching ``prefixes`` in reading order."""
	main = _find_main_area(root) or root
	anchors: List[NVDAObject] = []
	for obj in _walk_descendants(main):
		try:
			if obj.role != controlTypes.Role.STATICTEXT:
				continue
		except Exception:
			continue
		if not _name_starts_with(obj, prefixes):
			continue
		anchors.append(obj)
	# Sort by visual top — anchors live in document order already, but be
	# defensive against shadow-DOM or virtualization shenanigans.
	def _top(o: NVDAObject) -> int:
		loc = _safe_attr(o, "location")
		if loc is None:
			return 0
		try:
			return int(loc.top)
		except Exception:
			return 0
	anchors.sort(key=_top)
	return anchors


def _current_anchor_index(anchors: List[NVDAObject]) -> int:
	"""Return the index of the anchor closest to the user's current vertical
	position, or -1 if no useful reference position is available.

	"Current" means: the largest-top anchor whose top is at or above the
	user's review/focus position. That maps naturally to "the message the
	user is currently reading."
	"""
	if not anchors:
		return -1
	ref_top: Optional[int] = None

	# Prefer the review cursor position — it follows browse-mode and
	# explicit caret moves.
	try:
		ti = api.getReviewPosition()
		if ti is not None:
			rect = _safe_attr(ti, "boundingRects", None)
			if rect:
				try:
					ref_top = int(rect[0].top)
				except Exception:
					ref_top = None
	except Exception:
		ref_top = None

	# Fall back to the focus object's top.
	if ref_top is None:
		focus = api.getFocusObject()
		loc = _safe_attr(focus, "location") if focus is not None else None
		if loc is not None:
			try:
				ref_top = int(loc.top)
			except Exception:
				ref_top = None

	if ref_top is None:
		return -1

	idx = -1
	for i, anchor in enumerate(anchors):
		loc = _safe_attr(anchor, "location")
		if loc is None:
			continue
		try:
			if int(loc.top) <= ref_top:
				idx = i
			else:
				break
		except Exception:
			continue
	return idx


def _move_to(obj: NVDAObject) -> None:
	"""Best-effort: scroll the anchor into view, move the review cursor to
	it, and speak it.
	"""
	# UIA elements expose scrollIntoView; ignore failures (e.g. IA2 backend).
	try:
		obj.scrollIntoView()
	except Exception:
		pass

	# Move the review cursor.
	try:
		ti = obj.makeTextInfo(textInfos.POSITION_FIRST)
		api.setReviewPosition(ti)
	except Exception as exc:
		log.debug(f"NVDAClaude: setReviewPosition failed: {exc}")

	# Speak the anchor name — it already contains the first sentence of
	# the message, which is the right level of detail for navigation.
	try:
		speech.speakObject(obj, reason=controlTypes.OutputReason.FOCUS)
	except Exception:
		try:
			ui.message(obj.name or "")
		except Exception:
			pass


def _collect_message_text(anchor: NVDAObject, all_anchors: List[NVDAObject]) -> str:
	"""Concatenate the text content of every node between ``anchor`` and the
	next anchor (exclusive)."""
	try:
		anchor_top = int(anchor.location.top) if anchor.location else 0
	except Exception:
		anchor_top = 0
	# Top of the next anchor, or +∞ for the last message.
	next_top: Optional[int] = None
	for a in all_anchors:
		try:
			t = int(a.location.top) if a.location else 0
		except Exception:
			continue
		if t > anchor_top:
			next_top = t
			break

	main = _find_main_area(api.getForegroundObject()) or api.getForegroundObject()
	if main is None:
		return anchor.name or ""

	parts: List[str] = []
	# Skip the anchor itself (its name = the truncated first sentence).
	# We want the actual rendered text, which sits in sibling Text nodes.
	for obj in _walk_descendants(main):
		try:
			if obj.role not in (controlTypes.Role.STATICTEXT, controlTypes.Role.LINK):
				continue
		except Exception:
			continue
		loc = _safe_attr(obj, "location")
		if loc is None:
			continue
		try:
			top = int(loc.top)
		except Exception:
			continue
		# Strictly between the current anchor and the next one. The anchor
		# itself sits 1 px above the message body, so > anchor_top excludes it.
		if top <= anchor_top:
			continue
		if next_top is not None and top >= next_top:
			continue
		# Skip 1x1 sr-only filler elements (they would duplicate already-
		# announced anchor text).
		try:
			if loc.width <= 1 and loc.height <= 1:
				continue
		except Exception:
			pass
		name = (obj.name or "").strip()
		if name:
			parts.append(name)

	if not parts:
		return anchor.name or ""
	return "\n".join(parts)


# --------------------------------------------------------------------------
# App module
# --------------------------------------------------------------------------


class AppModule(appModuleHandler.AppModule):

	# ----- navigation -----

	def _navigate(self, prefixes: Tuple[str, ...], direction: int) -> None:
		"""``direction`` is +1 for forward, -1 for backward."""
		root = api.getForegroundObject()
		if root is None:
			# Translators: spoken when the Claude window cannot be located.
			ui.message(_("Claude window not found"))
			return
		anchors = _collect_anchors(root, prefixes=prefixes)
		if not anchors:
			# Translators: spoken when no messages are present (or the
			# current view isn't a chat — e.g. Code/Cowork surface).
			ui.message(_("No messages on this surface"))
			return
		# When navigating filtered (user-only / assistant-only) we still
		# want "current" to be defined relative to ALL anchors so jumps
		# feel correct from the user's perspective.
		all_anchors = (
			anchors if prefixes is ALL_PREFIXES
			else _collect_anchors(root, prefixes=ALL_PREFIXES)
		)
		cur_top = -1
		cur_idx_all = _current_anchor_index(all_anchors)
		if cur_idx_all >= 0:
			try:
				cur_top = int(all_anchors[cur_idx_all].location.top)
			except Exception:
				cur_top = -1

		# Find the next/prev anchor (in the filtered list) relative to cur_top.
		target: Optional[NVDAObject] = None
		if direction > 0:
			for a in anchors:
				try:
					t = int(a.location.top)
				except Exception:
					continue
				if t > cur_top:
					target = a
					break
		else:
			for a in reversed(anchors):
				try:
					t = int(a.location.top)
				except Exception:
					continue
				if t < cur_top or cur_top < 0:
					target = a
					break

		if target is None:
			# Translators: spoken when there is no further message in the
			# requested direction.
			ui.message(_("No more messages"))
			return
		_move_to(target)

	@script(
		# Translators: input help message for next-message script.
		description=_("Move to the next message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+j",
	)
	def script_nextMessage(self, gesture):
		self._navigate(ALL_PREFIXES, +1)

	@script(
		description=_("Move to the previous message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+k",
	)
	def script_previousMessage(self, gesture):
		self._navigate(ALL_PREFIXES, -1)

	@script(
		description=_("Move to the next user message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+u",
	)
	def script_nextUserMessage(self, gesture):
		self._navigate(USER_PREFIXES, +1)

	@script(
		description=_("Move to the previous user message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+u",
	)
	def script_previousUserMessage(self, gesture):
		self._navigate(USER_PREFIXES, -1)

	@script(
		description=_("Move to the next Claude response"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+a",
	)
	def script_nextAssistantMessage(self, gesture):
		self._navigate(ASSISTANT_PREFIXES, +1)

	@script(
		description=_("Move to the previous Claude response"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+a",
	)
	def script_previousAssistantMessage(self, gesture):
		self._navigate(ASSISTANT_PREFIXES, -1)

	# ----- top / bottom / input -----

	@script(
		description=_("Move to the first message in the chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+t",
	)
	def script_firstMessage(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		anchors = _collect_anchors(root)
		if not anchors:
			ui.message(_("No messages on this surface"))
			return
		_move_to(anchors[0])

	@script(
		description=_("Move to the last message in the chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+b",
	)
	def script_lastMessage(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		anchors = _collect_anchors(root)
		if not anchors:
			ui.message(_("No messages on this surface"))
			return
		_move_to(anchors[-1])

	@script(
		description=_("Move focus to the Claude chat input field"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+i",
	)
	def script_focusInput(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		main = _find_main_area(root) or root
		# The composer is the bottom-most editable element inside the main
		# region. There may be other Edit elements (e.g. an inline rename
		# in the header) — picking the one with the largest top discriminates.
		best: Optional[NVDAObject] = None
		best_top = -1
		for obj in _walk_descendants(main):
			try:
				if obj.role not in (
					controlTypes.Role.EDITABLETEXT,
					controlTypes.Role.DOCUMENT,
				):
					continue
				if controlTypes.State.READONLY in obj.states:
					continue
			except Exception:
				continue
			loc = _safe_attr(obj, "location")
			if loc is None:
				continue
			try:
				if int(loc.top) > best_top:
					best_top = int(loc.top)
					best = obj
			except Exception:
				continue
		if best is None:
			ui.message(_("Input field not found"))
			return
		try:
			best.setFocus()
		except Exception:
			_move_to(best)

	# ----- read / copy current message -----

	def _current_anchor(self) -> Optional[NVDAObject]:
		root = api.getForegroundObject()
		if root is None:
			return None
		anchors = _collect_anchors(root)
		if not anchors:
			return None
		idx = _current_anchor_index(anchors)
		if idx < 0:
			# Default to the last message if we can't locate the user.
			return anchors[-1]
		return anchors[idx]

	@script(
		description=_("Read the current message in full"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+c",
	)
	def script_readCurrentMessage(self, gesture):
		anchor = self._current_anchor()
		if anchor is None:
			ui.message(_("No messages on this surface"))
			return
		root = api.getForegroundObject()
		text = _collect_message_text(anchor, _collect_anchors(root)) if root else (anchor.name or "")
		if text:
			speech.speakText(text)
		else:
			speech.speakObject(anchor, reason=controlTypes.OutputReason.FOCUS)

	@script(
		description=_("Copy the current message to the clipboard"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+c",
	)
	def script_copyCurrentMessage(self, gesture):
		anchor = self._current_anchor()
		if anchor is None:
			ui.message(_("No messages on this surface"))
			return
		root = api.getForegroundObject()
		text = _collect_message_text(anchor, _collect_anchors(root)) if root else (anchor.name or "")
		if not text:
			ui.message(_("Nothing to copy"))
			return
		try:
			api.copyToClip(text)
			# Translators: spoken after a message has been copied.
			ui.message(_("Message copied"))
		except Exception as exc:
			log.debug(f"NVDAClaude: copyToClip failed: {exc}")
			ui.message(_("Could not copy message"))
