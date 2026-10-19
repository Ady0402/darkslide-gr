"""Menu-language rules as the read-back checks see them.

Written separately from menu_language.py (the writer side) on purpose: if the
writer's language table or policy were wrong, checks that reused it would agree
with the mistake. The indices below were confirmed against the factory preset
names in the official GR III 2.10 and GR IIIx 1.60 files
(tests/test_verify_languages.py).
"""

# code -> index into the firmware's 21-entry string-table array
INDEX = {
    "ja": 0, "en": 1, "fr": 2, "de": 3, "es": 4, "pt": 5, "it": 6, "nl": 7,
    "da": 8, "sv": 9, "fi": 10, "pl": 11, "cs": 12, "hu": 13, "tr": 14,
    "el": 15, "ru": 16, "ko": 17, "zh-TW": 18, "zh-CN": 19, "th": 20,
}

# Languages whose own text never lends its storage to a longer preset name.
NEVER_LENT = (0, 1, 18, 19)

# Always read back: English plus the Chinese and Japanese menus.
ALWAYS_CHECKED = ("en", "zh-CN", "zh-TW", "ja")


def chosen(edit):
    """Languages besides English whose record should point at the new name.

    No choice keeps the 1.0.0 behaviour: Simplified Chinese only."""
    if "menu_language" not in edit:
        return ("zh-CN",)
    code = edit["menu_language"]
    if type(code) is not str or code not in INDEX:
        raise ValueError("menu language")
    return () if code == "en" else (code,)


def checked(edit=None):
    extra = chosen(edit) if edit is not None else ()
    return ALWAYS_CHECKED + tuple(c for c in extra if c not in ALWAYS_CHECKED)


def shows_new_name(edit, code):
    return code == "en" or code in chosen(edit)
