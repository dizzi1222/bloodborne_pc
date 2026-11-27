# SPDX-License-Identifier: GPL-2.0-or-later
"""Spanish / English texts for the Hunter's Atlas updater.

The language follows Windows (Spanish UI -> Spanish, anything else -> English).
``--lang es|en`` or the HUNTERS_ATLAS_LANG environment variable override it.
Every text is written in place as ``tr("español", "English")``.
"""
from __future__ import annotations

import ctypes
import os

LANGS = ("es", "en")


def _windows_language() -> str:
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "es" if (lang_id & 0x3FF) == 0x0A else "en"  # LANG_SPANISH


def _initial() -> str:
    forced = os.environ.get("HUNTERS_ATLAS_LANG", "").strip().lower()[:2]
    return forced if forced in LANGS else _windows_language()


LANG = _initial()


def set_language(lang: str | None) -> None:
    global LANG
    if lang and lang.lower()[:2] in LANGS:
        LANG = lang.lower()[:2]


def tr(es: str, en: str) -> str:
    return es if LANG == "es" else en
