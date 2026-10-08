"""Contract tests for the bundled Workflow scripts.

The scripts are plain JS the `Workflow` tool runs with the body wrapped in an async
function, its `agent`/`parallel`/`phase`/`log` hooks injected. These tests inject the same
hooks from a stub harness so the pure logic — dedupe, the refuter quorum, the guards — is
provable without spending an agent: each case declares canned per-label agent responses and
asserts on the script's return value, its logs and the agent calls it made.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
REVIEW = SHIPGATE / "skills" / "review" / "references" / "review-workflow.js"
EXPLORE = SHIPGATE / "skills" / "feature" / "references" / "explore-workflow.js"
NODE = shutil.which("node")

HARNESS = r"""
const __RESPONSES = %RESPONSES%;
const __LOGS = [];
const __CALLS = [];
const args = %ARGS%;
const budget = { spent: 0, limit: null, remaining: null };
function log(message) { __LOGS.push(String(message)); }
function phase(title) { __LOGS.push('phase:' + String(title)); }
function __respond(label) {
  if (Object.prototype.hasOwnProperty.call(__RESPONSES, label)) return __RESPONSES[label];
  let best = null;
  for (const key of Object.keys(__RESPONSES)) {
    if (label.startsWith(key) && (best === null || key.length > best.length)) best = key;
  }
  return best === null ? null : __RESPONSES[best];
}
function agent(prompt, opts) {
  const options = opts || {};
  const label = String(options.label || '');
  __CALLS.push({
    label,
    prompt,
    agentType: options.agentType || null,
    phase: options.phase || null,
    effort: options.effort || null,
    model: options.model || null,
  });
  return Promise.resolve(__respond(label));
}
function parallel(thunks) { return Promise.all(thunks.map((thunk) => thunk())); }
function pipeline(thunks) {
  return thunks.reduce((chain, thunk) => chain.then((carry) => thunk(carry)), Promise.resolve(null));
}
async function __run() {
%BODY%
}
__run().then(
  (result) => console.log(JSON.stringify({ ok: true, result, logs: __LOGS, calls: __CALLS })),
  (error) => console.log(JSON.stringify({
    ok: false,
    error: String((error && error.message) || error),
    logs: __LOGS,
    calls: __CALLS,
  })),
);
"""


def run_script(script: Path, args: dict, responses: dict) -> dict:
    body = script.read_text(encoding="utf-8").replace("export const meta", "const meta", 1)
    source = (
        HARNESS.replace("%RESPONSES%", json.dumps(responses))
        .replace("%ARGS%", json.dumps(args))
        .replace("%BODY%", body)
    )
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case.mjs"
        case.write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [NODE, str(case)], capture_output=True, text=True, timeout=120
        )
    if proc.returncode != 0:
        raise AssertionError(f"node exited {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout)


def finding(**over) -> dict:
    base = {
        "severity": "MEDIUM",
        "confidence": 90,
        "file": "src/a.js",
        "line": None,
        "summary": "a finding",
        "why": "because the guard is missing",
        "fix": "add the guard",
    }
    base.update(over)
    return base


def verdict(refuted=True, evidence="src/a.js:10 shows the guard", confidence=90) -> dict:
    return {"refuted": refuted, "reason": "the guard exists", "evidence": evidence, "confidence": confidence}


def finders(reports: dict) -> dict:
    return {
        f"review:{lens}": (None if items is None else {"findings": items})
        for lens, items in reports.items()
    }


@unittest.skipUnless(NODE, "node is required to run the Workflow scripts")
class ScriptCase(unittest.TestCase):
    script: Path

    def ok(self, args: dict, responses: dict | None = None) -> dict:
        out = run_script(self.script, args, responses or {})
        self.assertTrue(out["ok"], out.get("error"))
        return out

    def err(self, args: dict, responses: dict | None = None) -> str:
        out = run_script(self.script, args, responses or {})
        self.assertFalse(out["ok"], out.get("result"))
        return out["error"]


class ReviewWorkflow(ScriptCase):
    script = REVIEW

    def review(self, reports: dict, verdicts: dict | None = None, **overrides) -> dict:
        args = {"lenses": list(reports), "finderBrief": "diff: HEAD~1", "model": "sonnet"}
        args.update(overrides)
        return self.ok(args, {**finders(reports), **(verdicts or {})})

    def deduped(self, reports: dict) -> dict:
        return self.review(reports, verify="none")["result"]

    def test_lineless_findings_in_one_file_stay_separate(self):
        result = self.deduped(
            {
                "correctness": [
                    finding(summary="the retry loop never terminates"),
                    finding(summary="config is read before it is validated"),
                    finding(summary="errors are swallowed by the catch"),
                ]
            }
        )
        self.assertEqual(result["counts"]["deduped"], 3)

    def test_same_line_merges_and_keeps_the_loser_wording(self):
        result = self.deduped(
            {
                "correctness": [finding(line=10, summary="off by one in the loop bound", confidence=80)],
                "conventions+design": [
                    finding(line=10, severity="HIGH", confidence=90, summary="loop bound drops the last row")
                ],
            }
        )
        self.assertEqual(result["counts"]["deduped"], 1)
        survivor = result["survivors"][0]
        self.assertEqual(survivor["summary"], "loop bound drops the last row")
        self.assertEqual(survivor["lenses"], ["correctness", "conventions+design"])
        self.assertEqual(
            survivor["alsoReported"],
            [{"lens": "correctness", "summary": "off by one in the loop bound"}],
        )

    def test_same_summary_merges_across_different_lines(self):
        result = self.deduped(
            {
                "correctness": [finding(line=10, summary="the token is logged in clear text")],
                "simplicity+security": [finding(line=99, summary="the token is logged in clear text")],
            }
        )
        self.assertEqual(result["counts"]["deduped"], 1)

    def test_nearby_lines_do_not_chain(self):
        result = self.deduped(
            {
                "correctness": [
                    finding(line=10, summary="the retry loop never terminates"),
                    finding(line=12, summary="config is read before it is validated"),
                    finding(line=14, summary="errors are swallowed by the catch"),
                ]
            }
        )
        self.assertEqual(result["counts"]["deduped"], 3)

    def test_path_forms_share_a_merge_key(self):
        for label, files in (
            ("two segments", ["src/a.js", "./src/a.js", "/src/a.js"]),
            ("three segments", ["pkg/src/a.js", "./pkg/src/a.js", "/build/w/pkg/src/a.js"]),
        ):
            with self.subTest(label):
                result = self.deduped(
                    {
                        "correctness": [
                            finding(file=files[0], line=10, summary="first wording"),
                            finding(file=files[1], line=10, summary="second wording"),
                            finding(file=files[2], line=10, summary="third wording"),
                        ]
                    }
                )
                self.assertEqual(result["counts"]["deduped"], 1)

    def test_high_only_spends_refuters_on_high_severity_within_the_cap(self):
        out = self.review(
            {
                "correctness": [
                    finding(severity="BLOCKER", line=10, summary="unauthenticated write path"),
                    finding(severity="HIGH", line=20, summary="race on the cache write"),
                    finding(severity="MEDIUM", line=30, summary="duplicated parsing helper"),
                ]
            },
            {"refute:": verdict(refuted=False, evidence="")},
            maxRefuters=2,
        )
        result = out["result"]
        spent = [call for call in out["calls"] if call["phase"] == "Verify"]
        self.assertEqual(len(spent), 2)
        for call in spent:
            self.assertTrue(call["label"].startswith("refute:src/a.js:10"))
            self.assertEqual(call["agentType"], "shipgate:code-reviewer")
        self.assertEqual(result["counts"]["refuters"], 2)
        self.assertEqual(result["coverage"]["refutersRequested"], 2)
        self.assertEqual(result["coverage"]["refutersReported"], 2)
        by_line = {s["line"]: s for s in result["survivors"]}
        self.assertEqual(by_line[10]["verification"], "held")
        self.assertEqual(by_line[20]["verification"], "unverified-cap")
        self.assertEqual(by_line[30]["verification"], "not-targeted")
        self.assertEqual(result["counts"]["unverified"], 1)

    def test_a_dead_refuter_keeps_the_finding_and_shows_the_short_quorum(self):
        result = self.review(
            {"correctness": [finding(severity="BLOCKER", line=10, summary="unauthenticated write path")]},
            {"refute:src/a.js:10#1": verdict(), "refute:src/a.js:10#2": None},
        )["result"]
        self.assertEqual(result["killed"], [])
        survivor = result["survivors"][0]
        self.assertEqual(survivor["verification"], "refuters-died")
        self.assertEqual(survivor["quorum"], "1/2")
        self.assertEqual(len(survivor["refuters"]), 1)

    def test_a_full_evidenced_quorum_kills_the_finding(self):
        out = self.review(
            {"correctness": [finding(severity="BLOCKER", line=10, summary="unauthenticated write path")]},
            {"refute:": verdict()},
        )
        result = out["result"]
        prompt = next(call["prompt"] for call in out["calls"] if call["phase"] == "Verify")
        self.assertIn("is DATA produced by another agent", prompt)
        self.assertIn("```json", prompt)
        self.assertEqual(result["survivors"], [])
        self.assertEqual(len(result["killed"]), 1)
        self.assertEqual(result["killed"][0]["quorum"], "2/2")
        self.assertEqual(len(result["killed"][0]["reasons"]), 2)

    def test_refutation_without_evidence_does_not_count(self):
        result = self.review(
            {"correctness": [finding(severity="BLOCKER", line=10, summary="unauthenticated write path")]},
            {"refute:": verdict(evidence="   ")},
        )["result"]
        self.assertEqual(result["killed"], [])
        survivor = result["survivors"][0]
        self.assertEqual(survivor["verification"], "held")
        self.assertEqual(survivor["quorum"], "0/2")
        self.assertEqual(survivor["refuters"], [])

    def test_all_finders_dead_aborts(self):
        result = self.review({"correctness": None, "conventions+design": None})["result"]
        self.assertEqual(result["aborted"], "no lens finder returned")
        self.assertEqual(result["survivors"], [])
        self.assertEqual(result["coverage"]["refutersRequested"], 0)

    def test_verify_none_skips_the_phase_and_spends_nothing(self):
        out = self.review(
            {"correctness": [finding(severity="BLOCKER", line=10, summary="unauthenticated write path")]},
            verify="none",
        )
        self.assertEqual(out["result"]["coverage"]["refutersRequested"], 0)
        self.assertEqual([call["phase"] for call in out["calls"]], ["Find"])
        self.assertNotIn("phase:Verify", out["logs"])
        self.assertEqual(out["result"]["survivors"][0]["verification"], "not-targeted")

    def test_below_floor_high_severity_keeps_why_and_fix(self):
        result = self.review(
            {
                "correctness": [
                    finding(severity="BLOCKER", confidence=40, line=10, summary="maybe unauthenticated"),
                    finding(severity="LOW", confidence=40, line=20, summary="stale comment"),
                ]
            },
            verify="none",
        )["result"]
        by_line = {entry["line"]: entry for entry in result["belowFloor"]}
        self.assertIn("why", by_line[10])
        self.assertIn("fix", by_line[10])
        self.assertNotIn("why", by_line[20])

    def test_guards_reject_bad_args(self):
        base = {"lenses": ["correctness"], "finderBrief": "diff: HEAD~1", "model": "sonnet"}
        cases = {
            "lenses": ({**base, "lenses": ["correctness", ""]}, "non-empty lens name"),
            "duplicate lenses": ({**base, "lenses": ["correctness", "correctness"]}, "must not repeat a lens"),
            "lenses not a list": ({**base, "lenses": "correctness"}, "at least one review lens"),
            "brief": ({**base, "finderBrief": "   "}, "args.finderBrief is required"),
            "budget": ({**base, "maxRefuters": 1}, "could ever be verified"),
            "floor": ({**base, "confidenceFloor": 140}, "must be a number 0-100"),
            "doNotFlag": ({**base, "doNotFlag": [{"note": "x"}]}, "must be an array of strings"),
        }
        for label, (args, expected) in cases.items():
            with self.subTest(label):
                self.assertIn(expected, self.err(args))

    def test_file_risk_steers_the_refuter_budget_to_the_top_risk_file(self):
        out = self.review(
            {
                "correctness": [
                    finding(severity="HIGH", confidence=90, file="src/safe.js", line=10, summary="safe race"),
                    finding(severity="HIGH", confidence=80, file="src/hot.js", line=20, summary="hot race"),
                ]
            },
            {"refute:": verdict(refuted=False, evidence="")},
            maxRefuters=2,
            refutersForHigh=2,
            fileRisk={"src/safe.js": "low", "src/hot.js": "top"},
        )
        result = out["result"]
        spent = [call["label"] for call in out["calls"] if call["phase"] == "Verify"]
        self.assertEqual(len(spent), 2)
        for label in spent:
            self.assertTrue(label.startswith("refute:src/hot.js:20"), label)
        by_file = {s["file"]: s for s in result["survivors"]}
        self.assertEqual(by_file["src/hot.js"]["verification"], "held")
        self.assertEqual(by_file["src/safe.js"]["verification"], "unverified-cap")
        self.assertEqual(result["counts"]["unverified"], 1)
        self.assertTrue(any(line == "risk-ordered verify over 2 file(s)" for line in out["logs"]))

    def test_file_risk_never_overrides_severity_in_verify(self):
        out = self.review(
            {
                "correctness": [
                    finding(severity="BLOCKER", confidence=70, file="src/safe.js", line=10, summary="auth bypass"),
                    finding(severity="HIGH", confidence=95, file="src/hot.js", line=20, summary="hot race"),
                ]
            },
            {"refute:": verdict(refuted=False, evidence="")},
            maxRefuters=2,
            fileRisk={"src/hot.js": "top"},
        )
        spent = [call["label"] for call in out["calls"] if call["phase"] == "Verify"]
        self.assertTrue(all(label.startswith("refute:src/safe.js:10") for label in spent), spent)

    def test_file_risk_breaks_a_severity_and_confidence_tie(self):
        result = self.deduped_with_risk(
            [
                finding(file="src/cold.js", line=1, summary="cold issue"),
                finding(file="src/hot.js", line=1, summary="hot issue"),
            ],
            {"src/hot.js": "top", "src/cold.js": "low"},
        )
        self.assertEqual([s["file"] for s in result["survivors"]], ["src/hot.js", "src/cold.js"])

    def test_file_risk_keys_are_path_normalized(self):
        result = self.deduped_with_risk(
            [finding(file="src/a.js", line=1, summary="an issue")],
            {"./src/a.js": "high"},
        )
        self.assertEqual(result["survivors"][0]["risk"], "high")

    def test_file_risk_is_labelled_on_compacted_findings_when_present(self):
        result = self.deduped_with_risk(
            [
                finding(file="src/hot.js", line=1, summary="hot issue"),
                finding(file="src/other.js", line=2, summary="unmapped issue"),
                finding(file="src/hot.js", line=3, confidence=10, summary="low confidence"),
            ],
            {"src/hot.js": "mid"},
        )
        self.assertIs(result["coverage"]["riskOrdered"], True)
        by_file = {s["file"]: s for s in result["survivors"]}
        self.assertEqual(by_file["src/hot.js"]["risk"], "mid")
        self.assertNotIn("risk", by_file["src/other.js"])
        self.assertEqual(result["belowFloor"][0]["risk"], "mid")

    def test_file_risk_absent_leaves_the_output_byte_identical(self):
        reports = {
            "correctness": [
                finding(severity="BLOCKER", line=10, summary="unauthenticated write path"),
                finding(severity="HIGH", line=20, file="src/b.js", summary="race on the cache write"),
                finding(severity="MEDIUM", line=30, summary="duplicated parsing helper"),
                finding(severity="HIGH", confidence=40, line=40, summary="maybe a leak"),
            ]
        }
        verdicts = {"refute:src/a.js:10": verdict(), "refute:": verdict(refuted=False, evidence="")}
        absent = self.review(reports, verdicts, maxRefuters=2)
        for label, value in (("null", None), ("empty", {}), ("only null labels", {"src/a.js": None})):
            with self.subTest(label):
                given = self.review(reports, verdicts, maxRefuters=2, fileRisk=value)
                self.assertEqual(json.dumps(given["result"]), json.dumps(absent["result"]))
                self.assertEqual(given["logs"], absent["logs"])
        result = absent["result"]
        self.assertEqual(
            sorted(result["coverage"]), ["refutersReported", "refutersRequested", "unverified", "verify"]
        )
        self.assertNotIn("risk-ordered", "\n".join(absent["logs"]))
        entries = result["survivors"] + result["belowFloor"] + [k["finding"] for k in result["killed"]]
        self.assertTrue(entries)
        for entry in entries:
            self.assertNotIn("risk", entry)

    def test_file_risk_null_labels_are_treated_as_absent(self):
        result = self.deduped_with_risk(
            [
                finding(file="a.js", line=1, summary="shallow-row issue"),
                finding(file="b.js", line=1, summary="ranked issue"),
            ],
            {"a.js": None, "b.js": "top"},
        )
        self.assertIs(result["coverage"]["riskOrdered"], True)
        by_file = {s["file"]: s for s in result["survivors"]}
        self.assertEqual(by_file["b.js"]["risk"], "top")
        self.assertNotIn("risk", by_file["a.js"])

    def test_file_risk_guard_rejects_bad_values(self):
        base = {"lenses": ["correctness"], "finderBrief": "diff: HEAD~1", "model": "sonnet"}
        for label, value in (
            ("unknown label", {"a.js": "hot"}),
            ("string", "top"),
            ("array", [["a.js", "top"]]),
            ("non-string label", {"a.js": 3}),
        ):
            with self.subTest(label):
                self.assertTrue(
                    self.err({**base, "fileRisk": value}).startswith("review-workflow: args.fileRisk"),
                )
        self.ok({**base, "fileRisk": None}, finders({"correctness": []}))

    def deduped_with_risk(self, findings: list, risk: dict) -> dict:
        return self.review({"correctness": findings}, verify="none", fileRisk=risk)["result"]


class ExploreWorkflow(ScriptCase):
    script = EXPLORE

    def explore(self, reports: dict, **overrides) -> dict:
        args = {
            "lenses": [{"name": name, "prompt": f"trace {name}"} for name in reports],
            "brief": "config excerpts",
            "model": "sonnet",
        }
        args.update(overrides)
        responses = {f"explore:{name}": report for name, report in reports.items()}
        return self.ok(args, responses)

    def test_all_explorers_dead_aborts(self):
        out = self.explore({"write-path": None, "read-models": None})
        self.assertEqual(out["result"]["aborted"], "no lens explorer returned")
        self.assertEqual(out["result"]["essentialFiles"], [])
        self.assertTrue(any("explored nothing" in line for line in out["logs"]))
        self.assertFalse(any("continuing on the rest" in line for line in out["logs"]))

    def test_brief_is_required(self):
        args = {
            "lenses": [{"name": "write-path", "prompt": "trace it"}],
            "brief": "  ",
            "model": "sonnet",
        }
        self.assertIn("args.brief is required", self.err(args))

    def test_path_forms_merge_into_one_essential_file(self):
        result = self.explore(
            {
                "write-path": {
                    "findings": [],
                    "essential_files": [
                        {"path": "pkg/src/a.js", "why": "the write path lives here"},
                        {"path": "pkg/src/a.js", "why": "the write path lives here"},
                    ],
                },
                "read-models": {
                    "findings": [],
                    "essential_files": [{"path": "/build/w/pkg/src/a.js", "why": "the read model reads it"}],
                },
            }
        )["result"]
        self.assertEqual(len(result["essentialFiles"]), 1)
        entry = result["essentialFiles"][0]
        self.assertEqual(entry["path"], "pkg/src/a.js")
        self.assertEqual(
            entry["why"],
            [
                {"lens": "write-path", "why": "the write path lives here"},
                {"lens": "read-models", "why": "the read model reads it"},
            ],
        )

    def test_the_dispatched_explorer_can_read_other_refs(self):
        """A lens may need a ref that is not checked out (`origin/<integration>` for a
        staleness check) or the history; with Glob/Grep/Read alone it can read neither."""
        out = self.explore({"staleness": {"findings": [], "essential_files": []}})
        agent_types = {call["agentType"] for call in out["calls"]}
        self.assertEqual(agent_types, {"shipgate:code-explorer"})
        definition = (SHIPGATE / "agents" / "code-explorer.md").read_text(encoding="utf-8")
        tools_line = next(line for line in definition.splitlines() if line.startswith("tools:"))
        tools = {tool.strip() for tool in tools_line.split(":", 1)[1].split(",")}
        self.assertIn("Bash", tools)
        # the shell stays read-only: the prompt names what it is for and what it never does
        self.assertIn("git show <ref>:<path>", definition)
        self.assertIn("never `git fetch`", definition)

    def test_findings_are_capped_per_lens(self):
        many = [{"topic": f"t{i}", "detail": "d", "refs": []} for i in range(25)]
        out = self.explore({"write-path": {"findings": many, "essential_files": []}})
        self.assertEqual(len(out["result"]["lenses"][0]["findings"]), 20)
        self.assertTrue(any("dropping 5" in line for line in out["logs"]))


if __name__ == "__main__":
    unittest.main()
