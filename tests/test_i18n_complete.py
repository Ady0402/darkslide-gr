"""Every interface string is translated into every interface language.

Rule (user, 2026-10-19): a new feature ships with its interface text in English,
日本語 and 한국어 too (繁體 also has a per-character fallback). After changing UI
text run, then fill in the new keys in tools/i18n/{en,ja,ko}.json:

    python3 tools/i18n_extract.py
    python3 tools/i18n_build.py
"""

import collections
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import i18n_build  # noqa: E402
import i18n_extract  # noqa: E402

FOLDER = ROOT / "tools/i18n"
# The camera's own menu names (official 2.10 firmware, Japanese index 0, Korean index 17).
PRESETS = {
    "标准": ("スタンダード", "표준"), "鲜艳": ("ビビッド", "비비드"), "单色": ("モノトーン", "모노톤"),
    "柔和单色": ("ソフトモノトーン", "소프트 모노톤"), "硬调单色": ("ハードモノトーン", "하드 모노톤"),
    "高对比黑白": ("ハイコントラスト白黒", "하이 콘트라스트 흑백"), "正片": ("ポジフィルム調", "포지티브 필름"),
    "银流冲洗": ("ブリーチバイパス", "블리치 바이패스"), "怀旧": ("レトロ", "복고풍"), "HDR 色调": ("HDR調", "HDR톤"),
    "交叉冲洗": ("クロスプロセス", "크로스 프로세스"), "负片": ("ネガフィルム調", "네거티브 필름"),
    "自定义 1": ("カスタム1", "커스텀 1"), "自定义 2": ("カスタム2", "커스텀 2"),
}


class Complete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((FOLDER / "source.json").read_text(encoding="utf-8"))

    def test_source_list_is_current(self):
        # New interface text must be extracted (run tools/i18n_extract.py).
        self.assertEqual(sorted(i18n_extract.collect()), sorted(self.source))

    def test_every_string_in_every_language(self):
        for code in i18n_build.LANGS:
            with self.subTest(language=code):
                table, extra = i18n_build.load(FOLDER, code)
                bad, missing = i18n_build.problems(self.source, table, extra)
                self.assertEqual(missing, [], "untranslated in %s.json" % code)
                self.assertEqual(bad, [], "placeholders differ in %s.json" % code)
                empty = [k for k in self.source if not (table.get(k) or extra.get(k))]
                self.assertEqual(empty, [])

    def test_preset_names_match_the_camera(self):
        for code, at in (("ja", 0), ("ko", 1)):
            table, extra = i18n_build.load(FOLDER, code)
            for zh, names in PRESETS.items():
                self.assertEqual(extra.get(zh, table.get(zh)), names[at], (code, zh))

    def test_bundle_is_current(self):
        # web/i18n-data.js must be rebuilt after editing the tables (run tools/i18n_build.py).
        want = i18n_build.render(i18n_build.build(report=False))
        self.assertEqual((ROOT / "web/i18n-data.js").read_text(encoding="utf-8"), want)


if __name__ == "__main__":
    unittest.main()
