# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

from site_scons.site_tools.NVDATool.typings import AddonInfo, BrailleTables, SymbolDictionaries

# Since some strings in `addon_info` are translatable,
# we need to include them in the .po files.
# Gettext recognizes only strings given as parameters to the `_` function.
# To avoid initializing translations in this module we simply import a "fake" `_` function
# which returns whatever is given to it as an argument.
from site_scons.site_tools.NVDATool.utils import _


# Add-on information variables
addon_info = AddonInfo(
	# add-on Name/identifier, internal for NVDA
	addon_name="NVDAClaude",
	# Add-on summary/title, usually the user visible name of the add-on
	# Translators: Summary/title for this add-on
	# to be shown on installation and add-on information found in add-on store
	addon_summary=_("Claude Accessibility"),
	# Add-on description
	# Translators: Long description to be shown for this add-on on add-on information from add-on store
	addon_description=_("""Makes the Anthropic Claude desktop client more accessible for screen reader users.
Adds keyboard shortcuts to jump between messages (next/previous, user-only, Claude-only),
to read the current message in full, and to copy it to the clipboard.
Works on all three surfaces — Chat, Code, and Cowork — auto-detected per gesture."""),
	# version
	addon_version="0.3.0",
	# Brief changelog for this version
	# Translators: what's new content for the add-on version to be shown in the add-on store
	addon_changelog=_("""Version 0.3.0: Adds support for the Cowork surface. Anthropic only ships the user turn anchor there (no "Claude responded" sr-only), so the add-on synthesizes Claude turns from the gap between consecutive user messages. Tool invocations ("Execute Shell Command", "MacMini-Integration used", etc.) are read as part of the response. First press of any navigation key now lands on the latest message; if Claude produces a new response between gestures, the next press snaps to that new latest. Internal pipeline rewritten to do a single UIA tree walk per gesture (~50% faster) and to cache the result for ~1.5 s for snappy successive presses.\n\nVersion 0.2.0: Adds support for the Code surface using the per-turn "Fork from here" / "Pin as chapter" buttons.\n\nVersion 0.1.0: Initial release. Keyboard navigation between chat messages."""),
	# Author(s)
	addon_author="Stefan Lohmaier <stefan@slohmaier.de>",
	# URL for the add-on documentation support
	addon_url="https://github.com/slohmaier/NVDAClaude",
	# URL for the add-on repository where the source code can be found
	addon_sourceURL="https://github.com/slohmaier/NVDAClaude",
	# Documentation file name
	addon_docFileName="readme.html",
	# Minimum NVDA version supported (e.g. "2019.3.0", minor version is optional)
	addon_minimumNVDAVersion="2024.1",
	# Last NVDA version supported/tested (e.g. "2024.4.0", ideally more recent than minimum version)
	addon_lastTestedNVDAVersion="2026.1",
	# Add-on update channel (default is None, denoting stable releases,
	# and for development releases, use "dev".)
	# Do not change unless you know what you are doing!
	addon_updateChannel=None,
	# Add-on license such as GPL 2
	addon_license="GPL v2",
	# URL for the license document the ad-on is licensed under
	addon_licenseURL="https://www.gnu.org/licenses/gpl-2.0.html",
)

# Define the python files that are the sources of your add-on.
pythonSources: list[str] = ["addon/appModules/*.py"]

# Files that contain strings for translation. Usually your python sources
i18nSources: list[str] = pythonSources + ["buildVars.py"]

# Files that will be ignored when building the nvda-addon file
excludedFiles: list[str] = []

# Base language for the NVDA add-on
baseLanguage: str = "en"

# Markdown extensions for add-on documentation
markdownExtensions: list[str] = []

# Custom braille translation tables
brailleTables: BrailleTables = {}

# Custom speech symbol dictionaries
symbolDictionaries: SymbolDictionaries = {}
