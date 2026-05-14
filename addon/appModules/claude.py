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

import time
from dataclasses import dataclass
from typing import Any, Iterator, List, Optional, Tuple

import api
import appModuleHandler
import controlTypes
import speech
import textInfos
import tones
import ui
from logHandler import log
from NVDAObjects import NVDAObject
from scriptHandler import script

# UIA is required for Chromium / Electron apps — NVDA's NVDAObject
# firstChild/next traversal only sees the outer HWND skeleton for those.
# UIAHandler is always present at runtime; the try/except is purely to
# keep the linter happy when the file is read outside NVDA.
try:
	import UIAHandler  # type: ignore[import-not-found]
	from NVDAObjects.UIA import UIA as UIANVDAObject  # type: ignore[import-not-found]
	_UIA_AVAILABLE = True
except Exception:
	UIAHandler = None  # type: ignore[assignment]
	UIANVDAObject = None  # type: ignore[assignment]
	_UIA_AVAILABLE = False

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

# How deep we recurse. Claude's chat DOM is heavily nested (Hauptbereich
# already sits ~14 levels under the top-level window, message rows another
# ~14 below that), so be generous.
MAX_WALK_DEPTH = 50

# UIA Control Type IDs we care about. Mirrors the dumpUIA mapping.
_UIA_BUTTON = 50000
_UIA_HYPERLINK = 50005
_UIA_LISTITEM = 50007
_UIA_TEXT = 50020
_UIA_GROUP = 50026
_UIA_DOCUMENT = 50030
_UIA_PANE = 50033
_UIA_EDIT = 50004


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class _Turn:
	"""One conversational turn on either surface.

	We store the raw IUIAutomationElement, not an NVDAObject — wrapping
	Chromium DOM elements as NVDA UIA NVDAObjects fails with E_INVALIDARG
	on Claude desktop, so we stay on the UIA layer and operate directly.

	``message_text`` is precomputed during collection (single tree walk),
	so navigating is free of further COM roundtrips.
	"""

	speaker: str  # "user" or "assistant"
	nav_elem: Any  # raw IUIAutomationElement we want to land on
	start_top: int  # vertical top of nav_elem
	end_top: int  # vertical top of the next turn's nav_elem or +∞
	message_text: str = ""


# --------------------------------------------------------------------------
# UIA-direct helpers
# --------------------------------------------------------------------------
# NVDA's NVDAObject child traversal does not penetrate Electron/Chromium
# windows beyond the outer HWND scaffolding (firstChild yields a single
# UNKNOWN element and stops). We therefore walk the raw UIA tree directly
# via the IUIAutomation interface NVDA already holds open — same approach
# as the sibling `dumpUIA` tool.


def _uia_walker():
	"""Return the IUIAutomationTreeWalker (raw view) or None."""
	if not _UIA_AVAILABLE:
		return None
	try:
		return UIAHandler.handler.clientObject.RawViewWalker
	except Exception as exc:
		log.debug(f"NVDAClaude: RawViewWalker unavailable: {exc}")
		return None


def _uia_element_from_window(nvda_root: NVDAObject):
	"""Return the IUIAutomationElement for the foreground window."""
	if not _UIA_AVAILABLE:
		return None
	hwnd = getattr(nvda_root, "windowHandle", None) or getattr(nvda_root, "hwnd", None)
	if not hwnd:
		return None
	try:
		return UIAHandler.handler.clientObject.ElementFromHandle(hwnd)
	except Exception as exc:
		log.debug(f"NVDAClaude: ElementFromHandle({hwnd}) failed: {exc}")
		return None


def _uia_name(elem) -> str:
	try:
		return elem.CurrentName or ""
	except Exception:
		return ""


def _uia_control_type(elem) -> int:
	try:
		return int(elem.CurrentControlType)
	except Exception:
		return 0


def _uia_class_name(elem) -> str:
	try:
		return elem.CurrentClassName or ""
	except Exception:
		return ""


def _uia_top(elem) -> Optional[int]:
	try:
		r = elem.CurrentBoundingRectangle
		return int(r.top)
	except Exception:
		return None


def _uia_size(elem) -> Tuple[int, int]:
	"""Return (width, height) of the element, or (0, 0)."""
	try:
		r = elem.CurrentBoundingRectangle
		return int(r.right - r.left), int(r.bottom - r.top)
	except Exception:
		return 0, 0


def _walk_uia_descendants(root_elem, max_depth: int = MAX_WALK_DEPTH) -> Iterator[Any]:
	"""Yield every descendant of ``root_elem`` (a raw UIA element) in
	document order, using the raw view walker.
	"""
	walker = _uia_walker()
	if walker is None or root_elem is None or max_depth < 0:
		return
	try:
		child = walker.GetFirstChildElement(root_elem)
	except Exception:
		return
	while child is not None:
		yield child
		yield from _walk_uia_descendants(child, max_depth - 1)
		try:
			child = walker.GetNextSiblingElement(child)
		except Exception:
			break


def _name_starts_with_uia(elem, prefixes: Tuple[str, ...]) -> bool:
	name = _uia_name(elem)
	return any(name.startswith(p) for p in prefixes)


def _find_main_area_uia(root_elem):
	"""Locate the main chat region (``<main>``) by name + Group control type."""
	for elem in _walk_uia_descendants(root_elem, max_depth=30):
		try:
			if _uia_control_type(elem) == _UIA_GROUP and _uia_name(elem) in MAIN_AREA_NAMES:
				return elem
		except Exception:
			continue
	return None


def _nvda_obj_top(obj) -> Optional[int]:
	"""Best-effort top coordinate for an NVDAObject (used for the focus
	reference point, which originates from NVDA, not from our UIA walk).
	"""
	try:
		loc = getattr(obj, "location", None)
		if loc is None:
			return None
		return int(loc.top)
	except Exception:
		return None


# UIA pattern ID for scrolling an item into view. Same numeric value across
# Windows versions — see Microsoft docs.
_UIA_SCROLL_ITEM_PATTERN_ID = 10000


def _try_scroll_into_view(elem) -> None:
	"""Best-effort scroll the element into view via ScrollItemPattern."""
	if elem is None:
		return
	try:
		ptr = elem.GetCurrentPattern(_UIA_SCROLL_ITEM_PATTERN_ID)
	except Exception:
		return
	if not ptr:
		return
	try:
		from comtypes.gen.UIAutomationClient import IUIAutomationScrollItemPattern
		sp = ptr.QueryInterface(IUIAutomationScrollItemPattern)
		sp.ScrollIntoView()
	except Exception as exc:
		log.debug(f"NVDAClaude: ScrollIntoView via UIA pattern failed: {exc!r}")


def _try_set_focus(elem) -> bool:
	"""Best-effort: ask UIA to move keyboard focus to this element. Returns
	True on success.
	"""
	if elem is None:
		return False
	try:
		elem.SetFocus()
		return True
	except Exception:
		return False


# --------------------------------------------------------------------------
# Chat surface collector
# --------------------------------------------------------------------------


_CONTENT_CONTROL_TYPES = (
	_UIA_TEXT, _UIA_HYPERLINK, _UIA_BUTTON, _UIA_LISTITEM,
)

_FOOTER_BUTTONS = (
	"Nachricht kopieren", "Copy message",
	"Als Kapitel anheften", "Pin as chapter",
	"Von hier forken", "Fork from here",
	# Cowork: per-message footer is a single localized "Copy" button.
	"Copy", "Kopieren",
)

# Cowork: visible "Copy" button name (the localized button at the end of
# every user message). Used to detect where a user message ends so the
# subsequent content can be attributed to Claude.
_COWORK_COPY_BUTTONS = ("Copy", "Kopieren")


# Each flat entry: (elem, top, control_type, name, width, height).
_FlatEntry = Tuple[Any, int, int, str, int, int]


def _scan_uia(root: NVDAObject) -> Tuple[Optional[Any], List[_FlatEntry]]:
	"""Walk the chat area once and return (main_element, flat_list).

	The flat list is sorted by ``top`` and only contains positioned
	elements whose control type might be useful — we keep the union of
	chat anchors, code terminators, and message content. This single walk
	is the only expensive operation per gesture; the surface collectors
	below run in pure Python over the resulting list.
	"""
	root_elem = _uia_element_from_window(root)
	if root_elem is None:
		return None, []
	main = _find_main_area_uia(root_elem) or root_elem
	flat: List[_FlatEntry] = []
	for elem in _walk_uia_descendants(main):
		ct = _uia_control_type(elem)
		# Keep only roles that could be either an anchor or message content.
		if ct not in (_UIA_TEXT, _UIA_HYPERLINK, _UIA_BUTTON, _UIA_LISTITEM):
			continue
		try:
			r = elem.CurrentBoundingRectangle
			top = int(r.top)
			width = int(r.right - r.left)
			height = int(r.bottom - r.top)
		except Exception:
			continue
		try:
			name = elem.CurrentName or ""
		except Exception:
			name = ""
		flat.append((elem, top, ct, name, width, height))
	flat.sort(key=lambda x: x[1])
	return main, flat


def _build_message_text(flat: List[_FlatEntry], start_top: int, end_top: int) -> str:
	"""Concatenate the rendered text of a turn from a precomputed flat list.

	Adjacent duplicates are suppressed — Cowork wraps tool buttons in
	sr-only StatusBars that re-emit the same text inside, which would
	otherwise produce annoying back-to-back repetitions.
	"""
	parts: List[str] = []
	for _elem, top, ct, name, width, height in flat:
		if top < start_top or top >= end_top:
			continue
		if ct not in _CONTENT_CONTROL_TYPES:
			continue
		# Skip 1×1 sr-only fillers (already announced as the chat anchor).
		if width <= 1 and height <= 1:
			continue
		# Skip per-message footer buttons.
		if ct == _UIA_BUTTON and name in _FOOTER_BUTTONS:
			continue
		s = name.strip()
		if not s:
			continue
		if parts and parts[-1] == s:
			# Duplicate of the previous part — skip.
			continue
		parts.append(s)
	return "\n".join(parts)


def _collect_chat_turns_from_flat(flat: List[_FlatEntry]) -> List[_Turn]:
	"""Chat surface: per-turn sr-only Text anchors for BOTH speakers.

	Returns an empty list if the assistant anchor is missing — that's the
	Cowork surface (chat-style user anchors only) and the next collector
	will handle it.
	"""
	user_candidates: List[Tuple[Any, int]] = []
	assistant_candidates: List[Tuple[Any, int]] = []
	for elem, top, ct, name, _w, _h in flat:
		if ct != _UIA_TEXT:
			continue
		if any(name.startswith(p) for p in CHAT_USER_PREFIXES):
			user_candidates.append((elem, top))
		elif any(name.startswith(p) for p in CHAT_ASSISTANT_PREFIXES):
			assistant_candidates.append((elem, top))
	# Cowork has user anchors but no assistant anchors — defer to the
	# Cowork collector in that case.
	if not assistant_candidates:
		return []
	candidates = (
		[(e, t, "user") for e, t in user_candidates]
		+ [(e, t, "assistant") for e, t in assistant_candidates]
	)
	candidates.sort(key=lambda c: c[1])
	turns: List[_Turn] = []
	for i, (elem, t, speaker) in enumerate(candidates):
		end_top = candidates[i + 1][1] if i + 1 < len(candidates) else 10**9
		text = _build_message_text(flat, t, end_top)
		turns.append(_Turn(
			speaker=speaker, nav_elem=elem,
			start_top=t, end_top=end_top, message_text=text,
		))
	return turns


def _collect_cowork_turns_from_flat(flat: List[_FlatEntry]) -> List[_Turn]:
	"""Cowork surface: chat-style user sr-only anchors only; Claude responses
	are synthesized as the gap between consecutive user turns.

	The structure is:

	    sr-only Text "Du hast gesagt: …"   ← user anchor (1×1 px)
	    Text (visible user message body)
	    Button "Copy"                       ← end-of-user-message marker
	    [tool buttons, status texts, prose] ← Claude's response
	    sr-only Text "Du hast gesagt: …"   ← next user turn
	    ...
	"""
	# 1. User anchors: chat-style sr-only Text starting with USER_PREFIXES.
	user_anchors: List[Tuple[Any, int]] = []
	for elem, top, ct, name, w, h in flat:
		if ct != _UIA_TEXT:
			continue
		if w > 1 or h > 1:
			continue  # Real user message text — keep only the 1×1 sr-only anchor.
		if any(name.startswith(p) for p in CHAT_USER_PREFIXES):
			user_anchors.append((elem, top))
	if not user_anchors:
		return []
	user_anchors.sort(key=lambda x: x[1])

	# 2. Copy buttons (in the Message-actions group right after each user
	#    message body). They give us a tighter end-of-user marker than just
	#    "next user anchor".
	copy_tops: List[int] = []
	for _elem, top, ct, name, _w, _h in flat:
		if ct == _UIA_BUTTON and name in _COWORK_COPY_BUTTONS:
			copy_tops.append(top)
	copy_tops.sort()

	turns: List[_Turn] = []
	for i, (user_elem, user_top) in enumerate(user_anchors):
		next_user_top = user_anchors[i + 1][1] if i + 1 < len(user_anchors) else 10**9
		# End of the user message = first Copy button after the anchor +
		# a few px to clear the button itself.
		user_end_top = next_user_top
		for cb_top in copy_tops:
			if cb_top > user_top:
				user_end_top = cb_top + 35
				break
		# USER turn.
		user_text = _build_message_text(flat, user_top, user_end_top)
		turns.append(_Turn(
			speaker="user", nav_elem=user_elem,
			start_top=user_top, end_top=user_end_top,
			message_text=user_text,
		))
		# ASSISTANT turn (synthesized) — only if there's content in the gap.
		if next_user_top - user_end_top < 5:
			continue
		asst_nav = None
		asst_top = user_end_top
		for elem, top, ct, name, w, h in flat:
			if top <= user_end_top:
				continue
			if top >= next_user_top:
				break
			if w <= 1 and h <= 1:
				continue
			if ct not in _CONTENT_CONTROL_TYPES:
				continue
			if ct == _UIA_BUTTON and name in _FOOTER_BUTTONS:
				continue
			asst_nav = elem
			asst_top = top
			break
		if asst_nav is None:
			continue
		asst_text = _build_message_text(flat, user_end_top, next_user_top)
		if not asst_text.strip():
			continue
		turns.append(_Turn(
			speaker="assistant", nav_elem=asst_nav,
			start_top=asst_top, end_top=next_user_top,
			message_text=asst_text,
		))
	return turns


def _collect_chat_turns(root: NVDAObject) -> List[_Turn]:
	"""Convenience wrapper; production code goes through ``_collect_turns``."""
	_main, flat = _scan_uia(root)
	if not flat:
		return []
	return _collect_chat_turns_from_flat(flat)


def _collect_cowork_turns(root: NVDAObject) -> List[_Turn]:
	"""Convenience wrapper; production code goes through ``_collect_turns``."""
	_main, flat = _scan_uia(root)
	if not flat:
		return []
	return _collect_cowork_turns_from_flat(flat)


# --------------------------------------------------------------------------
# Code surface collector
# --------------------------------------------------------------------------


_CODE_NAV_ROLES = (_UIA_TEXT, _UIA_HYPERLINK, _UIA_BUTTON, _UIA_LISTITEM)
_CODE_COPY_BUTTONS = ("Nachricht kopieren", "Copy message")


def _collect_code_turns_from_flat(flat: List[_FlatEntry]) -> List[_Turn]:
	# 1. Index of terminators in `flat`, with speaker.
	terminators: List[Tuple[int, str]] = []
	for i, (_elem, _t, ct, name, _w, _h) in enumerate(flat):
		if ct != _UIA_BUTTON:
			continue
		if name in CODE_USER_TERMINATORS:
			terminators.append((i, "user"))
		elif name in CODE_ASSISTANT_TERMINATORS:
			terminators.append((i, "assistant"))
	if not terminators:
		return []

	# 2. For each terminator, the turn extends from (previous terminator's
	#    flat-index + 1) up to this terminator's flat-index. The navigation
	#    anchor is the first content element in that range.
	raw_turns: List[Tuple[str, Any, int, int]] = []  # (speaker, nav_elem, nav_top, term_top)
	prev_end_flat_idx = -1
	for tidx, speaker in terminators:
		start_flat = prev_end_flat_idx + 1
		end_flat = tidx
		nav_elem = None
		nav_top = flat[tidx][1]
		for j in range(start_flat, end_flat):
			elem, top, ct, name, _w, _h = flat[j]
			if ct == _UIA_BUTTON and name in _CODE_COPY_BUTTONS:
				continue
			if ct in _CODE_NAV_ROLES:
				nav_elem = elem
				nav_top = top
				break
		if nav_elem is None:
			nav_elem = flat[tidx][0]
		raw_turns.append((speaker, nav_elem, nav_top, flat[tidx][1]))
		prev_end_flat_idx = tidx

	# 3. Determine each turn's end_top as the next turn's nav_top, then
	#    precompute message_text for all turns in one pass.
	turns: List[_Turn] = []
	for i, (speaker, nav_elem, nav_top, _term_top) in enumerate(raw_turns):
		end_top = raw_turns[i + 1][2] if i + 1 < len(raw_turns) else 10**9
		text = _build_message_text(flat, nav_top, end_top)
		turns.append(_Turn(
			speaker=speaker, nav_elem=nav_elem,
			start_top=nav_top, end_top=end_top, message_text=text,
		))
	return turns


def _collect_code_turns(root: NVDAObject) -> List[_Turn]:
	_main, flat = _scan_uia(root)
	if not flat:
		log.info("NVDAClaude.code: empty scan")
		return []
	turns = _collect_code_turns_from_flat(flat)
	log.info(f"NVDAClaude.code: scanned, {len(turns)} turn(s)")
	return turns


# --------------------------------------------------------------------------
# Surface-agnostic API
# --------------------------------------------------------------------------


def _collect_turns(root: NVDAObject) -> List[_Turn]:
	"""Auto-detect surface and return its turn list. Empty list if no
	surface has identifiable turns. Performs a single UIA tree walk and
	tries chat → cowork → code in turn.
	"""
	_main, flat = _scan_uia(root)
	if not flat:
		log.info("NVDAClaude: empty UIA scan")
		return []
	# 1. Chat surface — both user and assistant sr-only anchors present.
	turns = _collect_chat_turns_from_flat(flat)
	if turns:
		log.info(f"NVDAClaude: chat surface, {len(turns)} turn(s)")
		return turns
	# 2. Cowork surface — chat-style user anchors only; synthesize asst.
	turns = _collect_cowork_turns_from_flat(flat)
	if turns:
		log.info(f"NVDAClaude: cowork surface, {len(turns)} turn(s)")
		return turns
	# 3. Code surface — per-turn terminator buttons.
	turns = _collect_code_turns_from_flat(flat)
	if turns:
		log.info(f"NVDAClaude: code surface, {len(turns)} turn(s)")
		return turns
	log.info("NVDAClaude: no turns on any surface")
	return []


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
			rects = getattr(ti, "boundingRects", None)
			if rects:
				try:
					ref_top = int(rects[0].top)
				except Exception:
					ref_top = None
	except Exception:
		ref_top = None
	if ref_top is None:
		focus = api.getFocusObject()
		ref_top = _nvda_obj_top(focus) if focus is not None else None
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


def _speaker_label(speaker: str) -> str:
	if speaker == "user":
		# Translators: announced before user messages during navigation.
		return _("You: ")
	# Translators: announced before assistant messages during navigation.
	return _("Claude: ")


def _move_to_turn(turn: _Turn, root: NVDAObject) -> None:
	"""Land on a turn: scroll into view (best effort) and announce speaker
	label + the precomputed message content.
	"""
	try:
		_try_scroll_into_view(turn.nav_elem)
	except Exception:
		pass
	text = turn.message_text or _uia_name(turn.nav_elem) or ""
	to_say = _speaker_label(turn.speaker) + text
	log.info(f"NVDAClaude._move_to_turn: speaker={turn.speaker} chars={len(text)}")
	try:
		ui.message(to_say)
	except Exception:
		try:
			speech.speakText(to_say)
		except Exception as exc:
			log.info(f"NVDAClaude._move_to_turn: both speech paths failed: {exc!r}")


# --------------------------------------------------------------------------
# App module
# --------------------------------------------------------------------------


class AppModule(appModuleHandler.AppModule):

	# Remembered "current navigation position" — the start_top of the turn
	# we most recently announced. Because we don't actually move NVDA's
	# focus or review cursor when navigating (the turn anchors are 1×1
	# sr-only elements that don't accept focus), we keep this in the
	# AppModule so successive J/K presses advance through the conversation
	# instead of recomputing position from the (unchanged) focus location.
	_last_nav_top: Optional[int] = None

	# Short-lived cache of the turn list. Walking the UIA tree for every
	# gesture is expensive (~1 s on a long Code conversation), so we keep
	# the previous result around for a few hundred ms.
	_cache_hwnd: Optional[int] = None
	_cache_time: float = 0.0
	_cache_turns: Optional[List[_Turn]] = None
	_CACHE_TTL_SEC: float = 1.5

	def _get_turns_cached(self, root: NVDAObject) -> List[_Turn]:
		hwnd = getattr(root, "windowHandle", None) or 0
		now = time.monotonic()
		if (
			self._cache_hwnd == hwnd
			and self._cache_turns
			and (now - self._cache_time) < self._CACHE_TTL_SEC
		):
			return self._cache_turns
		turns = _collect_turns(root)
		# If the chat has *grown* since the last scan (Claude produced a new
		# response, or the user sent a new message), reset the remembered
		# navigation position so the next gesture jumps to the new latest
		# message instead of continuing from a stale offset.
		if self._cache_turns is not None and len(turns) > len(self._cache_turns):
			log.info(
				f"NVDAClaude: chat grew {len(self._cache_turns)} -> {len(turns)}, "
				f"resetting nav position"
			)
			self._last_nav_top = None
		self._cache_hwnd = hwnd
		self._cache_time = now
		self._cache_turns = turns
		return turns

	def _invalidate_cache(self) -> None:
		self._cache_turns = None
		self._cache_time = 0.0

	def _navigate(self, kind: str, direction: int) -> None:
		"""``kind`` ∈ {"all","user","assistant"}, ``direction`` ∈ {+1,-1}."""
		root = api.getForegroundObject()
		if root is None:
			log.info("NVDAClaude._navigate: no foreground object")
			ui.message(_("Claude window not found"))
			return
		all_turns = self._get_turns_cached(root)
		filtered = _filter_turns(all_turns, kind)
		if not filtered:
			log.info(f"NVDAClaude._navigate: no turns (kind={kind})")
			ui.message(_("No messages on this surface"))
			return
		# First-press behavior: if we haven't navigated yet (or the chat
		# just grew so the position was reset), always land on the latest
		# turn regardless of which arrow was pressed. The user expectation
		# is "show me what's new first."
		if self._last_nav_top is None:
			target = filtered[-1]
			log.info(
				f"NVDAClaude._navigate: first-press fallback to latest "
				f"turn (speaker={target.speaker} top={target.start_top})"
			)
			_move_to_turn(target, root)
			self._last_nav_top = target.start_top
			return
		cur_top = self._last_nav_top
		log.info(
			f"NVDAClaude._navigate: kind={kind} dir={direction} cur_top={cur_top} "
			f"turns={len(filtered)} tops={[t.start_top for t in filtered]}"
		)
		target: Optional[_Turn] = None
		if direction > 0:
			for t in filtered:
				if t.start_top > cur_top:
					target = t
					break
		else:
			for t in reversed(filtered):
				if t.start_top < cur_top:
					target = t
					break
		if target is None:
			# End of conversation reached.
			log.info("NVDAClaude._navigate: end of conversation reached")
			try:
				tones.beep(400, 80)
			except Exception:
				pass
			ui.message(_("No more messages"))
			return
		log.info(f"NVDAClaude._navigate: target speaker={target.speaker} top={target.start_top}")
		_move_to_turn(target, root)
		self._last_nav_top = target.start_top

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
		turns = self._get_turns_cached(root)
		if not turns:
			ui.message(_("No messages on this surface"))
			return
		_move_to_turn(turns[0], root)
		self._last_nav_top = turns[0].start_top

	@script(
		description=_("Move to the last message in the chat"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+b",
	)
	def script_lastMessage(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		turns = self._get_turns_cached(root)
		if not turns:
			ui.message(_("No messages on this surface"))
			return
		_move_to_turn(turns[-1], root)
		self._last_nav_top = turns[-1].start_top

	@script(
		description=_("Move focus to the Claude chat input field"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+i",
	)
	def script_focusInput(self, gesture):
		root = api.getForegroundObject()
		if root is None:
			return
		root_elem = _uia_element_from_window(root)
		if root_elem is None:
			ui.message(_("Input field not found"))
			return
		main = _find_main_area_uia(root_elem) or root_elem
		# The composer is the bottom-most editable element in the main
		# region.
		best = None
		best_top = -10**9
		for elem in _walk_uia_descendants(main):
			if _uia_control_type(elem) not in (_UIA_EDIT, _UIA_DOCUMENT):
				continue
			t = _uia_top(elem)
			if t is None:
				continue
			if t > best_top:
				best_top = t
				best = elem
		if best is None:
			ui.message(_("Input field not found"))
			return
		_try_scroll_into_view(best)
		# Reset remembered navigation position — after the user has moved
		# focus to the composer, a subsequent "previous" should start from
		# the bottom of the conversation again.
		self._last_nav_top = None
		if not _try_set_focus(best):
			# Translators: spoken when the input field can't take focus.
			ui.message(_("Input field not focusable"))

	# ----- read / copy current message -----

	def _current_turn(self) -> Optional[Tuple[_Turn, NVDAObject]]:
		root = api.getForegroundObject()
		if root is None:
			return None
		turns = self._get_turns_cached(root)
		if not turns:
			return None
		# Prefer the remembered navigation position (the last turn we
		# announced). If the user hasn't navigated yet, fall back to the
		# review/focus location.
		cur_top = self._last_nav_top
		if cur_top is None:
			cur_top = _current_turn_top(turns)
		if cur_top is None:
			return turns[-1], root
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
		turn, _root = cur
		text = turn.message_text or _uia_name(turn.nav_elem) or ""
		ui.message(_speaker_label(turn.speaker) + text)

	# ----- diagnostics -----

	@script(
		description=_("Dump diagnostic info about the Claude UI to nvda.log"),
		category=_("Claude"),
		gesture="kb:NVDA+alt+d",
	)
	def script_diagnoseDump(self, gesture):
		"""Walk the foreground UI via UIA and log what we see."""
		root = api.getForegroundObject()
		log.info("NVDAClaude: ===== diagnose dump start =====")
		if root is None:
			log.info("NVDAClaude: foreground object is None")
			ui.message(_("Diagnostic dump written to log"))
			return
		try:
			log.info(
				f"NVDAClaude: foreground: name={root.name!r} "
				f"className={getattr(root, 'windowClassName', '?')!r} "
				f"hwnd={getattr(root, 'windowHandle', '?')!r}"
			)
		except Exception as exc:
			log.info(f"NVDAClaude: failed to read foreground props: {exc}")
		log.info(f"NVDAClaude: UIA available={_UIA_AVAILABLE}")
		root_elem = _uia_element_from_window(root)
		log.info(f"NVDAClaude: UIA root element = {root_elem!r}")
		if root_elem is None:
			log.info("NVDAClaude: cannot get UIA root — aborting")
			ui.message(_("Diagnostic dump written to log"))
			return

		# Walk via UIA.
		count = 0
		ct_counts: dict = {}
		main_hits: List[str] = []
		chat_user_hits: List[str] = []
		chat_asst_hits: List[str] = []
		code_user_hits: List[str] = []
		code_asst_hits: List[str] = []
		other_buttons_sample: List[str] = []
		max_log = 8000
		try:
			for elem in _walk_uia_descendants(root_elem, max_depth=30):
				count += 1
				if count > max_log:
					log.info(f"NVDAClaude: stopped walk at {max_log} elements (capped)")
					break
				ct = _uia_control_type(elem)
				name = _uia_name(elem)
				ct_counts[ct] = ct_counts.get(ct, 0) + 1
				if ct == _UIA_GROUP and name in MAIN_AREA_NAMES:
					main_hits.append(name)
				if _name_starts_with_uia(elem, CHAT_USER_PREFIXES):
					chat_user_hits.append(name[:80])
				if _name_starts_with_uia(elem, CHAT_ASSISTANT_PREFIXES):
					chat_asst_hits.append(name[:80])
				if ct == _UIA_BUTTON:
					if name in CODE_USER_TERMINATORS:
						code_user_hits.append(name)
					elif name in CODE_ASSISTANT_TERMINATORS:
						code_asst_hits.append(name)
					elif name and len(other_buttons_sample) < 30:
						other_buttons_sample.append(name[:60])
		except Exception as exc:
			log.info(f"NVDAClaude: walk crashed at element #{count}: {exc!r}")

		log.info(f"NVDAClaude: walked {count} elements")
		log.info(f"NVDAClaude: control-type counts: {ct_counts}")
		log.info(f"NVDAClaude: main-area matches: {main_hits}")
		log.info(f"NVDAClaude: chat USER anchor matches ({len(chat_user_hits)}): {chat_user_hits[:5]}")
		log.info(f"NVDAClaude: chat ASST anchor matches ({len(chat_asst_hits)}): {chat_asst_hits[:5]}")
		log.info(f"NVDAClaude: code USER terminators ({len(code_user_hits)}): {code_user_hits[:5]}")
		log.info(f"NVDAClaude: code ASST terminators ({len(code_asst_hits)}): {code_asst_hits[:5]}")
		log.info(f"NVDAClaude: sample of other button names: {other_buttons_sample}")

		try:
			chat_turns = _collect_chat_turns(root)
			log.info(f"NVDAClaude: _collect_chat_turns -> {len(chat_turns)} turns")
		except Exception as exc:
			log.info(f"NVDAClaude: _collect_chat_turns crashed: {exc!r}")
		try:
			cowork_turns = _collect_cowork_turns(root)
			log.info(f"NVDAClaude: _collect_cowork_turns -> {len(cowork_turns)} turns")
		except Exception as exc:
			log.info(f"NVDAClaude: _collect_cowork_turns crashed: {exc!r}")
		try:
			code_turns = _collect_code_turns(root)
			log.info(f"NVDAClaude: _collect_code_turns -> {len(code_turns)} turns")
		except Exception as exc:
			log.info(f"NVDAClaude: _collect_code_turns crashed: {exc!r}")

		log.info("NVDAClaude: ===== diagnose dump end =====")
		# Translators: spoken after the diagnostic dump.
		ui.message(_("Diagnostic dump written to log"))

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
		turn, _root = cur
		text = turn.message_text
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
