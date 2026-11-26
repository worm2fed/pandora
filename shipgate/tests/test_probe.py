"""Contract tests for evals/probe.py (ADR 0036, FR-016 to FR-018, SC-006): the trigger
probe counts the skills that fired and the named calls in a canned stream-json run,
judges each run against a probe.json, and saves one result file per case with the model,
turns, cost and time of every run. No test starts a real claude."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
REPO = SHIPGATE.parent
PROBE = SHIPGATE / "evals" / "probe.py"
EVALRUN = SHIPGATE / "evals" / "evalrun.py"
PROBE_SH = REPO / ".claude" / "skills" / "run-evals" / "scripts" / "probe.sh"

_spec = importlib.util.spec_from_file_location("shipgate_probe", PROBE)
probe = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(probe)
except FileNotFoundError:
    probe = None

NEGATIVE = {"skill": "structured-debug", "fires": False,
            "zero": {"bash": ["signals\\.py", "codegraph"], "agent": True,
                     "edit": ["docs/", "CLAUDE\\.md"], "write": []}}
FIRING = {"skill": "route-and-map", "fires": True, "zero": {"agent": True}}


def init(model="claude-fable-5-2"):
    return {"type": "system", "subtype": "init", "model": model,
            "plugins": [{"name": "shipgate", "path": "/plugin"}]}


def tool(name, **inp):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t-{name}", "name": name, "input": inp}]}}


def result(turns=3, cost=0.08, ms=12000, is_error=False, text="done"):
    return {"type": "result", "subtype": "success", "num_turns": turns,
            "total_cost_usd": cost, "duration_ms": ms, "is_error": is_error, "result": text}


QUIET = [init(), tool("Read", file_path="src/a.ts"),
         tool("Edit", file_path="src/a.ts", old_string="a", new_string="b"),
         result(turns=3, cost=0.08, ms=12000)]

NOISY = [init(),
         tool("Skill", skill="shipgate:structured-debug"),
         tool("Bash", command="python3 shipgate/scripts/signals.py hotspots --json"),
         tool("Bash", command="codegraph status"),
         tool("Bash", command="git status"),
         tool("Agent", description="explore", prompt="look"),
         tool("Task", description="legacy", prompt="look"),
         tool("Edit", file_path="docs/notes.md", old_string="a", new_string="b"),
         tool("Edit", file_path="app/CLAUDE.md", old_string="a", new_string="b"),
         tool("Edit", file_path="src/a.ts", old_string="a", new_string="b"),
         tool("Write", file_path="src/new.ts", content="x"),
         tool("Skill", skill="verify"),
         result(turns=9, cost=0.31, ms=45500)]

FIRED = [init(), tool("Skill", skill="shipgate:route-and-map"),
         tool("Bash", command="ls"), result(turns=4, cost=0.12, ms=20000)]

LIMIT_LINE = "You've hit your weekly limit · resets Mon 9am"


class TmpDir(unittest.TestCase):
    def setUp(self):
        if probe is None:
            self.fail(f"{PROBE} does not exist")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plugin = self.tmp / "plugin"
        (self.plugin / ".claude-plugin").mkdir(parents=True)
        (self.plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "shipgate", "version": "1.2.3"}))

    def stream(self, events, name="run1.jsonl", extra_lines=()):
        path = self.tmp / name
        lines = [json.dumps(e) for e in events] + list(extra_lines)
        path.write_text("".join(line + "\n" for line in lines))
        return path

    def expect(self, data, name="probe.json"):
        path = self.tmp / name
        path.write_text(json.dumps(data))
        return path

    def cli(self, *args, code=0):
        proc = subprocess.run([sys.executable, str(PROBE), *map(str, args)],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return proc


class TestCounts(TmpDir):
    def test_skills_in_order_and_named_counts(self):
        run = probe.read_stream(self.stream(NOISY))
        self.assertEqual(run["skills"], ["shipgate:structured-debug", "verify"])
        counts = probe.count_calls(run["calls"], NEGATIVE["zero"])
        self.assertEqual(counts["bash"], {"signals\\.py": 1, "codegraph": 1})
        self.assertEqual(counts["agent"], 2)
        self.assertEqual(counts["edit"], {"docs/": 1, "CLAUDE\\.md": 1})
        self.assertEqual(counts["write"], {"*": 1})

    def test_empty_or_absent_pattern_list_counts_every_call(self):
        run = probe.read_stream(self.stream(NOISY))
        counts = probe.count_calls(run["calls"], {"bash": [], "edit": []})
        self.assertEqual(counts["bash"], {"*": 3})
        self.assertEqual(counts["edit"], {"*": 3})
        self.assertEqual(counts["write"], {"*": 1})
        self.assertEqual(counts["agent"], 2)
        self.assertEqual(probe.count_calls(run["calls"], None)["bash"], {"*": 3})

    def test_turns_cost_and_seconds_from_the_result_record(self):
        run = probe.read_stream(self.stream(NOISY))
        self.assertEqual((run["turns"], run["cost"], run["seconds"]), (9, 0.31, 45.5))
        self.assertIsNone(run["error"])

    def test_non_json_line_is_kept_as_an_error(self):
        run = probe.read_stream(self.stream(QUIET[:2], extra_lines=[LIMIT_LINE]))
        self.assertIn("weekly limit", run["error"])

    def test_is_error_result_and_missing_result_are_errors(self):
        run = probe.read_stream(self.stream([init(), result(is_error=True, text="boom")]))
        self.assertIn("boom", run["error"])
        run = probe.read_stream(self.stream([init(), tool("Bash", command="ls")]))
        self.assertIn("no result record", run["error"])


class TestJudge(TmpDir):
    def judge(self, events, expect, extra_lines=()):
        run = probe.read_stream(self.stream(events, extra_lines=extra_lines))
        return probe.judge_run(run, expect, "shipgate")

    def test_negative_probe_passes_on_a_quiet_run(self):
        verdict = self.judge(QUIET, NEGATIVE)
        self.assertIs(verdict["passed"], True, verdict)
        self.assertEqual(verdict["failures"], [])

    def test_negative_probe_fails_on_fired_skill_and_each_nonzero_count(self):
        verdict = self.judge(NOISY, NEGATIVE)
        self.assertIs(verdict["passed"], False)
        text = "\n".join(verdict["failures"])
        for needle in ("structured-debug", "signals\\.py", "codegraph", "agent", "docs/",
                       "CLAUDE\\.md", "write"):
            self.assertIn(needle, text)

    def test_bare_skill_name_matches_too(self):
        events = [init(), tool("Skill", skill="structured-debug"), result()]
        self.assertIs(self.judge(events, NEGATIVE)["passed"], False)

    def test_other_plugin_skill_of_the_same_name_does_not_match(self):
        events = [init(), tool("Skill", skill="other:structured-debug"), result()]
        self.assertIs(self.judge(events, NEGATIVE)["passed"], True)

    def test_firing_probe_passes_only_when_the_skill_fired(self):
        self.assertIs(self.judge(FIRED, FIRING)["passed"], True)
        verdict = self.judge(QUIET, FIRING)
        self.assertIs(verdict["passed"], False)
        self.assertIn("route-and-map", "\n".join(verdict["failures"]))

    def test_firing_probe_fails_on_a_zero_count(self):
        events = FIRED[:-1] + [tool("Agent", prompt="x"), result()]
        self.assertIs(self.judge(events, FIRING)["passed"], False)

    def test_absent_zero_keys_are_not_checked(self):
        self.assertIs(self.judge(NOISY, {"skill": "clarify", "fires": False})["passed"], True)

    def test_agent_false_is_not_checked(self):
        events = [init(), tool("Agent", prompt="x"), result()]
        self.assertIs(self.judge(events, {"skill": "clarify", "fires": False,
                                          "zero": {"agent": False}})["passed"], True)

    def test_a_run_with_an_error_fails_with_the_error_stated(self):
        verdict = self.judge(QUIET[:2], NEGATIVE, extra_lines=[LIMIT_LINE])
        self.assertIs(verdict["passed"], False)
        self.assertTrue(any("weekly limit" in f for f in verdict["failures"]), verdict)

    def test_no_expectation_judges_nothing(self):
        verdict = self.judge(NOISY, None)
        self.assertIsNone(verdict["passed"])
        self.assertEqual(verdict["failures"], [])

    def test_a_malformed_expectation_is_refused(self):
        for bad in ({"fires": False}, {"skill": "x", "fires": "no"},
                    {"skill": "x", "fires": False, "zero": {"grep": []}},
                    {"skill": "x", "fires": False, "zero": {"bash": "signals"}},
                    {"skill": "x", "fires": False, "zero": {"bash": ["("]}}):
            with self.assertRaises(probe.ProbeError, msg=bad):
                probe.check_expect(bad)


class TestSavedResult(TmpDir):
    def judge_cli(self, expect, *streams, code=0):
        out = self.tmp / "results" / "probes" / "2026-11-25T10-00-00Z" / "11-neg-one-line-change.json"
        args = ["judge", "--case", "11-neg-one-line-change", "--model", "claude-fable-5-2",
                "--plugin-dir", self.plugin, "--out", out]
        if expect is not None:
            args += ["--expect", self.expect(expect)]
        proc = self.cli(*args, *streams, code=code)
        return proc, out

    def test_all_runs_pass_and_the_file_holds_model_cost_and_time(self):
        quiet = [self.stream(QUIET, f"run{k}.jsonl") for k in (1, 2, 3)]
        proc, out = self.judge_cli(NEGATIVE, *quiet)
        saved = json.loads(out.read_text())
        self.assertEqual(saved["case"], "11-neg-one-line-change")
        self.assertEqual(saved["model"], "claude-fable-5-2")
        self.assertEqual((saved["plugin"], saved["version"]), ("shipgate", "1.2.3"))
        self.assertEqual(saved["expect"], NEGATIVE)
        self.assertIs(saved["passed"], True)
        self.assertEqual([r["run"] for r in saved["runs"]], [1, 2, 3])
        first = saved["runs"][0]
        self.assertEqual(first["skills"], [])
        self.assertEqual(first["turns"], 3)
        self.assertEqual(first["cost"], 0.08)
        self.assertEqual(first["seconds"], 12.0)
        self.assertIs(first["passed"], True)
        self.assertIsNone(first["error"])
        self.assertEqual(first["counts"]["bash"], {"signals\\.py": 0, "codegraph": 0})
        self.assertAlmostEqual(saved["cost"], 0.24)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(lines[0], "11-neg-one-line-change run1: PASS skill=[] bash{signals\\.py}=0 "
                                   "bash{codegraph}=0 agent=0 edit{docs/}=0 edit{CLAUDE\\.md}=0 "
                                   "write=0 turns=3 cost=$0.08 12s")

    def test_one_failing_run_fails_the_case(self):
        streams = [self.stream(QUIET, "run1.jsonl"), self.stream(NOISY, "run2.jsonl"),
                   self.stream(QUIET[:2], "run3.jsonl", extra_lines=[LIMIT_LINE])]
        proc, out = self.judge_cli(NEGATIVE, *streams)
        saved = json.loads(out.read_text())
        self.assertIs(saved["passed"], False)
        self.assertEqual([r["passed"] for r in saved["runs"]], [True, False, False])
        self.assertIn("weekly limit", saved["runs"][2]["error"])
        self.assertIsNone(saved["runs"][2]["cost"])
        self.assertAlmostEqual(saved["cost"], 0.39)
        self.assertIn("run2: FAIL", proc.stdout)
        self.assertIn("weekly limit", proc.stdout)

    def test_count_only_without_an_expectation(self):
        proc, out = self.judge_cli(None, self.stream(NOISY))
        saved = json.loads(out.read_text())
        self.assertIsNone(saved["expect"])
        self.assertIsNone(saved["passed"])
        self.assertIsNone(saved["runs"][0]["passed"])
        self.assertEqual(saved["runs"][0]["skills"], ["shipgate:structured-debug", "verify"])
        self.assertIn("run1: skill=[shipgate:structured-debug, verify] bash=3 agent=2 edit=3 "
                      "write=1 turns=9 cost=$0.31 46s", proc.stdout)

    def test_input_errors_exit_1(self):
        self.judge_cli(NEGATIVE, self.tmp / "missing.jsonl", code=1)
        bad = self.tmp / "bad.json"
        bad.write_text("{not json")
        out = self.tmp / "x.json"
        self.cli("judge", "--case", "c", "--model", "m", "--plugin-dir", self.plugin,
                 "--expect", bad, "--out", out, self.stream(QUIET), code=1)
        self.cli("judge", "--case", "c", "--model", "m", "--plugin-dir", self.tmp / "nowhere",
                 "--out", out, self.stream(QUIET), code=1)
        self.assertFalse(out.exists())


    def test_check_validates_probe_json_files(self):
        self.cli("check", self.expect(NEGATIVE), self.expect(FIRING, "firing.json"))
        proc = self.cli("check", self.expect({"skill": "x", "fires": "no"}, "bad.json"), code=1)
        self.assertIn("fires", proc.stderr)


STUB_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "home": os.environ.get("HOME"),
                         "config": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\\n")
sys.stdout.write(open(os.environ["STUB_STREAM"]).read())
"""

STUB_EVALRUN = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_EVALRUN_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("STUB_EVALRUN_EXIT", "0") != "0":
    print("a plugin named shipgate is installed", file=sys.stderr)
sys.exit(int(os.environ.get("STUB_EVALRUN_EXIT", "0")))
"""


class TestProbeSh(unittest.TestCase):
    """probe.sh with a stub `claude` on PATH: no real Claude session, no spend."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plugin = self.tmp / "shipgate"
        evals = self.plugin / "evals"
        (self.plugin / ".claude-plugin").mkdir(parents=True)
        (self.plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "shipgate", "version": "1.2.3"}))
        evals.mkdir()
        shutil.copy(PROBE, evals / "probe.py")
        (evals / "evalrun.py").write_text(STUB_EVALRUN)
        neg = evals / "11-neg-probe"
        neg.mkdir()
        (neg / "probe.md").write_text("---\nnote: frontmatter\n---\nRename x to y.\n")
        (neg / "probe.json").write_text(json.dumps(NEGATIVE))
        old = evals / "12-old-case"
        old.mkdir()
        (old / "prompt.md").write_text("---\nruns: 3\n---\nExplain this.\n")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        claude = self.bin / "claude"
        claude.write_text(STUB_CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        (self.tmp / "home").mkdir()
        self.log = self.tmp / "claude.log"
        self.evalrun_log = self.tmp / "evalrun.log"
        self.stream = self.tmp / "stream.jsonl"
        self.stream.write_text("".join(json.dumps(e) + "\n" for e in QUIET))

    def run_sh(self, *args, env=None):
        full = {k: v for k, v in os.environ.items()
                if k not in ("CLAUDE_CONFIG_DIR", "EVAL_CONFIG_DIR", "CLAUDECODE")}
        full.update({"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                     "HOME": str(self.tmp / "home"), "TMPDIR": str(self.tmp),
                     "EVAL_SKIP_GIT_CHECK": "1", "STUB_LOG": str(self.log),
                     "STUB_STREAM": str(self.stream), "STUB_EVALRUN_LOG": str(self.evalrun_log)})
        full.update(env or {})
        bash = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
        return subprocess.run([bash, str(PROBE_SH), *map(str, args)], capture_output=True,
                              text=True, env=full, check=False)

    def claude_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def saved(self, case):
        found = sorted((self.plugin / "evals" / "results" / "probes").glob(f"*/{case}.json"))
        self.assertEqual(len(found), 1, found)
        return json.loads(found[0].read_text())

    def test_no_model_exits_64_before_any_call(self):
        proc = self.run_sh("--config-dir", self.cfg, self.plugin, "11")
        self.assertEqual(proc.returncode, 64, proc.stderr)
        self.assertIn("--model", proc.stderr)
        self.assertEqual(self.claude_calls(), [])
        self.assertFalse(self.evalrun_log.exists())

    def test_a_failed_config_check_exits_1_before_any_call(self):
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "11",
                           env={"STUB_EVALRUN_EXIT": "1"})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.claude_calls(), [])
        argv = json.loads(self.evalrun_log.read_text().splitlines()[0])
        self.assertEqual(argv[:4], ["config-check", "--config-dir", str(self.cfg), "--plugin-dir"])
        self.assertEqual(Path(argv[4]).resolve(), self.plugin.resolve())

    def test_a_bad_probe_json_exits_1_before_any_call(self):
        (self.plugin / "evals" / "11-neg-probe" / "probe.json").write_text('{"skill": "x"}')
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "11")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.claude_calls(), [])

    def test_one_case_runs_with_the_model_and_saves_the_result(self):
        proc = self.run_sh("--config-dir", self.cfg, "--model", "claude-fable-5-2", self.plugin, "11", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.claude_calls()
        self.assertEqual(len(calls), 2)
        argv = calls[0]["argv"]
        self.assertEqual(argv[:2], ["-p", "Rename x to y."])
        self.assertEqual(argv[argv.index("--model") + 1], "claude-fable-5-2")
        self.assertEqual(Path(argv[argv.index("--plugin-dir") + 1]).resolve(), self.plugin.resolve())
        for flag in ("--strict-mcp-config", "--verbose", "--allowedTools", "--max-turns"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(calls[0]["config"], str(self.cfg))
        self.assertNotEqual(calls[0]["home"], str(self.tmp / "home"))
        saved = self.saved("11-neg-probe")
        self.assertEqual(saved["model"], "claude-fable-5-2")
        self.assertIs(saved["passed"], True)
        self.assertEqual(len(saved["runs"]), 2)
        self.assertIn("11-neg-probe run1: PASS skill=[]", proc.stdout)
        self.assertIn("result: ", proc.stdout)

    def test_flags_may_follow_the_case(self):
        proc = self.run_sh(self.plugin, "11", "1", "--model", "m", "--config-dir", self.cfg)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        argv = self.claude_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "m")

    def test_default_runs_is_3(self):
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "11")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(self.claude_calls()), 3)

    def test_a_case_without_probe_json_runs_count_only(self):
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "12", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.claude_calls()[0]["argv"][1], "Explain this.")
        saved = self.saved("12-old-case")
        self.assertIsNone(saved["expect"])
        self.assertIsNone(saved["passed"])

    def test_probes_set_needs_a_sets_file(self):
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "probes")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("sets.json", proc.stderr)
        self.assertEqual(self.claude_calls(), [])

    def probes_sets(self, sets):
        """The real evalrun.py (its set-cases reads the probes list) and a sets.json."""
        shutil.copy(EVALRUN, self.plugin / "evals" / "evalrun.py")
        (self.plugin / "evals" / "sets.json").write_text(json.dumps(sets))

    @unittest.skipUnless(EVALRUN.exists(), "evals/evalrun.py is not written yet")
    def test_probes_set_runs_every_listed_case(self):
        self.probes_sets({"kept": ["11-neg-probe"], "probes": ["11-neg-probe", "12-old-case"]})
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "probes", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(self.claude_calls()), 2)
        self.assertIs(self.saved("11-neg-probe")["passed"], True)
        self.assertIsNone(self.saved("12-old-case")["passed"])

    @unittest.skipUnless(EVALRUN.exists(), "evals/evalrun.py is not written yet")
    def test_probes_set_refusals_of_set_cases_apply_before_any_call(self):
        cases = {
            "parked": {"probes": ["11-neg-probe", "12-old-case"], "parked": ["12-old-case"]},
            "twice": {"probes": ["11-neg-probe", "11-neg-probe"]},
            "empty": {"probes": []},
            "no probes": {"kept": ["11-neg-probe"]},
        }
        for what, sets in cases.items():
            with self.subTest(what):
                self.probes_sets(sets)
                proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "probes", "1")
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn("evalrun: set-cases:", proc.stderr)
                self.assertEqual(self.claude_calls(), [])

    def test_runs_and_max_turns_must_be_whole_numbers_above_0(self):
        for extra in (["0"], ["abc"], ["2", "0"], ["2", "x"], ["-1"]):
            with self.subTest(extra=extra):
                proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "11", *extra)
                self.assertEqual(proc.returncode, 64, proc.stdout + proc.stderr)
                self.assertIn("whole number above 0", proc.stderr)
                self.assertEqual(self.claude_calls(), [])
                self.assertFalse(self.evalrun_log.exists())

    @unittest.skipUnless(EVALRUN.exists(), "evals/evalrun.py is not written yet")
    def test_a_same_name_install_in_the_config_dir_exits_1_before_any_call(self):
        shutil.copy(EVALRUN, self.plugin / "evals" / "evalrun.py")
        (self.cfg / "plugins").mkdir()
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"shipgate@x": [
                {"scope": "user", "version": "1.0.0", "installPath": "/nowhere"}]}}))
        proc = self.run_sh("--config-dir", self.cfg, "--model", "m", self.plugin, "11")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.claude_calls(), [])
        self.assertIn("shipgate", proc.stderr)


if __name__ == "__main__":
    unittest.main()
