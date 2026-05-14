# NVDAClaude — App module for the Anthropic Claude desktop client (claude.exe).
# Copyright (C) 2026 Stefan Lohmaier <stefan@slohmaier.de>
# Licensed under the GNU General Public License v2.
#
# Provides keyboard navigation between messages on multiple surfaces:
#   - Chat: uses screen-reader-only turn anchors that Anthropic already ships
#     in the Chromium DOM ("You said: …" / "Claude said: …" and localized
#     counterparts).
#   - Code: uses the per-message terminator buttons ("Von hier forken" =
#     end of a user message, "Als Kapitel anheften" = end of a Claude
#     response) plus the preceding "Nachricht kopieren" button.
#   - Cowork: not yet implemented; gestures no-op there.
#
# Surface is auto-detected per gesture: if chat anchors exist they take
# precedence, otherwise we try the code surface.

from __future__ import annotations

from dataclasses import dataclass
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
# Chat surface — sr-only turn anchors
# --------------------------------------------------------------------------

CHAT_USER_PREFIXES: Tuple[str, ...] = (
	"Du hast gesagt:",   # de
	"You said:",         # en
)

CHAT_ASSISTANT_PREFIXES: Tuple[str, ...] = (
	"Claude hat geantwortet:",  # de
	"Claude said:",             # en (older)
	"Claude responded:",        # en (newer)
)

CHAT_ALL_PREFIXES: Tuple[str, ...] = CHAT_USER_PREFIXES + CHAT_ASSISTANT_PREFIXES


# --------------------------------------------------------------------------
# Code surface — per-turn terminator buttons
# --------------------------------------------------------------------------
# Each turn ends with a "Nachricht kopieren" button followed by a
# speaker-specific button. The speaker-specific one tells us who the
# message belongs to.

CODE_USER_TERMINATORS: Tuple[str, ...] = (
	"Von hier forken",
	"Fork from here",
)

CODE_ASSISTANT_TERMINATORS: Tuple[str, ...] = (
	"Als Kapitel anheften",
	"Pin as chapter",
)

CODE_ALL_TERMINATORS: Tuple[str, ...] = CODE_USER_TERMINATORS + CODE_ASSISTANT_TERMINATORS

# Activity summary buttons (e.g. "Ausgeführt 13 Befehle, …") that Claude
# prepends to its responses on the Code surface. We treat them as part of
# the turn content for "read full message", but we don't navigate onto
# them — the natural landing spot is the first prose text.
CODE_ACTIVITY_PREFIXES: Tuple[str, ...] = (
	"Ausgeführt ",     # de
	"Ran ",            # en
	"Performed ",      # en (some variants)
)


# --------------------------------------------------------------------------
# General
# --------------------------------------------------------------------------

# Localized names of the main chat container <main role="main">. Used to
# scope the descendant walk so we don't recurse into the sidebar.
MAIN_AREA_NAMES: Tuple[str, ...] = (
	"Hauptbereich",  # de
	"Main area",     # en
	"Main",          # en fallback
)

# How deep we recurse below the main area.
MAX_WALK_DEPTH = 25


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class _Turn:
	"""One conversational turn on either surface."""

	speaker: str  # "user" or "assistant"
	nav_obj: NVDAObject  # element to land on when navigating to this turn
	start_top: int  # vertical top of nav_obj
	end_top: int  # vertical top of the next turn's nav_obj or +∞


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _safe_attr(obj: NVDAObject, name: str, default=None):
	try:
		return getattr(obj, name, default)
	except Exception:
		return default


def _top(obj: NVDAObject) -> Optional[int]:
	loc = _safe_attr(obj, "location")
	if loc is None:
		return None
	try:
		return int(loc.top)
	except Exception:
		return None


def _walk_descendants(obj: NVDAObject, max_depth: int = MAX_WALK_DEPTH) -> Iterator[NVDAObject]:
	"""Yield every descendant of ``obj`` in document order.

	Uses ``firstChild`` / ``next`` so it works for both UIA and IA2 backends.
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
	"""Locate the main chat region (``<main>``) inside the Claude window."""
	for obj in _walk_descendants(root, max_depth=15):
		try:
			if obj.role == controlTypes.Role.GROUP and obj.name in MAIN_AREA_NAMES:
				return obj
		except Exception:
			continue
	return None


# --------------------------------------------------------------------------
# Chat surface collector
# --------------------------------------------------------------------------


def _collect_chat_turns(root: NVDAObject) -> List[_Turn]:
	main = _find_main_area(root) or root
	candidates: List[Tuple[NVDAObject, int, str]] = []
	for obj in _walk_descendants(main):
		try:
			if obj.role != controlTypes.Role.STATICTEXT:
				continue
		except Exception:
			continue
		t = _top(obj)
		if t is None:
			continue
		if _name_starts_with(obj, CHAT_USER_PREFIXES):
			candidates.append((obj, t, "user"))
		elif _name_starts_with(obj, CHAT_ASSISTANT_PREFIXES):
			candidates.append((obj, t, "assistant"))
	candidates.sort(key=lambda c: c[1])
	turns: List[_Turn] = []
	for i, (obj, t, speaker) in enumerate(candidates):
		end_top = candidates[i + 1][1] if i + 1 < len(candidates) else 10**9
		turns.append(_Turn(speaker=speaker, nav_obj=obj, start_top=t, end_top=end_top))
	return turns


# --------------------------------------------------------------------------
# Code surface collector
# --------------------------------------------------------------------------


def _collect_code_turns(root: NVDAObject) -> List[_Turn]:
	"""Identify turns on the Code surface by walking the main area, finding
	speaker-specific terminator buttons, and pairing each with the first
	content element of that turn.
	"""
	main = _find_main_area(root) or root

	# 1. Linear list of children in document order, only those positioned
	#    (have a sensible top). We need both terminators and content.
	flat: List[Tuple[NVDAObject, int]] = []
	for obj in _walk_descendants(main):
		t = _top(obj)
		if t is None:
			continue
		flat.append((obj, t))
	flat.sort(key=lambda x: x[1])

	# 2. Index of terminators in `flat`, with speaker.
	terminators: List[Tuple[int, str]] = []  # (index_in_flat, speaker)
	for i, (obj, _t) in enumerate(flat):
		try:
			if obj.role != controlTypes.Role.BUTTON:
				continue
			name = obj.name or ""
		except Exception:
			continue
		if name in CODE_USER_TERMINATORS:
			terminators.append((i, "user"))
		elif name in CODE_ASSISTANT_TERMINATORS:
			terminators.append((i, "assistant"))

	if not terminators:
		return []

	# 3. For each terminator, the turn extends from (previous terminator's
	#    flat-index + 1) up to (this terminator's flat-index - 1, before
	#    "Nachricht kopieren"). The navigation anchor is the first element
	#    in that range whose role is meaningful for a screen reader user.
	turns: List[_Turn] = []
	prev_end_flat_idx = -1
	for tidx, speaker in terminators:
		start_flat = prev_end_flat_idx + 1
		end_flat = tidx
		# Pick the first content element in [start_flat, end_flat). Skip
		# the "Nachricht kopieren" button which always sits right before
		# the terminator.
		nav_obj: Optional[NVDAObject] = None
		for j in range(start_flat, end_flat):
			obj, _t2 = flat[j]
			try:
				role = obj.role
				name = obj.name or ""
			except Exception:
				continue
			if role == controlTypes.Role.BUTTON and name in (
				"Nachricht kopieren", "Copy message",
			):
				continue
			# Anything that has text content is fine as a landing spot.
			if role in (
				controlTypes.Role.STATICTEXT,
				controlTypes.Role.LINK,
				controlTypes.Role.BUTTON,  # e.g. activity summary
				controlTypes.Role.HEADING,
				controlTypes.Role.LIST,
				controlTypes.Role.LISTITEM,
			):
				nav_obj = obj
				break
		# Fallback: use the terminator itself if we couldn't find a body.
		if nav_obj is None:
			nav_obj = flat[tidx][0]
		nav_top = _top(nav_obj) or flat[tidx][1]
		turns.append(_Turn(
			speaker=speaker,
			nav_obj=nav_obj,
			start_top=nav_top,
			end_top=flat[tidx][1],  # tightened below
		))
		prev_end_flat_idx = tidx

	# 4. Patch end_top to be the *next* turn's start_top so "read full
	#    message" covers the right range. Without this, end_top sits at the
	#    terminator button which excludes nothing — the next turn's text
	#    would bleed into this one.
	for i in range(len(turns) - 1):
		turns[i].end_top = turns[i + 1].start_top
	if turns:
		turns[-1].end_top = 10**9
	return turns


# --------------------------------------------------------------------------
# Surface-agnostic API
# --------------------------------------------------------------------------


def _collect_turns(root: NVDAObject) -> List[_Turn]:
	"""Auto-detect surface and return its turn list. Empty list if neither
	surface has identifiable turns (e.g. Cowork, empty chat, sidebar focus).
	"""
	turns = _collect_chat_turns(root)
	if turns:
		return turns
	return _collect_code_turns(root)


def _filter_turns(turns: List[_Turn], kind: str) -> List[_Turn]:
	if kind == "user":
		return [t for t in turns if t.speaker == "user"]
	if kind == "assistant":
		return [t for t in turns if t.speaker == "assistant"]
	return turns


def _current_turn_top(turns: List[_Turn]) -> Optional[int]:
	"""Return the top coordinate of the turn the user is currently on."""
	if not turns:
		return None
	ref_top: Optional[int] = None
	try:
		ti = api.getReviewPosition()
		if ti is not None:
			rects = _safe_attr(ti, "boundingRects", None)
			if rects:
				try:
					ref_top = int(rects[0].top)
				except Exception:
					ref_top = None
	except Exception:
		ref_top = None
	if ref_top is None:
		focus = api.getFocusObject()
		ref_top = _top(focus) if focus is not None else None
	if ref_top is None:
		return None
	# Largest start_top that is <= ref_top.
	current = None
	for t in turns:
		if t.start_top <= ref_top:
			current = t.start_top
		else:
			break
	return current


def _move_to(obj: NVDAObject) -> None:
	"""Best-effort: scroll into view, move the review cursor, and speak."""
	try:
		obj.scrollIntoView()
	except Exception:
		pass
	try:
		ti = obj.makeTextInfo(textInfos.POSITION_FIRST)
		api.setReviewPosition(ti)
	except Exception as exc:
		log.debug(f"NVDAClaude: setReviewPosition failed: {exc}")
	try:
		speech.speakObject(obj, reason=controlTypes.OutputReason.FOCUS)
	except Exception:
		try:
			ui.message(obj.name or "")
		except Exception:
			pass


def _collect_message_text(turn: _Turn, root: NVDAObject) -> str:
	"""Concatenate the rendered text of one turn."""
	main = _find_main_area(root) or root
	parts: List[str] = []
	for obj in _walk_descendants(main):
		try:
			role = obj.role
		except Exception:
			continue
		if role not in (
			controlTypes.Role.STATICTEXT,
			controlTypes.Role.LINK,
			controlTypes.Role.BUTTON,
			controlTypes.Role.HEADING,
			controlTypes.Role.LISTITEM,
		):
			continue
		t = _top(obj)
		if t is None:
			continue
		if t < turn.start_top:
			continue
		if t >= turn.end_top:
			continue
		# Skip 1x1 sr-only fillers — their text was already part of the
		# anchor name on chat surface, or is irrelevant on code surface.
		loc = _safe_attr(obj, "location")
		try:
			if loc is not None and loc.width <= 1 and loc.height <= 1:
				continue
		except Exception:
			pass
		# Skip the per-message footer buttons on code surface.
		try:
			name = obj.name or ""
		except Exception:
			name = ""
		if role == controlTypes.Role.BUTTON and name in (
			"Nachricht kopieren", "Copy message",
			"Als Kapitel anheften", "Pin as chapter",
			"Von hier forken", "Fork from here",
		):
			continue
		name_s = name.strip()
		if name_s:
			parts.append(name_s)
	if not parts:
		# Fallback: at least the anchor name.
		try:
			return (turn.nav_obj.name or "").strip()
		except Exception:
			return ""
	return "\n".join(parts)


# --------------------------------------------------------------------------
# App module
# --------------------------------------------------------------------------


class AppModule(appModuleHandler.AppModule):

	def _navigate(self, kind: str, direction: int) -> None:
		"""``kind`` ∈ {"all","user","assistant"}, ``direction`` ∈ {+1,-1}."""
		root = api.getForegroundObject()
		if root is None:
			ui.message(_("Claude window not found"))
			return
		all_turns = _collect_turns(root)
		filtered = _filter_turns(all_turns, kind)
		if not filtered:
			ui.message(_("No messages on this surface"))
			return
		# Reference position from the *full* list so behaviour stays
		# intuitive when user/assistant filtering is active.
		cur_top = _current_turn_top(all_turns)
		target: Optional[_Turn] = None
		if direction > 0:
			ref = cur_top if cur_top is not None else -10**9
			for t in filtered:
				if t.start_top > ref:
					target = t
					break
		else:
			ref = cur_top if cur_top is not None else 10**9
			for t in reversed(filtered):
				if t.start_top < ref:
					target = t
					break
			# If the user is exactly on a turn and presses "previous", we
			# want the one above — handled by < ref. If they're between
			# turns, < ref still gives the previous one. Good.
		if target is None:
			ui.message(_("No more messages"))
			return
		_move_to(target.nav_obj)

	# ----- next/previous -----

	@script(
		# Translators: input help message.
		description=_("Move to the next message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+j",
	)
	def script_nextMessage(self, gesture):
		self._navigate("all", +1)

	@script(
		description=_("Move to the previous message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+k",
	)
	def script_previousMessage(self, gesture):
		self._navigate("all", -1)

	@script(
		description=_("Move to the next user message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+u",
	)
	def script_nextUserMessage(self, gesture):
		self._navigate("user", +1)

	@script(
		description=_("Move to the previous user message in the Claude chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+u",
	)
	def script_previousUserMessage(self, gesture):
		self._navigate("user", -1)

	@script(
		description=_("Move to the next Claude response"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+a",
	)
	def script_nextAssistantMessage(self, gesture):
		self._navigate("assistant", +1)

	@script(
		description=_("Move to the previous Claude response"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+a",
	)
	def script_previousAssistantMessage(self, gesture):
		self._navigate("assistant", -1)

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
		turns = _collect_turns(root)
		if not turns:
			ui.message(_("No messages on this surface"))
			return
		_move_to(turns[0].nav_obj)

	@script(
		description=_("Move to the last message in the chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+b",
	)
	def script_lastMessage(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		turns = _collect_turns(root)
		if not turns:
			ui.message(_("No messages on this surface"))
			return
		_move_to(turns[-1].nav_obj)

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
		# The composer is the bottom-most editable element in the main
		# region.
		best: Optional[NVDAObject] = None
		best_top = -10**9
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
			t = _top(obj)
			if t is None:
				continue
			if t > best_top:
				best_top = t
				best = obj
		if best is None:
			ui.message(_("Input field not found"))
			return
		try:
			best.setFocus()
		except Exception:
			_move_to(best)

	# ----- read / copy current message -----

	def _current_turn(self) -> Optional[Tuple[_Turn, NVDAObject]]:
		root = api.getForegroundObject()
		if root is None:
			return None
		turns = _collect_turns(root)
		if not turns:
			return None
		cur_top = _current_turn_top(turns)
		if cur_top is None:
			return turns[-1], root  # default to last
		# Find the turn whose start_top == cur_top.
		for t in turns:
			if t.start_top == cur_top:
				return t, root
		return turns[-1], root

	@script(
		description=_("Read the current message in full"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+c",
	)
	def script_readCurrentMessage(self, gesture):
		cur = self._current_turn()
		if cur is None:
			ui.message(_("No messages on this surface"))
			return
		turn, root = cur
		text = _collect_message_text(turn, root)
		if text:
			speech.speakText(text)
		else:
			speech.speakObject(turn.nav_obj, reason=controlTypes.OutputReason.FOCUS)

	@script(
		description=_("Copy the current message to the clipboard"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+shift+c",
	)
	def script_copyCurrentMessage(self, gesture):
		cur = self._current_turn()
		if cur is None:
			ui.message(_("No messages on this surface"))
			return
		turn, root = cur
		text = _collect_message_text(turn, root)
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
