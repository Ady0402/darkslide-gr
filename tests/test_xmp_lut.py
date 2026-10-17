import unittest

from darkslide import xmp_lut as xl


def xmp(attrs=None, curves=None, name="Test Look", extra=""):
    a = "".join(' crs:%s="%s"' % kv for kv in (attrs or {}).items())
    c = "".join("<crs:%s><rdf:Seq>%s</rdf:Seq></crs:%s>" %
                (k, "".join("<rdf:li>%d, %d</rdf:li>" % p for p in pts), k) for k, pts in (curves or {}).items())
    return ('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"'
            ' crs:PresetType="Normal" crs:Version="15.0" crs:ProcessVersion="11.0"%s>'
            '<crs:Name><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></crs:Name>%s%s'
            '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>' % (a, name, c, extra)).encode("utf-8")


def table(result):
    lines = [l for l in result["cube"].splitlines() if l and (l[0].isdigit() or l[0] == "-")]
    return [tuple(map(float, l.split())) for l in lines]


def at(rows, size, r, g, b):
    return rows[r + g * size + b * size * size]


class Parse(unittest.TestCase):
    def test_reads_attributes_names_and_curves(self):
        s = xl.parse(xmp({"Saturation": "-20"}, {"ToneCurvePV2012": [(0, 0), (128, 140), (255, 255)]}))
        self.assertEqual(s["Saturation"], "-20")
        self.assertEqual(s["Name"], "Test Look")
        self.assertEqual(s["ToneCurvePV2012"], ["0, 0", "128, 140", "255, 255"])

    def test_refuses_unsafe_or_broken_input(self):
        for raw in (b"", b"x" * (xl.MAX_BYTES + 1), b"<!DOCTYPE x [<!ENTITY a 'b'>]><x>&a;</x>",
                    b"<not closed", b"<x/>", "文本".encode("utf-8")):
            with self.assertRaises(xl.XmpError):
                xl.parse(raw)

    def test_nested_look_is_noted_not_merged(self):
        look = ('<crs:Look><rdf:Description crs:Name="Inner"><crs:Parameters><rdf:Description'
                ' crs:Saturation="+80"/></crs:Parameters></rdf:Description></crs:Look>')
        s = xl.parse(xmp(extra=look))
        self.assertEqual(s["Look"], "True")
        self.assertNotIn("Saturation", s)

    def test_bad_values_rejected(self):
        for attrs, curves in (({"Saturation": "abc"}, None), ({"Exposure2012": "nan"}, None),
                              ({}, {"ToneCurvePV2012": [(0, 0), (0, 10)]}),
                              ({}, {"ToneCurvePV2012": [(0, 0), (300, 10)]})):
            with self.assertRaises(xl.XmpError):
                xl.convert(xmp(attrs, curves), size=3)


class Convert(unittest.TestCase):
    def test_neutral_preset_is_identity(self):
        n = 9
        res = xl.convert(xmp(), size=n)
        rows = table(res)
        self.assertEqual(len(rows), n ** 3)
        worst = max(abs(v - [r, g, b][k] / (n - 1)) for b in range(n) for g in range(n) for r in range(n)
                    for k, v in enumerate(at(rows, n, r, g, b)))
        self.assertLess(worst, 1e-5)
        self.assertEqual((res["used"], res["skipped"]), ([], []))

    def test_cube_header_and_range(self):
        res = xl.convert(xmp({"Vibrance": "+30", "Contrast2012": "+40"}, name='A "quoted"\nname'))
        head = res["cube"].splitlines()[:5]
        self.assertEqual(head[0], 'TITLE "A quotedname"')
        self.assertIn("LUT_3D_SIZE 33", head)
        rows = table(res)
        self.assertEqual(len(rows), 33 ** 3)
        self.assertTrue(all(0.0 <= v <= 1.0 for row in rows for v in row))

    def test_full_desaturation_and_black_white_are_neutral(self):
        for attrs in ({"Saturation": "-100"}, {"ConvertToGrayscale": "True", "GrayMixerRed": "-20", "GrayMixerBlue": "+30"}):
            rows = table(xl.convert(xmp(attrs), size=7))
            self.assertTrue(all(max(r) - min(r) < 2e-3 for r in rows), attrs)

    def test_point_curve_lifts_black(self):
        n = 5
        rows = table(xl.convert(xmp(curves={"ToneCurvePV2012": [(0, 40), (255, 255)]}), size=n))
        self.assertAlmostEqual(at(rows, n, 0, 0, 0)[0], 40 / 255, places=3)
        self.assertAlmostEqual(at(rows, n, 4, 4, 4)[1], 1.0, places=3)

    def test_channel_curve_only_moves_its_channel(self):
        n = 5
        rows = table(xl.convert(xmp(curves={"ToneCurvePV2012Blue": [(0, 0), (128, 160), (255, 255)]}), size=n))
        r, g, b = at(rows, n, 2, 2, 2)
        self.assertAlmostEqual(r, 0.5, places=3)
        self.assertAlmostEqual(g, 0.5, places=3)
        self.assertGreater(b, 0.55)

    def test_tone_sliders_keep_gray_axis_ordered(self):
        n = 17
        attrs = {"Exposure2012": "+0.40", "Contrast2012": "+60", "Highlights2012": "-80", "Shadows2012": "+70",
                 "Whites2012": "+30", "Blacks2012": "-40", "ParametricDarks": "+50", "ParametricLights": "-30"}
        rows = table(xl.convert(xmp(attrs), size=n))
        gray = [at(rows, n, i, i, i)[1] for i in range(n)]
        self.assertEqual(gray, sorted(gray))
        self.assertLess(abs(gray[0] - gray[-1]), 1.0 + 1e-9)

    def test_hsl_red_shift_leaves_blue_and_gray(self):
        n = 5
        rows = table(xl.convert(xmp({"HueAdjustmentRed": "+100", "SaturationAdjustmentRed": "-50"}), size=n))
        red, blue, gray = at(rows, n, 4, 1, 1), at(rows, n, 1, 1, 4), at(rows, n, 2, 2, 2)
        self.assertGreater(red[1] - 0.25, 0.02, "red moves toward orange")
        for got, want in ((blue, (0.25, 0.25, 1.0)), (gray, (0.5, 0.5, 0.5))):
            for x, y in zip(got, want):
                self.assertAlmostEqual(x, y, places=3)

    def test_warm_white_balance_and_shadow_grading(self):
        n = 5
        warm = at(table(xl.convert(xmp({"IncrementalTemperature": "+50"}), size=n)), n, 2, 2, 2)
        self.assertGreater(warm[0], warm[2])
        graded = table(xl.convert(xmp({"SplitToningShadowHue": "220", "SplitToningShadowSaturation": "80"}), size=n))
        dark, light = at(graded, n, 1, 1, 1), at(graded, n, 4, 4, 4)
        self.assertGreater(dark[2] - dark[0], 0.02, "shadows turn blue")
        self.assertLess(abs(light[2] - light[0]), 0.01, "white stays nearly neutral")

    def test_raw_white_balance_is_noted(self):
        res = xl.convert(xmp({"Temperature": "7500", "Tint": "+10"}), size=3)
        self.assertIn("白平衡", res["used"])
        self.assertTrue(any("5500" in n for n in res["notes"]))

    def test_non_colour_settings_are_skipped_and_listed(self):
        res = xl.convert(xmp({"GrainAmount": "25", "PostCropVignetteAmount": "-20", "Clarity2012": "+10",
                              "Sharpness": "0", "Table_ABCDEF": "xyz", "RGBTable": "ABCDEF"}), size=5)
        for label in ("颗粒", "暗角", "清晰度", "配置文件颜色表"):
            self.assertIn(label, res["skipped"])
        self.assertNotIn("锐化", res["skipped"], "zero values are not reported")
        self.assertTrue(any("颜色表" in n for n in res["notes"]))
        self.assertEqual(res["used"], [])
        rows = table(res)
        self.assertAlmostEqual(at(rows, 5, 1, 2, 3)[2], 0.75, places=4)

    def test_calibration_keeps_white(self):
        n = 5
        rows = table(xl.convert(xmp({"RedHue": "+40", "BlueSaturation": "-30", "GreenHue": "-20"}), size=n))
        for x in at(rows, n, 4, 4, 4):
            self.assertAlmostEqual(x, 1.0, places=3)
        self.assertNotAlmostEqual(at(rows, n, 4, 0, 0)[1], 0.0, places=2)

    def test_main_refuses_overwrite(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "a.xmp"), os.path.join(tmp, "a.cube")
            with open(src, "wb") as f:
                f.write(xmp({"Saturation": "+10"}))
            self.assertEqual(xl.main([src, out]), 0)
            with open(out, encoding="utf-8") as f:
                self.assertTrue(f.read().startswith('TITLE "Test Look"'))
            self.assertEqual(xl.main([src, out]), 1)


try:
    from tests.test_http import Served
except ImportError:  # run through "discover -s tests"
    from test_http import Served


class Http(Served):
    def test_xmp_route_returns_a_cube_named_after_the_preset(self):
        res = self.call("POST", "/api/xmp-lut", xmp({"Saturation": "-20"}), {"X-Filename": "moody.xmp"})
        out = self.assertJson(res, 200)
        self.assertEqual(out["name"], "Test Look")
        self.assertIn("LUT_3D_SIZE 33", out["cube"])
        self.assertIn("饱和度", out["used"])
        res = self.call("POST", "/api/xmp-lut", xmp({"Saturation": "-20"}, name=""), {"X-Filename": "moody.xmp"})
        self.assertEqual(self.assertJson(res, 200)["name"], "moody")
        self.assertEqual(self.call("POST", "/api/xmp-lut", b"<x>not a preset</x>", {"X-Filename": "a.xmp"}).status, 422)


if __name__ == "__main__":
    unittest.main()
