"""Contract tests for evals/evalrun.py and the run-evals run scripts (ADR 0035, ADR 0036).

No test spends money. The run scripts see a stub `claude` first on PATH: it records its
argv and, for `plugin eval`, writes a fake results dir with canned traces. Every
subprocess gets a temp HOME and a temp config dir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
REPO = SHIPGATE.parent
EVALRUN = SHIPGATE / "evals" / "evalrun.py"
SCRIPTS = REPO / ".claude" / "skills" / "run-evals" / "scripts"
RUN_CASE = SCRIPTS / "run-case.sh"
BASH = "/bin/bash" if os.path.exists("/bin/bash") else "bash"

STUB_CLAUDE = r'''#!/usr/bin/env python3
import fnmatch, json, os, sys, tempfile, time
argv = sys.argv[1:]
with open(os.environ["STUB_ARGV_FILE"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")
if argv[:2] != ["plugin", "eval"]:
    sys.exit(0)
if os.environ.get("STUB_ABORT"):
    print("stub: aborted before any result", file=sys.stderr)
    sys.exit(3)
target = argv[2]
def opt(name, default=None):
    hits = [i for i, a in enumerate(argv) if a == name]
    return argv[hits[-1] + 1] if hits else default
case_glob = opt("--case", "*")
ablation = opt("--ablation", "with-without")
runs = int(opt("--runs", "1"))
model = opt("--model")
with open(os.path.join(target, ".claude-plugin", "plugin.json")) as fh:
    manifest = json.load(fh)
evals = os.path.join(target, "evals")
cost, judge = 0.5, 0.1
sandbox_root = os.environ["STUB_SANDBOX_ROOT"]
arms = ["with", "without"] if ablation == "with-without" else ["with"]
cases = []
for name in sorted(os.listdir(evals)):
    if name == "results" or not fnmatch.fnmatch(name, case_glob) or not os.path.isdir(os.path.join(evals, name)):
        continue
    arm_runs = {}
    for arm in arms:
        arm_runs[arm] = []
        for _ in range(runs):
            sandbox = tempfile.mkdtemp(prefix="e-", dir=sandbox_root)
            os.makedirs(os.path.join(sandbox, "out"))
            trace = os.path.join(sandbox, "out", "trace.jsonl")
            plugins = []
            if arm == "with":
                plugins = [{"name": manifest["name"], "path": target, "version": manifest["version"]}]
            with open(trace, "w") as fh:
                fh.write(json.dumps({"type": "system", "subtype": "init", "model": model, "plugins": plugins}) + "\n")
                fh.write(json.dumps({"type": "result", "num_turns": 2, "total_cost_usd": cost, "is_error": False, "result": "done"}) + "\n")
            arm_runs[arm].append({"score": 1.0, "passed": True, "turns": 2, "costUsd": cost, "judgeCostUsd": judge,
                                  "durationSeconds": 1, "error": None, "tracePath": trace, "graders": []})
    cases.append({"name": name, "dir": name, "graders": [], "arms": arm_runs,
                  "aggregates": {"score": 1.0, "passRate": 1.0}})
out = os.path.join(evals, "results", time.strftime("%Y-%m-%dT%H-%M-%S") + "-%d" % os.getpid())
os.makedirs(out)
suite = {"ablation": ablation, "judgeModel": "sonnet", "root": evals, "caseFilter": case_glob,
         "plugins": [{"name": manifest["name"], "path": target, "version": manifest["version"]}]}
if model:
    suite["modelOverride"] = model
agg = {"schemaVersion": 1, "claudeVersion": "0.0.0-stub", "costUsd": 0, "durationSeconds": 1, "partial": False,
       "suite": suite, "cases": cases}
with open(os.path.join(out, "aggregate-result.json"), "w") as fh:
    json.dump(agg, fh)
if not os.environ.get("STUB_NO_REPORT"):
    print("Report: %s/report.html" % out)
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
'''

HARNESS_FLAGS = ["--runs", "3"]
TODAY_TAIL = ["--scaffold", "--judge-model", "sonnet", "--no-publish", "--allow-tools", "Bash", "Edit", "Write"]


def path_without_claude(path):
    keep = []
    for d in path.split(os.pathsep):
        if d and os.access(os.path.join(d, "claude"), os.X_OK):
            continue
        keep.append(d)
    return os.pathsep.join(keep)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def make_plugin(root, name="shipgate", version="9.9.9", cases=("05-x",)):
    plug = Path(root) / "plug"
    write_json(plug / ".claude-plugin" / "plugin.json", {"name": name, "version": version})
    for c in cases:
        (plug / "evals" / c).mkdir(parents=True)
        (plug / "evals" / c / "prompt.md").write_text("a prompt\n")
    (plug / "evals" / "evalrun.py").symlink_to(EVALRUN)
    return plug


class StubEnv(unittest.TestCase):
    """A temp world: plugin dir, config dir, HOME, sandbox root and a stub `claude`."""

    cases = ("05-x",)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plug = make_plugin(self.tmp, cases=self.cases)
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.sandboxes = self.tmp / "sandboxes"
        self.sandboxes.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.stub = self.bin / "claude"
        self.stub.write_text(STUB_CLAUDE)
        self.stub.chmod(0o755)
        self.argv_file = self.tmp / "argv.jsonl"
        self.env = {
            "PATH": str(self.bin) + os.pathsep + path_without_claude(os.environ.get("PATH", "/usr/bin:/bin")),
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.cfg),
            "EVAL_CONFIG_DIR": str(self.cfg),
            "EVAL_SKIP_GIT_CHECK": "1",
            "STUB_ARGV_FILE": str(self.argv_file),
            "STUB_SANDBOX_ROOT": str(self.sandboxes),
            "LANG": "C",
        }
        if os.environ.get("TMPDIR"):
            self.env["TMPDIR"] = os.environ["TMPDIR"]
        self.assertEqual(shutil.which("claude", path=self.env["PATH"]), str(self.stub))

    def run_script(self, script, *args, **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run([BASH, str(script)] + [str(a) for a in args], env=e,
                              capture_output=True, text=True, timeout=120)

    def argvs(self):
        if not self.argv_file.exists():
            return []
        return [json.loads(line) for line in self.argv_file.read_text().splitlines() if line]


MODEL = "claude-test-1"


class TestRunCaseArgv(StubEnv):
    def results_dirs(self):
        root = self.plug / "evals" / "results"
        return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []

    def test_argv_pin(self):
        r = self.run_script(RUN_CASE, "--config-dir", self.cfg, "--ablation", "with-without", "--model", MODEL, self.plug, "05")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.argvs(), [
            ["plugin", "eval", str(self.plug), "--runs", "3", "--ablation", "with-without"]
            + TODAY_TAIL + ["--model", MODEL, "--keep-temp", "--case", "05-*"]])
        self.assertIn("mode=with-without", r.stderr)
        self.assertIn("model=" + MODEL, r.stderr)
        self.assertIn("--ablation with-without", r.stderr)
        self.assertIn("--model " + MODEL, r.stderr)
        (res,) = self.results_dirs()
        self.assertIn("run-evals: results dir: %s" % res, r.stdout)
        shadow = json.loads((res / "shadow.json").read_text())
        self.assertIs(shadow["shadowed"], False)
        self.assertEqual(len(shadow["runs"]), 6)
        self.assertFalse((res / "bare.json").exists())

    def test_a_full_case_name_is_the_case_filter(self):
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05-x")
        self.assertEqual(r.returncode, 0, r.stderr)
        (argv,) = self.argvs()
        self.assertEqual(argv[argv.index("--case") + 1], "05-x")

    def test_a_case_yaml_case_is_a_full_name(self):
        d = self.plug / "evals" / "07-yaml-only"
        d.mkdir()
        (d / "case.yaml").write_text("prompt: a prompt\n")
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "07-yaml-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        (argv,) = self.argvs()
        self.assertEqual(argv[argv.index("--case") + 1], "07-yaml-only")

    def test_a_prefix_is_the_nn_filter(self):
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05")
        self.assertEqual(r.returncode, 0, r.stderr)
        (argv,) = self.argvs()
        self.assertEqual(argv[argv.index("--case") + 1], "05-*")

    def test_extra_flags_pass_through_and_keep_temp_once(self):
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05", "--runs", "1", "--keep-temp")
        self.assertEqual(r.returncode, 0, r.stderr)
        (argv,) = self.argvs()
        self.assertEqual(argv.count("--keep-temp"), 1)
        self.assertEqual(argv[-3:], ["--runs", "1", "--keep-temp"])
        self.assertEqual(argv[argv.index("--ablation") + 1], "none")

    def test_an_aborted_harness_keeps_its_status_and_says_so(self):
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05", STUB_ABORT="1")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("no new dir under", r.stderr)

    def test_no_report_line_falls_back_to_the_dir_listing(self):
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05", STUB_NO_REPORT="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (res,) = self.results_dirs()
        self.assertIn("run-evals: results dir: %s" % res, r.stdout)
        self.assertTrue((res / "shadow.json").exists())

    def test_harness_status_stands(self):
        r = self.run_script(RUN_CASE, "--ablation", "with-without", "--model", MODEL, self.plug, "05", STUB_EXIT="1")
        self.assertEqual(r.returncode, 1, r.stderr)
        (res,) = self.results_dirs()
        self.assertTrue((res / "shadow.json").exists())

    def temp_root_traces(self, *extra):
        self.env["STUB_SANDBOX_ROOT"] = tempfile.gettempdir()
        r = self.run_script(RUN_CASE, "--ablation", "none", "--model", MODEL, self.plug, "05", "--runs", "2", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        (res,) = self.results_dirs()
        agg = json.loads((res / "aggregate-result.json").read_text())
        traces = [run["tracePath"] for c in agg["cases"] for runs in c["arms"].values() for run in runs]
        for t in traces:
            self.addCleanup(shutil.rmtree, os.path.dirname(os.path.dirname(t)), True)
        self.assertEqual(len(traces), 2)
        return traces

    def test_removes_kept_sandboxes_after_the_checks(self):
        for t in self.temp_root_traces():
            self.assertFalse(os.path.exists(os.path.dirname(os.path.dirname(t))), t)

    def test_keeps_sandboxes_when_the_caller_asks(self):
        for t in self.temp_root_traces("--keep-temp"):
            self.assertTrue(os.path.exists(t), t)

    def test_bare_run_goes_through_the_stub(self):
        r = self.run_script(RUN_CASE, "--bare", "--model", MODEL, self.plug, "05")
        self.assertEqual(r.returncode, 0, r.stderr)
        (argv,) = self.argvs()
        target = argv[2]
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(self.plug))
        self.assertFalse(os.path.exists(target), "the stub dir is removed on exit")
        self.assertEqual(argv[argv.index("--ablation") + 1], "none")
        self.assertEqual(argv[argv.index("--model") + 1], MODEL)
        self.assertIn("--keep-temp", argv)
        self.assertIn("mode=bare", r.stderr)
        self.assertTrue((self.plug / "evals" / "05-x" / "prompt.md").exists())
        (res,) = self.results_dirs()
        line = [l for l in r.stdout.splitlines() if l.startswith("run-evals: results dir: ")]
        self.assertEqual(len(line), 1, r.stdout)
        printed = line[0].split(": ", 2)[2]
        self.assertTrue(os.path.isdir(printed), printed)
        self.assertEqual(os.path.realpath(printed), os.path.realpath(res))
        self.assertEqual(json.loads((res / "bare.json").read_text()),
                         {"arm": "bare", "plugin": "shipgate", "stub": "shipgate-bare", "version": "9.9.9"})
        shadow = json.loads((res / "shadow.json").read_text())
        self.assertIs(shadow["shadowed"], False)
        self.assertEqual({x["arm"] for x in shadow["runs"]}, {"without"})


class TestRunCaseRefusals(StubEnv):
    """SC-004: each refusal exits non-zero before the stub `claude` runs."""

    def refused(self, *args, status=64):
        r = self.run_script(RUN_CASE, *args)
        self.assertEqual(r.returncode, status, r.stderr)
        self.assertFalse(self.argv_file.exists(), "the stub claude ran")
        return r

    def test_no_mode(self):
        r = self.refused("--model", MODEL, self.plug, "05")
        self.assertIn("--ablation", r.stderr)
        self.assertIn("--bare", r.stderr)

    def test_both_modes(self):
        self.refused("--ablation", "none", "--bare", "--model", MODEL, self.plug, "05")

    def test_bad_ablation(self):
        self.refused("--ablation", "both", "--model", MODEL, self.plug, "05")

    def test_no_model(self):
        r = self.refused("--ablation", "with-without", self.plug, "05")
        self.assertIn("--model", r.stderr)

    def test_mode_flag_among_the_extra_flags(self):
        self.refused("--model", MODEL, "--bare", self.plug, "05", "--ablation", "with-without")
        self.refused("--ablation", "none", "--model", MODEL, self.plug, "05", "--model", "other")

    def test_a_dir_that_is_not_an_eval_case_is_refused(self):
        probe = self.plug / "evals" / "40-probe"
        probe.mkdir()
        (probe / "probe.md").write_text("a probe\n")
        write_json(probe / "probe.json", {"skill": "x"})
        (self.plug / "evals" / "results").mkdir()
        for arg in ("40-probe", "results", ".", ".."):
            with self.subTest(arg=arg):
                r = self.refused("--ablation", "none", "--model", MODEL, self.plug, arg)
                self.assertIn("not an eval case", r.stderr.splitlines()[0])

    def test_an_empty_case_is_refused(self):
        self.refused("--ablation", "none", "--model", MODEL, self.plug, "")

    def test_same_name_install(self):
        write_json(self.cfg / "plugins" / "installed_plugins.json", {"version": 2, "plugins": {
            "shipgate@market": [{"scope": "user", "installPath": "/c", "version": "0.36.0"}]}})
        r = self.refused("--config-dir", self.cfg, "--ablation", "with-without", "--model", MODEL, self.plug, "05", status=1)
        self.assertIn("shipgate@market", r.stderr)

    def test_same_name_enabled(self):
        write_json(self.cfg / "settings.json", {"enabledPlugins": {"shipgate@market": True}})
        self.refused("--config-dir", self.cfg, "--bare", "--model", MODEL, self.plug, "05", status=1)


# --------------------------------------------------------------------------
# evalrun.py


def evalrun(*args, timeout=120):
    return subprocess.run(["python3", str(EVALRUN)] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=timeout)


def snapshot(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            out[os.path.relpath(os.path.join(dirpath, d), root)] = None
        for f in filenames:
            full = os.path.join(dirpath, f)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root)] = (fh.read(), os.stat(full).st_mtime_ns)
    return out


def init_record(plugins, model="claude-test-1"):
    return {"type": "system", "subtype": "init", "model": model, "plugins": plugins}


class EvalrunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plug = make_plugin(self.tmp, cases=("05-x", "06-y"))
        self.tree = os.path.realpath(self.plug)
        self.results = self.plug / "evals" / "results" / "stamp-1"
        self.results.mkdir(parents=True)
        self.n = 0

    def trace(self, records, root=None, name=None):
        """A kept sandbox <root>/e-*/out/trace.jsonl holding `records`; returns its path."""
        self.n += 1
        root = Path(root) if root else self.tmp / "sandboxes"
        sandbox = root / (name or "e-run%d" % self.n)
        (sandbox / "out").mkdir(parents=True)
        path = sandbox / "out" / "trace.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return str(path)

    def write_result(self, cases, ablation="with-without"):
        """cases: {case: {arm: [tracePath or None, ...]}}."""
        out = []
        for name, arms in cases.items():
            out.append({"name": name, "dir": name, "graders": [], "aggregates": {},
                        "arms": {arm: [{"score": 1.0, "passed": True, "costUsd": 0.5, "judgeCostUsd": 0.1,
                                        "tracePath": t, "graders": []} for t in traces]
                                 for arm, traces in arms.items()}})
        write_json(self.results / "aggregate-result.json", {
            "suite": {"ablation": ablation, "plugins": [{"name": "shipgate", "path": str(self.plug), "version": "9.9.9"}]},
            "cases": out})

    def post_run(self, *extra, **kw):
        return evalrun("post-run", self.results, "--plugin-dir", self.plug, *extra, **kw)

    def read(self, name):
        return json.loads((self.results / name).read_text())


class TestConfigCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plug = make_plugin(self.tmp)
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()

    def check(self):
        before = snapshot(self.cfg)
        r = evalrun("config-check", "--config-dir", self.cfg, "--plugin-dir", self.plug)
        self.assertEqual(snapshot(self.cfg), before, "config-check must never write the config dir")
        return r

    def installed(self, plugins):
        write_json(self.cfg / "plugins" / "installed_plugins.json", {"version": 2, "plugins": plugins})

    def assert_fix(self, err):
        self.assertIn("--config-dir", err)
        self.assertIn("EVAL_CONFIG_DIR", err)
        self.assertIn("uninstall", err)

    def test_missing_files_are_clean(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_user_install_refused(self):
        self.installed({"shipgate@market": [{"scope": "user", "installPath": "/cache/shipgate/0.36.0", "version": "0.36.0"}]})
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("shipgate@market", r.stderr)
        self.assertIn("user", r.stderr)
        self.assertIn("0.36.0", r.stderr)
        self.assert_fix(r.stderr)

    def test_project_scope_install_refused(self):
        self.installed({"shipgate@market": [{"scope": "project", "projectPath": "/p", "installPath": "/c", "version": "0.35.0"},
                                            {"scope": "local", "installPath": "/c", "version": "0.34.0"}]})
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("project", r.stderr)
        self.assertIn("local", r.stderr)
        self.assertIn("0.35.0", r.stderr)
        self.assertIn("0.34.0", r.stderr)

    def test_enabled_plugin_refused(self):
        write_json(self.cfg / "settings.json", {"enabledPlugins": {"shipgate@market": True}})
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("shipgate@market", r.stderr)
        self.assertIn("enabledPlugins", r.stderr)
        self.assert_fix(r.stderr)

    def test_disabled_plugin_is_clean(self):
        write_json(self.cfg / "settings.json", {"enabledPlugins": {"shipgate@market": False}})
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_prefix_name_is_not_the_plugin(self):
        self.installed({"shipgate-hud@market": [{"scope": "user", "installPath": "/c", "version": "0.4.0"}]})
        write_json(self.cfg / "settings.json", {"enabledPlugins": {"shipgate-hud@market": True}})
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unreadable_plugin_manifest_is_a_usage_error(self):
        (self.plug / ".claude-plugin" / "plugin.json").unlink()
        r = evalrun("config-check", "--config-dir", self.cfg, "--plugin-dir", self.plug)
        self.assertEqual(r.returncode, 2, r.stderr)


class TestShadow(EvalrunCase):
    def test_with_without_result(self):
        own = {"name": "shipgate", "path": str(self.plug), "version": "9.9.9"}
        link = self.tmp / "link-to-plug"
        link.symlink_to(self.plug)
        self.write_result({
            "05-x": {
                "with": [
                    self.trace([init_record([own, {"name": "other", "path": "/o", "version": "1"}])]),
                    self.trace([init_record([{"name": "shipgate", "path": "/cache/shipgate/0.36.0", "version": "0.36.0"}])]),
                    None,
                    self.trace([init_record([{"name": "shipgate", "path": str(link)}])]),
                    self.trace([init_record([dict(own, version="0.36.0")])]),
                    self.trace([init_record([{"name": "shipgate-hud", "path": "/h", "version": "1"}])]),
                    self.trace([{"type": "result", "result": "x"}]),
                ],
                "without": [
                    self.trace([init_record([])]),
                    self.trace([init_record([{"name": "shipgate", "path": "/cache/shipgate/0.36.0", "version": "0.36.0"}])]),
                ],
            }})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.read("shadow.json")
        self.assertEqual((s["plugin"], s["tree"], s["version"], s["shadowed"]), ("shipgate", self.tree, "9.9.9", True))
        got = [(x["case"], x["arm"], x["run"], x["shadowed"]) for x in s["runs"]]
        self.assertEqual(got, [
            ("05-x", "with", 1, False), ("05-x", "with", 2, True), ("05-x", "with", 3, None),
            ("05-x", "with", 4, False), ("05-x", "with", 5, True), ("05-x", "with", 6, True),
            ("05-x", "with", 7, None),
            ("05-x", "without", 1, False), ("05-x", "without", 2, True)])
        self.assertEqual(s["runs"][1]["loaded"], [{"path": "/cache/shipgate/0.36.0", "version": "0.36.0"}])
        self.assertEqual(s["runs"][0]["loaded"], [{"path": str(self.plug), "version": "9.9.9"}])
        for x in s["runs"]:
            self.assertTrue(x["reason"] and "\n" not in x["reason"], x)
        self.assertEqual(r.stderr.count("SHADOWED"), 4, r.stderr)
        self.assertFalse((self.results / "bare.json").exists())
        self.assertFalse((self.results / "script-graders.json").exists())

    def test_clean_result_is_not_shadowed(self):
        own = {"name": "shipgate", "path": str(self.plug), "version": "9.9.9"}
        self.write_result({"05-x": {"with": [self.trace([init_record([own])])], "without": [self.trace([init_record([])])]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(self.read("shadow.json")["shadowed"], False)
        self.assertNotIn("SHADOWED", r.stderr)

    def test_the_tree_itself_in_the_without_arm_is_shadowed(self):
        own = [init_record([{"name": "shipgate", "path": str(self.plug), "version": "9.9.9"}])]
        self.write_result({"05-x": {"with": [self.trace(own)], "without": [self.trace(own)]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.read("shadow.json")
        self.assertEqual([(x["arm"], x["shadowed"]) for x in s["runs"]], [("with", False), ("without", True)])
        self.assertIs(s["shadowed"], True)

    def test_bare_result(self):
        stub = {"name": "shipgate-bare", "path": str(self.tmp / "stub"), "version": "9.9.9"}
        self.write_result({"05-x": {"with": [
            self.trace([init_record([stub])]),
            self.trace([init_record([stub, {"name": "shipgate", "path": "/cache/shipgate", "version": "0.36.0"}])]),
        ]}}, ablation="none")
        r = self.post_run("--bare")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.read("shadow.json")
        self.assertEqual([(x["arm"], x["run"], x["shadowed"]) for x in s["runs"]],
                         [("without", 1, False), ("without", 2, True)])
        self.assertEqual(self.read("bare.json"),
                         {"arm": "bare", "plugin": "shipgate", "stub": "shipgate-bare", "version": "9.9.9"})

    def test_bare_json_is_written_before_the_shadow_pass(self):
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}}, ablation="none")
        (self.results / "shadow.json").mkdir()
        r = self.post_run("--bare")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertTrue((self.results / "bare.json").is_file(), r.stdout + r.stderr)

    def test_missing_result_is_an_input_error(self):
        r = self.post_run()
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.results / "shadow.json").exists())


SCRIPT_PASS = 'import sys\nprint("init seen" if "init" in open(sys.argv[1]).read() else "no init")\nsys.exit(0)\n'
SCRIPT_FAIL = 'import sys\nopen(sys.argv[1]).read()\nprint("the last test ran before the last edit")\nprint("second line")\nsys.exit(1)\n'
SCRIPT_CRASH = 'import sys\nsys.exit(3)\n'
SCRIPT_SLOW = 'import time\ntime.sleep(30)\n'
SCRIPT_RAISE = 'raise ValueError("no result record in the trace")\n'


class TestScriptGraders(EvalrunCase):
    def add_graders(self, case, **scripts):
        d = self.plug / "evals" / case / "script-graders"
        d.mkdir(parents=True)
        for name, body in scripts.items():
            (d / (name + ".py")).write_text(body)

    def test_results_per_run_and_grader(self):
        self.add_graders("05-x", a_pass=SCRIPT_PASS, b_fail=SCRIPT_FAIL, c_crash=SCRIPT_CRASH)
        self.write_result({"05-x": {"with": [self.trace([init_record([])])], "without": [None]},
                           "06-y": {"with": [self.trace([init_record([])])]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.read("script-graders.json")["runs"]
        got = [(x["case"], x["arm"], x["run"], x["grader"], x["passed"]) for x in runs]
        self.assertEqual(got, [
            ("05-x", "with", 1, "a_pass", True), ("05-x", "with", 1, "b_fail", False), ("05-x", "with", 1, "c_crash", None),
            ("05-x", "without", 1, "a_pass", None), ("05-x", "without", 1, "b_fail", None), ("05-x", "without", 1, "c_crash", None)])
        self.assertEqual(runs[0]["reason"], "init seen")
        self.assertEqual(runs[1]["reason"], "the last test ran before the last edit")
        self.assertEqual(runs[2]["reason"], "exited 3")
        self.assertIn("trace", runs[3]["reason"])

    def one_row(self, body):
        self.add_graders("05-x", g=body)
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        (row,) = self.read("script-graders.json")["runs"]
        return row

    def test_exit_0_is_a_pass(self):
        row = self.one_row(SCRIPT_PASS)
        self.assertEqual((row["passed"], row["reason"]), (True, "init seen"))

    def test_exit_1_with_a_reason_on_stdout_is_a_fail(self):
        row = self.one_row(SCRIPT_FAIL)
        self.assertEqual((row["passed"], row["reason"]), (False, "the last test ran before the last edit"))

    def test_exit_1_with_empty_stdout_is_an_error_with_the_stderr_reason(self):
        bodies = {
            "sys.exit message": ('import sys\nsys.exit("no result record in the trace")\n',
                                 "no result record in the trace"),
            "uncaught exception": ('raise ValueError("no result record in the trace")\n',
                                   "ValueError: no result record in the trace"),
            "syntax error": ("def (:\n", "SyntaxError: invalid syntax"),
            "indentation error": ("if True:\npass\n", "IndentationError: expected an indented block"),
        }
        for what, (body, reason) in bodies.items():
            with self.subTest(what):
                shutil.rmtree(self.plug / "evals" / "05-x" / "script-graders", True)
                row = self.one_row(body)
                self.assertIsNone(row["passed"], row)
                self.assertTrue(row["reason"].startswith(reason), row)

    def test_a_line_on_stdout_then_a_crash_is_a_fail(self):
        row = self.one_row('print("half done")\nraise ValueError("no result record in the trace")\n')
        self.assertEqual((row["passed"], row["reason"]), (False, "half done"))

    def test_exit_1_with_empty_stdout_and_stderr_says_the_exit(self):
        row = self.one_row("import sys\nsys.exit(1)\n")
        self.assertEqual((row["passed"], row["reason"]), (None, "exited 1"))

    def test_exit_2_is_an_error(self):
        row = self.one_row('import sys\nprint("a stdout line")\nprint("usage: g trace", file=sys.stderr)\nsys.exit(2)\n')
        self.assertEqual((row["passed"], row["reason"]), (None, "usage: g trace"))

    def test_an_error_counts_apart_from_a_fail(self):
        self.add_graders("05-x", b_fail=SCRIPT_FAIL, raises=SCRIPT_RAISE)
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.read("script-graders.json")["runs"]
        self.assertEqual([(x["grader"], x["passed"]) for x in runs], [("b_fail", False), ("raises", None)])
        self.assertIn("1 failed, 1 errors", r.stdout)

    def test_bare_runs_are_the_without_arm(self):
        self.add_graders("05-x", a_pass=SCRIPT_PASS)
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}}, ablation="none")
        r = self.post_run("--bare")
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.read("script-graders.json")["runs"]
        self.assertEqual([(x["arm"], x["passed"]) for x in runs], [("without", True)])

    def test_timeout_is_null(self):
        self.add_graders("05-x", slow=SCRIPT_SLOW)
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}})
        r = self.post_run("--script-timeout", "1", timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.read("script-graders.json")["runs"][0]
        self.assertIsNone(run["passed"])
        self.assertIn("timed out", run["reason"])

    def test_no_script_graders_no_file(self):
        self.write_result({"05-x": {"with": [self.trace([init_record([])])]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.results / "script-graders.json").exists())


class TestClean(EvalrunCase):
    def temp_root_sandbox(self, prefix="e-", tail=("out", "trace.jsonl")):
        sandbox = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, sandbox, True)
        path = sandbox.joinpath(*tail)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(init_record([])) + "\n")
        return sandbox, str(path)

    def test_removes_only_harness_sandboxes_under_a_temp_root(self):
        real, real_trace = self.temp_root_sandbox()
        other, other_trace = self.temp_root_sandbox(prefix="x-")
        flat, flat_trace = self.temp_root_sandbox(tail=("trace.jsonl",))
        lookalike = self.trace([init_record([])], root=self.tmp, name="e-lookalike")
        self.write_result({"05-x": {"with": [real_trace, other_trace, flat_trace, lookalike, None]}})
        r = self.post_run("--clean")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(real.exists())
        self.assertTrue(other.exists())
        self.assertTrue(flat.exists())
        self.assertTrue(Path(lookalike).exists())
        self.assertIn("e-lookalike", r.stderr)
        self.assertTrue((self.results / "shadow.json").exists())

    def test_keeps_sandboxes_without_clean(self):
        real, real_trace = self.temp_root_sandbox()
        self.write_result({"05-x": {"with": [real_trace]}})
        r = self.post_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(real.exists())


class TestBareStub(EvalrunCase):
    def test_builds_the_stub(self):
        out = self.tmp / "stub"
        r = evalrun("bare-stub", self.plug, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str(out))
        self.assertEqual(sorted(os.listdir(out)), [".claude-plugin", "evals"])
        self.assertEqual(os.listdir(out / ".claude-plugin"), ["plugin.json"])
        manifest = json.loads((out / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual((manifest["name"], manifest["version"]), ("shipgate-bare", "9.9.9"))
        self.assertTrue(manifest.get("description"))
        self.assertEqual(set(manifest), {"name", "version", "description"})
        self.assertTrue((out / "evals").is_symlink())
        self.assertEqual(os.readlink(out / "evals"), os.path.realpath(self.plug / "evals"))

    def test_empty_out_dir_is_fine(self):
        out = self.tmp / "stub"
        out.mkdir()
        self.assertEqual(evalrun("bare-stub", self.plug, out).returncode, 0)

    def test_refuses_a_non_empty_out_dir(self):
        out = self.tmp / "stub"
        out.mkdir()
        (out / "x").write_text("x")
        r = evalrun("bare-stub", self.plug, out)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(os.listdir(out), ["x"])


class TestSetCases(EvalrunCase):
    def sets(self, obj):
        path = self.tmp / "sets.json"
        write_json(path, obj)
        return path

    def test_prints_the_cases(self):
        r = evalrun("set-cases", self.sets({"kept": ["05-x", "06-y"], "parked": ["78-p"]}), "kept")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["05-x", "06-y"])

    def test_unknown_set_lists_the_sets(self):
        r = evalrun("set-cases", self.sets({"kept": ["05-x"], "guards": ["06-y"]}), "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("guards", r.stderr)
        self.assertIn("kept", r.stderr)

    def test_parked_set_refused(self):
        r = evalrun("set-cases", self.sets({"kept": ["05-x"], "parked": ["78-p"]}), "parked")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")

    def test_a_case_listed_twice_is_refused(self):
        r = evalrun("set-cases", self.sets({"kept": ["05-x", "06-y", "05-x"]}), "kept")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(r.stdout, "")
        self.assertIn("twice", r.stderr)
        self.assertIn("05-x", r.stderr)
        self.assertNotIn("06-y", r.stderr)

    def test_parked_case_in_another_set_refused(self):
        r = evalrun("set-cases", self.sets({"kept": ["05-x", "78-p"], "parked": ["78-p"]}), "kept")
        self.assertEqual(r.returncode, 1)
        self.assertIn("78-p", r.stderr)


if __name__ == "__main__":
    unittest.main()
