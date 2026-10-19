"""Which camera menu language shows the custom preset names.

The new name always lives in the English text (or the storage lent to it), so the
English menu always shows it. The language chosen here additionally gets its own
menu record pointed at that text; every other language keeps its factory name.
A name edit without a choice keeps the 1.0.0 behaviour (Simplified Chinese only),
for older projects and direct API callers.

The 21 menu languages are listed in the firmware's own order (index into the
string-table array); every preset name record in each of them was checked on the
official GR III 2.10 file to be a separate one-line record.
"""

# code -> (firmware language index, name in that language)
CHOICES = {
    "ja": (0, "日本語"),
    "en": (1, "English"),
    "fr": (2, "Français"),
    "de": (3, "Deutsch"),
    "es": (4, "Español"),
    "pt": (5, "Português"),
    "it": (6, "Italiano"),
    "nl": (7, "Nederlands"),
    "da": (8, "Dansk"),
    "sv": (9, "Svenska"),
    "fi": (10, "Suomi"),
    "pl": (11, "Polski"),
    "cs": (12, "Čeština"),
    "hu": (13, "Magyar"),
    "tr": (14, "Türkçe"),
    "el": (15, "Ελληνικά"),
    "ru": (16, "Русский"),
    "ko": (17, "한국어"),
    "zh-TW": (18, "繁體中文"),
    "zh-CN": (19, "简体中文"),
    "th": (20, "ภาษาไทย"),
}
LEGACY = ("zh-CN",)
# Languages whose own text never lends its storage to a longer preset name. When the
# chosen language is the one that lends, its own record already shows the new name
# and is not pointed a second time.
KEEP = (0, 1, 18, 19)  # ja, en, zh-TW, zh-CN


class MenuLanguageError(ValueError):
    pass


def validate(value):
    if type(value) is not str or value not in CHOICES:
        raise MenuLanguageError("相机菜单语言只能是固件里的 21 种语言之一")
    return value


def index(code):
    return CHOICES[validate(code)][0]


def repointed(edit):
    """Languages, besides English, whose record points at this name edit's text."""
    if "menu_language" not in edit:
        return LEGACY
    code = validate(edit["menu_language"])
    return () if code == "en" else (code,)


def shows_new_name(edit, language):
    return language == "en" or language in repointed(edit)


def label(code):
    return CHOICES[code][1] if code in CHOICES else None
