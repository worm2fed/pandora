#!/usr/bin/env python3
"""Tests of the UI function (ADR 0031): ``scripts/_ui.py`` (``is_ui``, ``png_width``,
``match_width``) and the Build Plan paths of ``_journal/artifacts.py`` (``plan_paths``,
``ui_tasks``).

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_ui.py'

Every PNG is built in code; no fixture holds a real screen.
"""

from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
UI = TESTS_DIR.parent / "scripts" / "_ui.py"


def load_ui_module():
    spec = importlib.util.spec_from_file_location("shipgate_ui_test", UI)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png_bytes(width: int, height: int = 1) -> bytes:
    """A valid 8-bit grey PNG: the signature, IHDR, one IDAT and IEND."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b""))


class TestIsUi(unittest.TestCase):
    """``is_ui``: the glob rule of the artifact homes, case-sensitive."""

    GLOBS = ["web/templates/*", "web/static/*"]

    def setUp(self):
        self.ui = load_ui_module()

    def test_an_exact_glob(self):
        self.assertTrue(self.ui.is_ui("web/templates/index.html", self.GLOBS))
        self.assertTrue(self.ui.is_ui("web/static/site.css", self.GLOBS))

    def test_a_star_slash_match_on_a_deeper_path(self):
        self.assertTrue(self.ui.is_ui("app/web/templates/index.html", self.GLOBS))
        self.assertTrue(self.ui.is_ui("/abs/root/web/static/site.css", self.GLOBS))

    def test_a_star_crosses_a_slash(self):
        self.assertTrue(self.ui.is_ui("web/templates/partials/nav.html", self.GLOBS))

    def test_a_leading_dot_slash(self):
        self.assertTrue(self.ui.is_ui("./web/templates/index.html", self.GLOBS))
        self.assertTrue(self.ui.is_ui("web/static/site.css", ["./web/static/*"]))
        self.assertTrue(self.ui.is_ui("app/web/static/site.css", ["./web/static/*"]))

    def test_an_empty_list(self):
        self.assertFalse(self.ui.is_ui("web/templates/index.html", []))

    def test_a_tsx_file_outside_the_globs_is_not_ui(self):
        """SC-001: an extension is no rule; a terminal view is not UI."""
        self.assertFalse(self.ui.is_ui("hud/views.tsx", ["web/templates/*"]))
        self.assertFalse(self.ui.is_ui("hud/tests/views.test.tsx", self.GLOBS))

    def test_the_match_is_case_sensitive(self):
        self.assertFalse(self.ui.is_ui("Web/Templates/index.html", self.GLOBS))

    def test_another_path_is_not_ui(self):
        self.assertFalse(self.ui.is_ui("src/server.py", self.GLOBS))
        self.assertFalse(self.ui.is_ui("web/templatesX", self.GLOBS))


class TestPngWidth(unittest.TestCase):
    """``png_width``: the IHDR width of a PNG, from its first 24 bytes."""

    def setUp(self):
        self.ui = load_ui_module()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def test_the_widths_of_valid_pngs(self):
        for width in (390, 780, 1170, 1280):
            with self.subTest(width=width):
                path = self.write(f"w{width}.png", png_bytes(width))
                self.assertEqual(self.ui.png_width(path), width)
                self.assertEqual(self.ui.png_width(str(path)), width)

    def test_the_first_24_bytes_are_enough(self):
        path = self.write("head.png", png_bytes(390)[:24])
        self.assertEqual(self.ui.png_width(path), 390)

    def test_a_jpeg_is_not_a_png(self):
        path = self.write("shot.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 30)
        with self.assertRaisesRegex(ValueError, r"^not a PNG"):
            self.ui.png_width(path)

    def test_another_first_chunk_is_not_a_png(self):
        data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IDAT", b"\x00" * 13)
        path = self.write("idat.png", data)
        with self.assertRaisesRegex(ValueError, r"^not a PNG"):
            self.ui.png_width(path)

    def test_a_truncated_file(self):
        path = self.write("short.png", png_bytes(390)[:10])
        with self.assertRaisesRegex(ValueError, r"^truncated: "):
            self.ui.png_width(path)

    def test_a_width_of_0(self):
        path = self.write("zero.png", png_bytes(0))
        with self.assertRaises(ValueError) as raised:
            self.ui.png_width(path)
        self.assertEqual(str(raised.exception), "not a PNG: width 0")

    def test_a_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            self.ui.png_width(self.dir / "missing.png")


class TestMatchWidth(unittest.TestCase):
    """``match_width``: the set widths w for which a pixel width is w, 2w or 3w."""

    def setUp(self):
        self.ui = load_ui_module()

    def test_each_scale(self):
        widths = [390, 1280]
        for px, expected in ((390, [390]), (780, [390]), (1170, [390]),
                             (1280, [1280]), (2560, [1280]), (3840, [1280])):
            with self.subTest(px=px):
                self.assertEqual(self.ui.match_width(px, widths), expected)

    def test_no_match(self):
        for px in (1000, 1560, 389, 0):
            with self.subTest(px=px):
                self.assertEqual(self.ui.match_width(px, [390, 1280]), [])

    def test_two_set_widths_in_their_order_without_repeats(self):
        self.assertEqual(self.ui.match_width(780, [390, 780]), [390, 780])
        self.assertEqual(self.ui.match_width(780, [780, 390]), [780, 390])
        self.assertEqual(self.ui.match_width(780, [390, 390]), [390])


# Line numbers count in the whole file: the Build Plan starts on line 6.
WORKLOG = """# Worklog: demo

Prose that names T009 — file(s): `outside.py` is no task line.
- [ ] T099 — A task line above the Build Plan — file(s): `web/templates/above.html`

# Build Plan

## Setup

- [ ] T001 — Two paths — file(s): `web/templates/a.html`, `src/b.py` — done when: tests pass.
- [x] **T002**: A bold id — file(s): `web/static/site.css`
- [ ] T003 — No files — file(s): none — done when: the suite passes.
- [ ] T004 — No part — done when: it is written.
- [ ] T005 — A part with no path — file(s): the CSS files — done when: they load.
- [ ] T006 [P] — Ends at the dash — file(s): `src/c.py` — done when: `web/templates/x.html` exists.
- [ ] T007 – An en dash – file(s): `src/d.py` – done when: `web/static/y.css` loads.
- [ ] T008 — Not the literal form — files: `web/templates/b.html`
- [ ] T010 — A word that starts with none — file(s): nonexistent

# After the build

- [ ] T011 — Outside the region — file(s): `web/templates/z.html`
"""

NO_PATH = "file(s): names no path in backticks and is not none"
NO_PART = "no file(s): part"


class TestPlanPaths(unittest.TestCase):
    """``plan_paths``: the ``file(s):`` part of each Build Plan task line."""

    @classmethod
    def setUpClass(cls):
        from test_journal import load_journal_module

        cls.jm = load_journal_module()

    def test_each_form(self):
        self.assertEqual(self.jm.plan_paths(WORKLOG), [
            {"id": "T001", "line": 10, "paths": ["web/templates/a.html", "src/b.py"],
             "error": None},
            {"id": "T002", "line": 11, "paths": ["web/static/site.css"], "error": None},
            {"id": "T003", "line": 12, "paths": [], "error": None},
            {"id": "T004", "line": 13, "paths": None, "error": NO_PART},
            {"id": "T005", "line": 14, "paths": None, "error": NO_PATH},
            {"id": "T006", "line": 15, "paths": ["src/c.py"], "error": None},
            {"id": "T007", "line": 16, "paths": ["src/d.py"], "error": None},
            {"id": "T008", "line": 17, "paths": None, "error": NO_PART},
            {"id": "T010", "line": 18, "paths": None, "error": NO_PATH},
        ])

    def test_the_line_is_the_task_line_of_the_file(self):
        lines = WORKLOG.splitlines()
        for item in self.jm.plan_paths(WORKLOG):
            with self.subTest(task=item["id"]):
                self.assertIn(item["id"], lines[item["line"] - 1])
                self.assertRegex(lines[item["line"] - 1], r"^- \[[ x]\] ")

    def test_no_build_plan_heading_reads_the_whole_text(self):
        text = "Intro\n\n- [ ] T001 — x — file(s): `a.py`\n- [ ] T002 — y\n"
        self.assertEqual(self.jm.plan_paths(text), [
            {"id": "T001", "line": 3, "paths": ["a.py"], "error": None},
            {"id": "T002", "line": 4, "paths": None, "error": NO_PART},
        ])

    def test_a_repeated_id_gives_one_entry_per_line(self):
        text = ("## Build Plan\n- [ ] T001 — a — file(s): `src/a.py`\n"
                "- [x] T001 — b — file(s): `web/b.html`\n")
        self.assertEqual([(i["id"], i["line"], i["paths"]) for i in self.jm.plan_paths(text)],
                         [("T001", 2, ["src/a.py"]), ("T001", 3, ["web/b.html"])])

    def test_backticked_tokens_come_before_none(self):
        text = "# Build Plan\n- [ ] T001 — a — file(s): none, but see `web/a.html`\n"
        self.assertEqual(self.jm.plan_paths(text)[0]["paths"], ["web/a.html"])

    def test_the_ids_are_parse_build_plans(self):
        self.assertEqual([i["id"] for i in self.jm.plan_paths(WORKLOG)],
                         [t["id"] for t in self.jm.parse_build_plan(WORKLOG)])


class TestUiTasks(unittest.TestCase):
    """``ui_tasks``: per task id, whether a path of its first line is UI."""

    GLOBS = ["web/templates/*", "web/static/*"]

    @classmethod
    def setUpClass(cls):
        from test_journal import load_journal_module

        cls.jm = load_journal_module()

    def test_ui_and_other_tasks(self):
        self.assertEqual(self.jm.ui_tasks(WORKLOG, self.GLOBS), {
            "T001": True, "T002": True, "T003": False, "T004": False, "T005": False,
            "T006": False, "T007": False, "T008": False, "T010": False,
        })

    def test_a_repeated_id_keeps_its_first_line(self):
        first_not_ui = ("# Build Plan\n- [ ] T001 — a — file(s): `src/a.py`\n"
                        "- [ ] T001 — b — file(s): `web/static/b.css`\n")
        self.assertEqual(self.jm.ui_tasks(first_not_ui, self.GLOBS), {"T001": False})
        first_ui = ("# Build Plan\n- [ ] T001 — a — file(s): `web/static/b.css`\n"
                    "- [ ] T001 — b — file(s): `src/a.py`\n")
        self.assertEqual(self.jm.ui_tasks(first_ui, self.GLOBS), {"T001": True})

    def test_a_line_with_an_error_is_not_ui(self):
        text = ("# Build Plan\n- [ ] T001 — web/templates/a.html, no part\n"
                "- [ ] T002 — a — file(s): web/templates/a.html\n")
        self.assertEqual(self.jm.ui_tasks(text, self.GLOBS), {"T001": False, "T002": False})

    def test_empty_globs_give_all_false(self):
        result = self.jm.ui_tasks(WORKLOG, [])
        self.assertEqual(list(result), [i["id"] for i in self.jm.plan_paths(WORKLOG)])
        self.assertFalse(any(result.values()))


if __name__ == "__main__":
    unittest.main()
