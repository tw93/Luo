"""Regression checks for final posture and component gaps, without private fonts."""

import contextlib
import copy
import io
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.pointInsidePen import PointInsidePen
from fontTools.ttLib import TTFont

import build


def fixture(char, slope):
    fb = FontBuilder(2048, isTTF=True)
    fb.setupGlyphOrder([".notdef", "stroke"])
    fb.setupCharacterMap({ord(char): "stroke"})
    glyphs = {}
    for name in [".notdef", "stroke"]:
        pen = TTGlyphPen(None)
        if name == "stroke":
            rise = round(1200 * math.tan(math.radians(slope)))
            pen.moveTo((300, 900))
            pen.lineTo((1500, 900 + rise))
            pen.lineTo((1500, 800 + rise))
            pen.lineTo((300, 800))
            pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    return fb.font


class InstalledFontTests(unittest.TestCase):
    def test_diagnostic_overwrite_cannot_change_validated_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Library" / "Fonts" / "Luo-Regular.ttf"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"previous installed font")
            dist = root / "dist"
            dist.mkdir()
            source = dist / "Luo-Regular.ttf"
            complete = b"validated complete font"
            source.write_bytes(complete)
            candidate = Mock()
            candidate.getBestCmap.return_value = dict.fromkeys(range(6500))
            candidate.__enter__ = Mock(return_value=candidate)
            candidate.__exit__ = Mock(side_effect=lambda *args: source.write_bytes(b"diagnostic subset") and False)
            cf, ct = Mock(), Mock()
            cf.CFURLCreateFromFileSystemRepresentation.return_value = 1
            cf.CFErrorGetCode.return_value = 0
            ct.CTFontManagerRegisterFontsForURL.return_value = True
            ct.CTFontManagerUnregisterFontsForURL.return_value = True
            with patch.object(build.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"CI": ""}), \
                 patch.object(build, "BUILD_CHARS", "gb2312-full"), \
                 patch.object(build, "DIST_DIR", dist), \
                 patch.object(Path, "home", return_value=root), \
                 patch.object(build, "TTFont", return_value=candidate), \
                 patch("ctypes.util.find_library", side_effect=lambda name: name), \
                 patch("ctypes.CDLL", side_effect=lambda name: cf if name == "CoreFoundation" else ct), \
                 contextlib.redirect_stdout(io.StringIO()):
                build.sync_installed_font()
            self.assertEqual(source.read_bytes(), b"diagnostic subset")
            self.assertEqual(target.read_bytes(), complete)


class HorizontalPostureTests(unittest.TestCase):
    def test_built_frame_bars_stay_in_final_posture_band(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            for char in "面用日目田口中常":
                with self.subTest(char=char):
                    glyph = font["glyf"][font.getBestCmap()[ord(char)]]
                    coords, ends, flags = glyph.getCoordinates(font["glyf"])
                    width = max(x for x, y in coords) - min(x for x, y in coords)
                    bars = []
                    start = 0
                    for end in ends:
                        on = [i for i in range(start, end + 1) if flags[i] & 1]
                        for k, a in enumerate(on):
                            b = on[(k + 1) % len(on)]
                            dx, dy = coords[b][0]-coords[a][0], coords[b][1]-coords[a][1]
                            if abs(dx) >= width * 0.22 and abs(dy/dx) <= math.tan(math.radians(9)):
                                bars.append((dy/dx, abs(dx)))
                        start = end + 1
                    self.assertGreaterEqual(len(bars), 2)
                    bars.sort()
                    half = sum(length for slope, length in bars) / 2
                    accumulated = 0
                    for slope, length in bars:
                        accumulated += length
                        if accumulated >= half:
                            self.assertLessEqual(abs(math.degrees(math.atan(slope))), 1.15)
                            break

    def test_rising_and_falling_bars_reach_one_degree(self):
        for angle in (4, -4):
            with self.subTest(angle=angle):
                font = fixture("用", angle)
                before = list(font["glyf"]["stroke"].coordinates)
                with contextlib.redirect_stdout(io.StringIO()):
                    build.luo_horiz_level(font)
                after = list(font["glyf"]["stroke"].coordinates)
                (ax, ay), (bx, by) = after[:2]
                self.assertLessEqual(abs(math.degrees(math.atan2(by-ay, bx-ax))), 1.1)
                self.assertEqual([x for x, y in before], [x for x, y in after])
                self.assertEqual(after[1][1]-after[2][1], 100)

    def test_walk_body_is_not_exempt_from_affine_leveling(self):
        font = fixture("适", 4)
        with contextlib.redirect_stdout(io.StringIO()):
            build.luo_horiz_level(font)
        (ax, ay), (bx, by) = font["glyf"]["stroke"].coordinates[:2]
        self.assertLessEqual(abs(math.degrees(math.atan2(by-ay, bx-ax))), 1.1)

    def test_frozen_moon_and_diagonal_stroke_stay_unchanged(self):
        for char, angle in (("月", 4), ("人", 45), ("用", 0.5)):
            with self.subTest(char=char, angle=angle):
                font = fixture(char, angle)
                before = list(font["glyf"]["stroke"].coordinates)
                with contextlib.redirect_stdout(io.StringIO()):
                    build.luo_horiz_level(font)
                self.assertEqual(before, list(font["glyf"]["stroke"].coordinates))


class ComplexComponentTests(unittest.TestCase):
    def test_si_bar_and_dot_body_keep_secondary_stroke_weight(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            upm = font["head"].unitsPerEm
            glyphs = font.getGlyphSet()
            glyph = glyphs[font.getBestCmap()[ord("魔")]]

            def ink(x, y):
                pen = PointInsidePen(glyphs, (x, y), evenOdd=False)
                glyph.draw(pen)
                return pen.getResult()

            probes = [(1420, 120, -0.10, math.sqrt(0.99), 0.033),
                      (1470, 129, -0.10, math.sqrt(0.99), 0.033),
                      (1520, 133, -0.10, math.sqrt(0.99), 0.033),
                      (1610, 169, 0.80, 0.60, 0.070)]
            for x, y, nx, ny, minimum in probes:
                with self.subTest(point=(x, y)):
                    self.assertTrue(ink(x, y))
                    distances = []
                    for sign in (-1, 1):
                        distance = 0
                        while ink(x + sign * distance * nx, y + sign * distance * ny):
                            distance += 0.25
                            self.assertLess(distance, 0.12 * upm)
                        distances.append(distance)
                    self.assertGreaterEqual(sum(distances), minimum * upm)

    def test_si_has_open_space_on_both_sides_and_above_the_bowl(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            glyphs = font.getGlyphSet()
            glyph = glyphs[font.getBestCmap()[ord("魔")]]
            probes = [((1300, y), False) for y in (100, 150, 200, 250, 300)]
            probes += [((1600, 100), False), ((1240, 200), True), ((1420, 250), True)]
            for point, expected in probes:
                with self.subTest(point=point):
                    pen = PointInsidePen(glyphs, point, evenOdd=False)
                    glyph.draw(pen)
                    self.assertEqual(pen.getResult(), expected)

    def test_folded_strokes_do_not_collapse_into_thin_chevrons(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            glyph = font["glyf"][font.getBestCmap()[ord("鬣")]]
            start = glyph.endPtsOfContours[-4] + 1
            for end in glyph.endPtsOfContours[-3:]:
                with self.subTest(contour_end=end):
                    xs = [x for x, y in glyph.coordinates[start:end + 1]]
                    area = -build._contour_signed_area(glyph.coordinates, start, end)
                    self.assertGreater(area, 0)
                    self.assertGreaterEqual(area / (max(xs) - min(xs)), 0.060 * font["head"].unitsPerEm)
                start = end + 1

    def test_compound_si_is_not_reinflated_as_a_thin_tick(self):
        with TTFont(build.BASE_FONT) as font:
            build.subset_to_seed(font, "魔")
            with contextlib.redirect_stdout(io.StringIO()):
                build.bolden_glyphs(font, build.BOLDEN_H, build.BOLDEN_V)
                build.rebuild_complex_components(font)
            glyph = font["glyf"][font.getBestCmap()[ord("魔")]]
            start = glyph.endPtsOfContours[-2] + 1
            before = list(glyph.coordinates[start:])
            with contextlib.redirect_stdout(io.StringIO()):
                build.luo_small_stroke_plump(font)
            self.assertEqual(before, list(glyph.coordinates[start:]))

        # Positive control: an ordinary thin tick still receives the pass.
        font = fixture("来", 0)
        glyph = font["glyf"]["stroke"]
        for i, xy in enumerate(((300, 900), (700, 900), (700, 880), (300, 880))):
            glyph.coordinates[i] = xy
        before = list(glyph.coordinates)
        with contextlib.redirect_stdout(io.StringIO()):
            build.luo_small_stroke_plump(font)
        self.assertNotEqual(before, list(glyph.coordinates))

    def test_wood_crossbars_have_a_real_gap_between_inked_neighbors(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            glyphs = font.getGlyphSet()
            glyph = glyphs[font.getBestCmap()[ord("魔")]]
            for point, expected in (((1050, 1250), True), ((1120, 1250), False),
                                    ((1140, 1250), False), ((1200, 1250), True)):
                with self.subTest(point=point):
                    pen = PointInsidePen(glyphs, point, evenOdd=False)
                    glyph.draw(pen)
                    self.assertEqual(pen.getResult(), expected)

    def test_complex_hooks_stay_low_without_a_flat_clamp(self):
        path = Path(os.environ.get("LUO_TEST_FONT", build.DIST_DIR / "Luo-Regular.ttf"))
        with TTFont(path) as font:
            upm = font["head"].unitsPerEm
            for char, ceiling in (("魔", 0.17), ("鬣", 0.14)):
                with self.subTest(char=char):
                    glyph = font["glyf"][font.getBestCmap()[ord(char)]]
                    right_band = glyph.xMax - 0.1 * (glyph.xMax - glyph.xMin)
                    tail = [y for x, y in glyph.coordinates
                            if x > right_band and y < glyph.yMin + 0.4 * upm]
                    self.assertTrue(tail)
                    self.assertLessEqual((max(tail) - glyph.yMin) / upm, ceiling)
                    self.assertGreater(len(set(tail)), 4)


class ComponentSimplificationTests(unittest.TestCase):
    def test_rejected_component_stack_cannot_reenter_selected_glyphs(self):
        passes = (
            build.refine_by_category, build.refine_kai_component_balance,
            build.luo_bottom_anchor_settle, build.luo_left_radical_contain,
            build.luo_inner_counter_open, build.luo_top_bottom_separate,
            build.luo_frame_inner_open, build.refine_visible_problem_glyphs,
        )
        with TTFont(build.BASE_FONT) as source:
            for refiner in passes:
                with self.subTest(pass_name=refiner.__name__):
                    font = copy.deepcopy(source)
                    build.subset_to_seed(font, "魔鬣纸面")
                    cmap = font.getBestCmap()
                    before = {char: list(font["glyf"][cmap[ord(char)]].coordinates) for char in "魔鬣纸面"}
                    with contextlib.redirect_stdout(io.StringIO()):
                        refiner(font)
                    for char in before:
                        self.assertEqual(before[char], list(font["glyf"][cmap[ord(char)]].coordinates), char)

    def test_identity_stack_cannot_reenter_selected_glyphs(self):
        with TTFont(build.BASE_FONT) as font:
            build.subset_to_seed(font, "魔鬣纸面")
            cmap = font.getBestCmap()
            before = {char: list(font["glyf"][cmap[ord(char)]].coordinates) for char in "魔鬣纸面"}
            with contextlib.redirect_stdout(io.StringIO()):
                build.refine_identity_chars(font, "魔鬣纸面")
            for char in before:
                self.assertEqual(before[char], list(font["glyf"][cmap[ord(char)]].coordinates), char)

    def test_dense_inner_ticks_and_frame_primary_bar_are_preserved(self):
        for char, refiner in (("鬣", build.luo_small_stroke_plump), ("面", build.luo_gesture_body_contract)):
            with self.subTest(char=char):
                with TTFont(build.BASE_FONT) as font:
                    build.subset_to_seed(font, char)
                    glyph = font["glyf"][font.getBestCmap()[ord(char)]]
                    before = list(glyph.coordinates)
                    with contextlib.redirect_stdout(io.StringIO()):
                        refiner(font)
                    self.assertEqual(before, list(glyph.coordinates))


if __name__ == "__main__":
    unittest.main()
