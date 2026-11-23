#!/usr/bin/env python3
"""Tests for the close-out and the sweep of shipgate's ``scripts/journal.py`` (#31,
ADR 0025 and ADR 0026).

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_journal import JOURNAL, SESSION_ENV, load_journal_module

FORGE = Path(__file__).resolve().parent / "fixtures" / "forge"
HEAD = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"
BASE_TIP = "0d1e2f3a4b5c6d7e8f90a1b2c3d4e5f6a7b8c9d0"


def fixture(name):
    return (FORGE / name).read_text(encoding="utf-8")


class TestParsers(unittest.TestCase):
    """T011: the evidence files the observe script writes, parsed."""

    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def test_gh_one_object(self):
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        self.assertEqual(prs, [{
            "forge": "gh", "state": "merged", "raw_state": "MERGED",
            "url": "https://forge.invalid/o/r/pull/7", "head": "feat/7-x",
            "head_oid": HEAD, "base": "main", "merged_at": "2026-11-20T10:02:11Z",
            "fork": False,
        }])

    def test_gh_list_in_each_state(self):
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        self.assertEqual([(p["head"], p["state"]) for p in prs], [
            ("feat/7-x", "merged"), ("feat/8-y", "closed"), ("fix/9-z", "open")])

    def test_glab_one_object(self):
        prs = self.j.parse_forge_prs(fixture("glab_view_merged.json"))
        self.assertEqual(prs, [{
            "forge": "glab", "state": "merged", "raw_state": "merged",
            "url": "https://gitlab.forge.invalid/g/p/-/merge_requests/7",
            "head": "feat/7-x", "head_oid": HEAD, "base": "main",
            "merged_at": "2026-11-20T10:02:11.000Z", "fork": False,
        }])

    def test_a_fork_is_marked(self):
        gh = json.loads(fixture("gh_view_merged.json"))
        gh["isCrossRepository"] = True
        glab = json.loads(fixture("glab_view_merged.json"))
        glab["source_project_id"] = 99
        self.assertEqual([p["fork"] for p in self.j.parse_forge_prs(json.dumps([gh, glab]))],
                         [True, True])

    def test_glab_list_in_each_state(self):
        prs = self.j.parse_forge_prs(fixture("glab_list.json"))
        self.assertEqual([(p["head"], p["state"]) for p in prs], [
            ("feat/7-x", "merged"), ("feat/8-y", "closed"), ("fix/9-z", "open")])

    def test_a_locked_glab_mr_is_open(self):
        """F50: glab writes `locked` while an MR merges; the work is not done yet."""
        glab = json.loads(fixture("glab_view_merged.json"))
        glab.update({"state": "locked", "merged_at": None})
        prs = self.j.parse_forge_prs(json.dumps(glab))
        self.assertEqual([(p["state"], p["raw_state"]) for p in prs], [("open", "locked")])

    def test_garbage_is_none(self):
        for text in ("", "not json", "42", '"x"', "{nope"):
            with self.subTest(text=text):
                self.assertIsNone(self.j.parse_forge_prs(text))

    def test_an_entry_of_another_shape_is_dropped(self):
        prs = self.j.parse_forge_prs(json.dumps(
            [{"state": "MERGED"}, {"state": "weird", "headRefName": "x"}, 3,
             json.loads(fixture("gh_view_merged.json"))]))
        self.assertEqual([p["head"] for p in prs], ["feat/7-x"])

    def test_an_empty_list_is_no_pr(self):
        self.assertEqual(self.j.parse_forge_prs("[]"), [])

    def test_a_list_with_no_usable_entry_is_no_evidence(self):
        """F39: after a field rename every entry drops out; that is a format drift, not
        "no PR", so the decision falls back to git and says so."""
        self.assertIsNone(self.j.parse_forge_prs(
            '[{"number": 1, "head": "x", "state": "MERGED"}]'))

    def test_refs(self):
        refs = self.j.parse_refs(
            f"{HEAD} refs/heads/feat/7-x\n{BASE_TIP} refs/remotes/origin/main\n\n"
            "junk\n")
        self.assertEqual(refs, {"refs/heads/feat/7-x": HEAD,
                                "refs/remotes/origin/main": BASE_TIP})

    def test_merged(self):
        self.assertEqual(
            self.j.parse_merged(f"{HEAD} refs/heads/feat/7-x\n{BASE_TIP} refs/heads/main\n"),
            {"refs/heads/feat/7-x", "refs/heads/main"})

    def test_worktrees(self):
        trees = self.j.parse_worktrees(fixture("worktrees.txt"))
        self.assertEqual(trees, [
            {"path": "/repo", "head": BASE_TIP, "branch": "main"},
            {"path": "/repo.worktrees/feat-7-x", "head": HEAD, "branch": "feat/7-x"},
            {"path": "/tmp/probe", "head": "4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f70",
             "branch": None},
        ])

    def test_worktree_files(self):
        """F60: `git status --porcelain --ignored` in the stream's worktree; the ignored
        (`!!`) and untracked (`??`) entries are the files the removal deletes or git
        refuses on. A change to a tracked file is not one of them."""
        text = "!! .env\n?? notes.txt\n M src/a.py\nA  b.py\n!! node_modules/\n"
        self.assertEqual(self.j.parse_worktree_files(text),
                         [".env", "notes.txt", "node_modules/"])
        self.assertEqual(self.j.parse_worktree_files(""), [])

    def test_a_missing_file_reads_as_none(self):
        missing = FORGE / "no-such-dir"
        evidence = self.j.read_observed(missing)
        self.assertEqual(evidence, {"prs": None, "refs": None, "merged": None,
                                    "worktrees": None, "base": None,
                                    "first_parent": None, "worktree_files": None})

    def test_base_and_first_parent(self):
        self.assertEqual(self.j.parse_base("trunk\n"), "trunk")
        for text in ("", "\n", "-x\n", "a b\n"):
            with self.subTest(text=text):
                self.assertIsNone(self.j.parse_base(text))
        self.assertEqual(self.j.parse_first_parent(f"{BASE_TIP}\n{HEAD}\njunk\n\n"),
                         {BASE_TIP, HEAD})


class TestMergeEvidence(unittest.TestCase):
    """T011: forge first, git ancestry as the fallback (ADR 0025)."""

    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def facts(self, **over):
        facts = {"stream": "feat/7-x", "branch": "feat/7-x", "base": "main",
                 "url": "https://forge.invalid/o/r/pull/7"}
        facts.update(over)
        return facts

    def refs(self, local=HEAD, remote=HEAD):
        refs = {"refs/remotes/origin/main": BASE_TIP, "refs/heads/main": BASE_TIP}
        if local:
            refs["refs/heads/feat/7-x"] = local
        if remote:
            refs["refs/remotes/origin/feat/7-x"] = remote
        return refs

    def evidence(self, prs, refs=None, merged=None, first_parent=(), sweep=False, **facts):
        return self.j.merge_evidence(self.facts(**facts), prs,
                                     self.refs() if refs is None else refs,
                                     set() if merged is None else merged,
                                     None if first_parent is None else set(first_parent),
                                     sweep=sweep)

    def test_forge_merged_and_in_git(self):
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        got = self.evidence(prs, merged={"refs/heads/feat/7-x"})
        self.assertEqual(got["state"], "merged")
        self.assertEqual(got["source"], "forge")
        self.assertFalse(got["squash"])
        self.assertEqual(got["head_oid"], HEAD)
        self.assertEqual(got["url"], "https://forge.invalid/o/r/pull/7")
        self.assertEqual(got["detail"], "forge gh: MERGED 2026-11-20T10:02 · head "
                                        "1a2b3c4 · https://forge.invalid/o/r/pull/7")

    def test_a_squash_merge_is_marked(self):
        prs = self.j.parse_forge_prs(fixture("glab_view_merged.json"))
        got = self.evidence(prs, url=None)
        self.assertEqual((got["state"], got["source"], got["squash"]),
                         ("merged", "forge", True))

    def test_no_squash_mark_when_the_local_branch_is_gone(self):
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        got = self.evidence(prs, refs=self.refs(local=None))
        self.assertFalse(got["squash"])

    def test_no_squash_mark_for_a_merge_into_another_base(self):
        """F8: ``merged`` holds the refs merged into the observed base only, so a PR
        that merged into another base is no squash, and ``branch -d`` decides."""
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        prs[0]["base"] = "release/1"
        got = self.evidence(prs)
        self.assertEqual((got["state"], got["squash"], got["base"]),
                         ("merged", False, "release/1"))

    def test_closed_and_open(self):
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        self.assertEqual(self.evidence(prs, stream="feat/8-y", branch="feat/8-y",
                                       url=None)["state"], "closed")
        self.assertEqual(self.evidence(prs, stream="fix/9-z", branch="fix/9-z",
                                       url=None)["state"], "open")

    def test_the_url_wins_over_the_branch(self):
        """The recorded PR wins over a head match. Its head `feat/8-y` is not the
        stream's name, so the close-out acts on nothing; the sweep reads its state."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        got = self.evidence(prs, url="https://forge.invalid/o/r/pull/8")
        self.assertEqual((got["state"], got["source"]), ("unknown", "forge"))
        self.assertIn("journal.py sweep", got["detail"])
        got = self.evidence(prs, url="https://forge.invalid/o/r/pull/8", sweep=True)
        self.assertEqual(got["state"], "closed")
        self.assertNotIn("guess", got["detail"])

    def test_merged_outranks_closed_among_prs_of_one_branch(self):
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[1]["head"] = "feat/7-x"
        self.assertEqual(self.evidence(prs, url=None)["state"], "merged")

    def test_git_fallback_merged(self):
        got = self.evidence(None, merged={"refs/heads/feat/7-x"})
        self.assertEqual((got["state"], got["source"]), ("merged", "git"))
        self.assertIn("forge evidence missing", got["detail"])

    def test_a_tip_equal_to_the_base_tip_is_not_evidence(self):
        refs = self.refs(local=BASE_TIP, remote=None)
        got = self.evidence(None, refs=refs, merged={"refs/heads/feat/7-x"})
        self.assertEqual(got["state"], "unknown")

    def test_a_branch_with_no_commits_of_its_own_is_not_merged(self):
        """F1: cut from an old base commit and never committed to, the tip is in the
        merged refs and is not the base tip once the base moved on. It sits on the
        base's first-parent line, so nothing shows that the branch's work merged."""
        old = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432"
        refs = self.refs(local=old, remote=old)
        got = self.evidence(None, refs=refs,
                            merged={"refs/heads/feat/7-x", "refs/remotes/origin/feat/7-x"},
                            first_parent={BASE_TIP, old})
        self.assertEqual((got["state"], got["source"]), ("unknown", "git"))
        self.assertIn("first-parent", got["detail"])

    def test_with_a_forge_answer_and_no_pr_git_never_says_merged(self):
        """F24, the user's ruling: when the forge answered and no PR/MR matches, git
        may say gone or unknown, never merged. Here the branch sits at the tip of
        another branch that merged with a merge commit, so git alone would say merged."""
        other_tip = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        refs = self.refs(local=other_tip, remote=None)
        merged = {"refs/heads/feat/7-x"}
        alone = self.evidence(None, refs=refs, merged=merged, url=None)
        self.assertEqual(alone["state"], "merged")
        got = self.evidence([], refs=refs, merged=merged, url=None)
        self.assertEqual((got["state"], got["source"]), ("unknown", "git"))
        self.assertIn("forge: no PR/MR for feat/7-x", got["detail"])
        self.assertIn("never merged", got["detail"])
        self.assertEqual(self.evidence([], refs=self.refs(local=None, remote=None),
                                       url=None)["state"], "gone")

    def test_without_the_first_parent_file_git_cannot_say_merged(self):
        got = self.evidence(None, merged={"refs/heads/feat/7-x"}, first_parent=None)
        self.assertEqual((got["state"], got["source"]), ("unknown", "git"))
        self.assertIn("first-parent evidence missing", got["detail"])

    def test_git_fallback_not_in_base(self):
        got = self.evidence([], merged=set())
        self.assertEqual((got["state"], got["source"]), ("unknown", "git"))
        self.assertIn("no PR/MR", got["detail"])

    def test_no_branch_left_is_gone(self):
        got = self.evidence([], refs=self.refs(local=None, remote=None))
        self.assertEqual((got["state"], got["source"]), ("gone", "git"))

    def test_no_evidence_at_all(self):
        got = self.j.merge_evidence(self.facts(), None, None, None)
        self.assertEqual((got["state"], got["source"]), ("unknown", "none"))

    def test_the_close_out_matches_exact_names_only(self):
        """The user's round-3 ruling: the close-out takes the recorded PR or one whose
        head is the stream exactly, and acts on the branch named as the stream (F34,
        F35). The round-4 ruling: the sweep does not guess either (F44, F45)."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[0]["head"] = "7-x"
        refs = {"refs/remotes/origin/main": BASE_TIP, "refs/heads/7-x": HEAD}
        for sweep in (False, True):
            with self.subTest(sweep=sweep):
                got = self.evidence(prs, stream="feature/7-x", url=None, refs=refs,
                                    merged={"refs/heads/7-x"}, sweep=sweep)
                self.assertEqual((got["state"], got["source"]), ("gone", "git"))
                self.assertIn("forge: no PR/MR for feature/7-x", got["detail"])
                self.assertIn("no local or remote branch feature/7-x", got["detail"])
                self.assertNotIn("guess", got["detail"])

    def test_a_recorded_pr_with_another_head_closes_nothing(self):
        """The ruling: the recorded PR's head must be the stream's name, else the
        close-out names the sweep and plans no git step."""
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        prs[0]["head"] = "fix/7-x"
        got = self.evidence(prs)
        self.assertEqual((got["state"], got["source"]), ("unknown", "forge"))
        self.assertIn("fix/7-x", got["detail"])
        self.assertIn("journal.py sweep", got["detail"])

    def test_a_slug_alone_matches_no_pr_for_a_branch_named_stream(self):
        """F7: a PR of another branch with the same slug is not the stream's PR when
        the stream is named for its branch, even in the sweep."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[0]["head"] = "fix/7-x"
        got = self.evidence(prs, url=None, refs={"refs/remotes/origin/main": BASE_TIP},
                            sweep=True)
        self.assertEqual((got["state"], got["source"]), ("gone", "git"))

    def test_the_sweep_takes_no_slug_head(self):
        """F44, the user's round-4 ruling: for a `feature/<slug>` stream the sweep takes
        no PR head that ends in `/<slug>`, one or two of them; with no branch of the
        stream's name it reads gone and names what it looked for."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[0]["head"] = "fix/7-x"
        bare = {"refs/remotes/origin/main": BASE_TIP}
        got = self.evidence(prs, stream="feature/7-x", url=None, refs=bare, sweep=True)
        self.assertEqual((got["state"], got["source"]), ("gone", "git"))
        self.assertEqual(got["detail"], "forge: no PR/MR for feature/7-x; git: no local "
                                        "or remote branch feature/7-x")
        prs[2]["head"] = "renovate/npm/7-x"
        got = self.evidence(prs, stream="feature/7-x", url=None, refs=bare, sweep=True)
        self.assertEqual((got["state"], got["source"]), ("gone", "git"))

    def test_the_sweep_ignores_a_slug_head_when_its_branch_exists(self):
        """F45: the stream's own branch exists and another branch's PR with the same
        slug merged; the sweep reads the stream's branch only, never merged."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[0]["head"] = "chore/7-x"
        refs = {"refs/remotes/origin/main": BASE_TIP, "refs/heads/feature/7-x": HEAD}
        got = self.evidence(prs, stream="feature/7-x", url=None, refs=refs, sweep=True,
                            merged={"refs/heads/feature/7-x"})
        self.assertEqual((got["state"], got["source"]), ("unknown", "git"))
        self.assertIn("never merged", got["detail"])

    def test_the_sweep_takes_no_slug_branch(self):
        """F35 in the sweep: with no forge evidence, a branch that ends in `/<slug>`
        can be another stream's, so the sweep reads gone, never merged."""
        other = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        refs = {"refs/remotes/origin/main": BASE_TIP, "refs/heads/chore/docs": other,
                "refs/remotes/origin/feat/docs": other}
        got = self.evidence(None, stream="feature/docs", url=None, refs=refs,
                            merged={"refs/heads/chore/docs"}, sweep=True)
        self.assertEqual((got["state"], got["source"]), ("gone", "git"))
        self.assertEqual(got["detail"], "forge evidence missing; git: no local or remote "
                                        "branch feature/docs")

    def test_no_pr_detail_names_the_recorded_url_it_looked_for(self):
        """The round-4 ruling: the evidence shows what it looked for."""
        got = self.evidence([], refs={"refs/remotes/origin/main": BASE_TIP}, sweep=True)
        self.assertEqual(got["state"], "gone")
        self.assertIn("forge: no PR/MR for feat/7-x or https://forge.invalid/o/r/pull/7",
                      got["detail"])

    def test_a_stream_named_as_the_base_is_never_closed(self):
        """F43: the close-out never removes or deletes the integration branch."""
        refs = {"refs/remotes/origin/main": BASE_TIP, "refs/heads/main": HEAD}
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        prs[0]["head"] = "main"
        for evidence in (prs, None):
            with self.subTest(forge=evidence is not None):
                got = self.evidence(evidence, stream="main", refs=refs,
                                    merged={"refs/heads/main"})
                self.assertEqual(got["state"], "unknown")
                self.assertIn("integration branch", got["detail"])

    def test_a_recorded_url_in_another_form_still_matches(self):
        """F40: the URL compare stops at the PR/MR number."""
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        for url in ("https://forge.invalid/o/r/pull/7/files",
                    "https://FORGE.invalid/o/r/pull/7/",
                    "https://forge.invalid/o/r/pull/7#x"):
            with self.subTest(url=url):
                self.assertEqual(self.evidence(prs, url=url)["state"], "merged")
        glab = self.j.parse_forge_prs(fixture("glab_view_merged.json"))
        url = "https://gitlab.forge.invalid/g/p/-/merge_requests/7/diffs"
        self.assertEqual(self.evidence(glab, url=url)["state"], "merged")
        self.assertNotEqual(self.j._pr_url_key("https://forge.invalid/o/r/pull/70"),
                            self.j._pr_url_key("https://forge.invalid/o/r/pull/7"))

    def test_a_malformed_url_compares_as_itself(self):
        """F52: urlsplit raises on `https://[bad/...`; the key is then the URL."""
        bad = "https://[bad/o/r/pull/7"
        self.assertEqual(self.j._pr_url_key(bad), bad)
        prs = self.j.parse_forge_prs(fixture("gh_view_merged.json"))
        self.assertEqual(self.evidence(prs, url=bad)["state"], "merged")
        prs[0]["url"] = bad
        self.assertEqual(self.evidence(prs, url=bad)["url"], bad)
        self.assertIsNone(self.j.forge_from_url(bad))

    def test_a_fork_pr_matches_by_its_url_only(self):
        """F7: a fork's branch name says nothing about this repo's branch."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[0]["fork"] = True
        self.assertEqual(self.evidence(prs, url=None)["source"], "git")
        self.assertEqual(self.evidence(prs)["state"], "merged")

    def test_an_open_pr_outranks_an_older_merged_one(self):
        """F17: an open PR on the branch means the work goes on."""
        prs = self.j.parse_forge_prs(fixture("gh_list.json"))
        prs[2]["head"] = "feat/7-x"
        self.assertEqual(self.evidence(prs, url=None)["state"], "open")


class TestForgeChoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def test_the_url_host_decides(self):
        self.assertEqual(self.j.forge_from_url("https://github.com/o/r/pull/7"), "gh")
        self.assertEqual(
            self.j.forge_from_url("https://gitlab.example.invalid/g/p/-/merge_requests/7"),
            "glab")
        self.assertIsNone(self.j.forge_from_url("https://forge.invalid/o/r/pull/7"))
        self.assertIsNone(self.j.forge_from_url(None))

    def test_the_config_names_the_cli(self):
        """The legacy `Forge:` reader, which moved to `_config.forge_cli` (ADR 0028)."""
        for value, want in (("GitHub — CLI: `gh`, pull requests.", "gh"),
                            ("GitLab — CLI: glab", "glab"),
                            ("GitHub", "gh"), ("GitLab", "glab"),
                            ("Gitea — CLI: tea", None), ("<GitHub | GitLab>", None)):
            with self.subTest(value=value):
                self.assertEqual(self.j._config.forge_cli(value), want)


class TestConfiguredForge(unittest.TestCase):
    """T009: `configured_forge` reads the `forge` setting through the resolver (ADR
    0028). The settings file wins; a legacy `Forge:` line still gives the CLI."""

    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".claude").mkdir()
        self.user = self.root / "user-config"
        self.user.mkdir()
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.user)})
        env.start()
        self.addCleanup(env.stop)

    def settings(self, data, where=None):
        path = where or self.root / ".claude" / "shipgate.json"
        path.write_text(json.dumps(data), encoding="utf-8")

    def legacy(self, value, where=None):
        path = where or self.root / ".claude" / "shipgate.md"
        path.write_text("# demo\n\n## Forge & tracker\n\n- Forge: " + value + "\n",
                        encoding="utf-8")

    def forge(self):
        return self.j.configured_forge(self.root)

    def test_the_settings_file_names_the_forge(self):
        for value, want in (("github", "gh"), ("gitlab", "glab")):
            with self.subTest(value=value):
                self.settings({"version": 1, "forge": value})
                self.assertEqual(self.forge(), want)

    def test_the_settings_file_beats_a_legacy_line(self):
        self.legacy("GitHub — CLI: `gh`, pull requests.")
        self.settings({"version": 1, "forge": "gitlab"})
        self.assertEqual(self.forge(), "glab")

    def test_a_legacy_line_still_names_the_cli(self):
        for value, want in (("GitHub — CLI: `gh`, pull requests.", "gh"),
                            ("GitLab — CLI: glab", "glab"), ("GitLab", "glab")):
            with self.subTest(value=value):
                self.legacy(value)
                self.assertEqual(self.forge(), want)

    def test_another_forge_or_a_placeholder_gives_none(self):
        """A legacy line outside the set is a warning, never a refusal: None, as
        before ADR 0028."""
        for value in ("Gitea — CLI: tea", "<GitHub | GitLab>"):
            with self.subTest(value=value):
                self.legacy(value)
                self.assertIsNone(self.forge())

    def test_nothing_set_gives_none(self):
        self.assertIsNone(self.forge())

    def test_the_user_settings_file_cannot_set_it(self):
        """`forge` is a project setting: the user settings file's value is ignored. A
        user legacy line still applies, as before."""
        self.settings({"version": 1, "forge": "gitlab"},
                      self.user / "shipgate.settings.json")
        self.assertIsNone(self.forge())
        self.legacy("GitLab — CLI: glab", self.user / "shipgate.md")
        self.assertEqual(self.forge(), "glab")

    def test_a_bad_value_in_the_settings_file_is_a_usage_error(self):
        self.legacy("GitHub — CLI: `gh`, pull requests.")
        self.settings({"version": 1, "forge": "bitbucket"})
        with self.assertRaises(self.j.UsageError) as caught:
            self.forge()
        self.assertEqual(caught.exception.exit_code, 2)
        message = str(caught.exception)
        for part in (str(self.root / ".claude" / "shipgate.json"), "forge",
                     '"bitbucket"', "github, gitlab"):
            self.assertIn(part, message)


class TestCloseoutRules(unittest.TestCase):
    """T012, FR-015: the project's own post-merge steps, from the **Close-out** section
    of the nearest config file that holds it."""

    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.user = self.root / "user-config"
        self.user.mkdir()
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.user)})
        env.start()
        self.addCleanup(env.stop)

    def config(self, where, body):
        path = where / ".claude" / "shipgate.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# shipgate configuration — demo\n\n## Close-out\n\n" + body,
                        encoding="utf-8")

    def rules(self, start=None):
        return [(r["label"], r["action"]) for r in self.j.closeout_rules(self.root, start)]

    def test_no_section_gives_no_rules(self):
        self.assertEqual(self.rules(), [])

    def test_every_project_step_is_ask(self):
        """The user's ruling on F25 and F26: a project's own steps are arbitrary
        commands, so each one waits for the one close-out question, whatever it does.
        No mark and no word list decide it."""
        self.config(self.root,
                    "- Announce: post a line in the team channel\n"
                    "- Prune: git remote prune origin\n"
                    "- Clean: git branch -D old\n"
                    "- Merge: \"gh\" pr merge 1\n"
                    "- Fetch (run): git fetch --tags\n")
        self.assertEqual(self.rules(), [
            ("Announce", "post a line in the team channel"),
            ("Prune", "git remote prune origin"),
            ("Clean", "git branch -D old"),
            ("Merge", '"gh" pr merge 1'),
            ("Fetch (run)", "git fetch --tags")])
        self.assertNotIn("kind", self.j.CloseoutRule.__annotations__)

    def test_a_label_keeps_its_case_and_its_words(self):
        """F29: the label shows as written; a former mark is just words of it."""
        self.config(self.root, "- Tick #31 in GitHub: tick the child in its issue\n"
                               "- Bump README (run): bump the version line\n")
        self.assertEqual([label for label, _ in self.rules()],
                         ["Tick #31 in GitHub", "Bump README (run)"])

    def test_a_fenced_or_commented_bullet_is_no_rule(self):
        """F4: the section's bullets come through ``section_bullets``, so fenced code
        and HTML comments stay inert."""
        self.config(self.root, "- Prune: git remote prune origin\n\n"
                               "```\n- Wipe: rm -rf build\n```\n\n"
                               "<!-- - Hidden: echo hidden -->\n")
        self.assertEqual(self.rules(), [("Prune", "git remote prune origin")])

    def test_a_wrapped_bullet_is_one_rule(self):
        self.config(self.root, "- Tag the release: once the version-bump commit is on\n"
                               "  main, run claude plugin tag --push in shipgate/\n")
        self.assertEqual(self.rules(), [(
            "Tag the release",
            "once the version-bump commit is on main, run claude plugin tag --push in "
            "shipgate/")])

    def test_a_placeholder_bullet_is_no_rule(self):
        self.config(self.root, "- <Label>: <the action>\n")
        self.assertEqual(self.rules(), [])

    def test_the_nearest_file_wins_and_names_its_source(self):
        self.config(self.root, "- Root: the root's step\n")
        repo = self.root / "svc"
        (repo / ".git").mkdir(parents=True)
        self.config(repo, "- Repo: the repo's step\n")
        got = self.j.closeout_rules(self.root, repo)
        self.assertEqual([(r["label"], r["source"]) for r in got],
                         [("Repo", "svc/.claude/shipgate.md")])

    def test_the_user_file_is_the_last_layer(self):
        (self.user / "shipgate.md").write_text(
            "# mine\n\n## Close-out\n\n- Note: write the release note\n",
            encoding="utf-8")
        got = self.j.closeout_rules(self.root)
        self.assertEqual([(r["label"], r["source"]) for r in got], [("Note", "user file")])


class TestObserveScript(unittest.TestCase):
    """T013, FR-010, FR-019: the shell text that fills a fresh evidence directory."""

    HOSTILE = "feat/x'; rm -rf ~ #$(id)"

    @classmethod
    def setUpClass(cls):
        cls.j = load_journal_module()

    def script(self, kind="closeout", forge="gh", **over):
        facts = {"stream": "feat/7-x", "branch": "feat/7-x", "base": "main",
                 "url": "https://forge.invalid/o/r/pull/7", "project_dir": "/repo"}
        facts.update(over)
        return self.j.observe_script(kind, facts, forge)

    def line(self, text, needle):
        found = [line for line in text.splitlines() if needle in line]
        self.assertEqual(len(found), 1, text)
        return found[0]

    def test_a_fresh_directory_first(self):
        first = self.script().splitlines()[0]
        self.assertIn("mktemp -d", first)
        self.assertIn("|| exit 1", first)

    def test_it_runs_in_the_project_and_writes_the_six_files(self):
        text = self.script()
        self.assertIn("cd /repo || exit 1", text)
        for name in ("forge.json", "refs.txt", "merged.txt", "worktrees.txt", "base.txt",
                     "first-parent.txt"):
            self.assertIn(f'"$d/{name}"', text)
        self.assertIn("git fetch --prune origin", text)
        self.assertIn('"--merged=refs/remotes/origin/$base"', text)
        self.assertIn('git rev-list --first-parent "refs/remotes/origin/$base"', text)
        self.assertIn("git worktree list --porcelain", text)
        self.assertTrue(text.splitlines()[-1].startswith("printf"))

    def test_the_close_out_records_the_stream_worktree_files(self):
        """F60: the close-out's script runs `git status --porcelain --ignored` in the
        linked worktree whose branch is the stream, and keeps the file only when git
        succeeds; the sweep's script does not."""
        text = self.script()
        line = self.line(text, "status --porcelain --ignored")
        self.assertIn('git -C "$w" status --porcelain --ignored --untracked-files=normal',
                      line)
        self.assertIn('"$d/worktree-status.txt"', line)
        self.assertIn("'branch refs/heads/feat/7-x'", self.line(text, "awk"))
        self.assertLess(text.index("worktrees.txt"), text.index("worktree-status.txt"))
        self.assertNotIn("--ignored", self.script(kind="sweep", stream=None, branch=None,
                                                  url=None))

    def test_the_base_comes_from_git_not_the_config(self):
        """F5: the script reads origin/HEAD, else main; no config key names it."""
        text = self.script(base="release/9")
        self.assertIn("git symbolic-ref --quiet --short refs/remotes/origin/HEAD", text)
        self.assertIn('[ -n "$base" ] || base=main', text)
        self.assertNotIn("release/9", text)

    def test_gh_with_the_url(self):
        line = self.line(self.script(), "gh pr view")
        self.assertEqual(shlex.split(line)[:4],
                         ["gh", "pr", "view", "https://forge.invalid/o/r/pull/7"])
        self.assertIn("headRefOid", line)

    def test_gh_without_a_url_lists_the_branch(self):
        line = self.line(self.script(url=None), "gh pr list")
        self.assertIn("--head=feat/7-x", line)
        self.assertIn("--state all", line)

    def test_a_url_that_is_not_https_is_not_used(self):
        """F16: a recorded URL that starts with `--` would reach the CLI as a flag."""
        for forge, needle, flag in (("gh", "gh pr list", "--head=feat/7-x"),
                                    ("glab", "glab mr list", "--source-branch=feat/7-x")):
            for url in ("--repo=x/y", "http://forge.invalid/o/r/pull/7",
                        "file:///merge_requests/7"):
                with self.subTest(forge=forge, url=url):
                    text = self.script(forge=forge, url=url)
                    self.assertNotIn(url, text)
                    self.assertIn(flag, shlex.split(self.line(text, needle)))

    def test_a_value_that_is_not_printable_prints_no_script(self):
        """F15: a newline in a value would split a line of the printed script."""
        for over in ({"branch": "feat/x\nrm -rf ~", "url": None},
                     {"url": "https://forge.invalid/o\r/pull/7"},
                     {"project_dir": "/repo\n/x"}):
            with self.subTest(over=over):
                self.assertEqual(self.script(**over), self.j.NO_COMMAND)

    def test_glab_with_an_mr_url_views_its_iid(self):
        line = self.line(self.script(
            forge="glab", url="https://gitlab.forge.invalid/g/p/-/merge_requests/7"),
            "glab mr view")
        self.assertEqual(shlex.split(line)[:4], ["glab", "mr", "view", "7"])
        self.assertIn("-F json", line)

    def test_glab_without_a_url_lists_the_branch(self):
        line = self.line(self.script(forge="glab", url=None), "glab mr list")
        self.assertIn("--source-branch=feat/7-x", line)
        self.assertIn("--all", line)

    def test_git_only(self):
        text = self.script(forge=None)
        self.assertNotIn("gh ", text)
        self.assertNotIn("glab ", text)
        self.assertIn("no forge CLI", text)
        self.assertIn("refs.txt", text)

    def test_the_sweep_runs_one_list_query(self):
        text = self.script(kind="sweep", stream=None, branch=None, url=None)
        self.assertEqual(text.count("gh pr"), 1)
        self.assertIn("gh pr list --state all --limit 1000", text)
        glab = self.script(kind="sweep", forge="glab", stream=None, branch=None, url=None)
        self.assertEqual(glab.count("glab mr"), 1)

    def test_a_hostile_branch_is_one_word(self):
        for forge, needle, flag in (("gh", "gh pr list", "--head="),
                                    ("glab", "glab mr list", "--source-branch=")):
            with self.subTest(forge=forge):
                words = shlex.split(self.line(
                    self.script(forge=forge, url=None, branch=self.HOSTILE), needle))
                self.assertIn(flag + self.HOSTILE, words)

    def test_a_hostile_url_is_quoted(self):
        text = self.script(url="https://x.invalid/'$(id)")
        self.assertIn("https://x.invalid/'$(id)",
                      shlex.split(self.line(text, "gh pr view")))


# The `Integration branch:` line names `trunk` on purpose: since F5 nothing reads it, and
# the close-out tests below still see `main`, the base the observed `base.txt` names.
CLOSEOUT_CONFIG = """# shipgate configuration — demo

## Forge & tracker

- Forge: GitHub — CLI: `gh`, pull requests.
- Integration branch: `trunk`

## Close-out

- Tag the release: once the version-bump commit is on main, run claude plugin tag
  --push in shipgate/
- Prune: git remote prune origin
"""

MAIN_TREE = "/repo"
WORK_TREE = "/repo.worktrees/feat-7-x"
ORIGIN_MAIN = "5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f7081"


class CloseoutCase(unittest.TestCase):
    """A journaled project with one stream, `feat/7-x`, whose PR was opened."""

    S = "feat/7-x"
    URL = "https://forge.invalid/o/r/pull/7"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        claude = self.root / ".claude"
        claude.mkdir()
        self.db = claude / "shipgate.db"
        (claude / "shipgate.json").write_text(json.dumps({"version": 1, "db": str(self.db)}),
                                               encoding="utf-8")
        (claude / "shipgate.md").write_text(CLOSEOUT_CONFIG, encoding="utf-8")
        self.user = self.root / "user-config"
        self.user.mkdir()
        self.run_j("init", rc=0)
        self.append(self.S, "flow-started", {"request": "#7 the demo",
                                             "report_to": "lead t2 (send t2)"})
        self.append(self.S, "capture-done", {"promoted": [], "dropped": []})

    def env(self):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(self.user)
        return env

    def run_j(self, *args, rc=None):
        proc = subprocess.run([sys.executable, str(JOURNAL), *map(str, args)],
                              cwd=str(self.root), env=self.env(),
                              capture_output=True, text=True)
        if rc is not None:
            self.assertEqual(proc.returncode, rc, proc.stdout + proc.stderr)
        return proc

    def append(self, stream, etype, data):
        self.run_j("--db", self.db, "append", "--stream", stream, "--type", etype,
                   "--data", json.dumps(data), rc=0)

    def opened(self, stream=None):
        self.append(stream or self.S, "verify-run", {"outcome": "pass", "task_ids": []})
        self.append(stream or self.S, "review-verdict", {"verdict": "ready"})
        self.append(stream or self.S, "mr-opened", {"ref": "#7", "url": self.URL})

    def observed(self, pr="MERGED", local=HEAD, remote=HEAD, merged_local=True,
                 worktree=True, branch=None, url=None, worktree_files=()):
        """``worktree_files``: the `git status --porcelain --ignored` lines of the
        stream's worktree; None writes no file (not observed)."""
        branch = branch or self.S
        d = self.root / "observed"
        d.mkdir(exist_ok=True)
        forge = json.loads(fixture("gh_view_merged.json"))
        forge.update({"state": pr, "headRefName": branch, "url": url or self.URL})
        if pr != "MERGED":
            forge.update({"mergedAt": None, "mergeCommit": None})
        (d / "forge.json").write_text(json.dumps(forge) if pr else "", encoding="utf-8")
        refs = [f"{BASE_TIP} refs/heads/main", f"{ORIGIN_MAIN} refs/remotes/origin/main"]
        if local:
            refs.append(f"{local} refs/heads/{branch}")
        if remote:
            refs.append(f"{remote} refs/remotes/origin/{branch}")
        (d / "refs.txt").write_text("\n".join(refs) + "\n", encoding="utf-8")
        merged = [f"{BASE_TIP} refs/heads/main", f"{ORIGIN_MAIN} refs/remotes/origin/main"]
        if local and merged_local:
            merged.append(f"{local} refs/heads/{branch}")
        (d / "merged.txt").write_text("\n".join(merged) + "\n", encoding="utf-8")
        (d / "base.txt").write_text("main\n", encoding="utf-8")
        (d / "first-parent.txt").write_text(f"{ORIGIN_MAIN}\n{BASE_TIP}\n",
                                            encoding="utf-8")
        trees = [f"worktree {MAIN_TREE}\nHEAD {BASE_TIP}\nbranch refs/heads/main\n"]
        if worktree:
            trees.append(f"worktree {WORK_TREE}\nHEAD {HEAD}\nbranch refs/heads/{branch}\n")
        (d / "worktrees.txt").write_text("\n".join(trees), encoding="utf-8")
        status = d / "worktree-status.txt"
        if worktree and worktree_files is not None:
            status.write_text("".join(f"{line}\n" for line in worktree_files),
                              encoding="utf-8")
        elif status.exists():
            status.unlink()
        return d

    def closeout(self, *args, rc=0, stream=None):
        proc = self.run_j("closeout", "--stream", stream or self.S, *args, rc=rc)
        return proc.stdout

    def record(self, text):
        """The record command the plan prints after the `ask once` line, up to its
        heredoc's closing `EOF`."""
        lines = text.splitlines()
        at = next(i for i, line in enumerate(lines) if line.startswith("ask once")) + 1
        end = lines.index("EOF", at)
        return lines[at:end + 1]

    def steps(self, text):
        return [line.strip() for line in text.splitlines()
                if re.match(r"^\s+\d+\. \[", line)]

    def settings(self, extra):
        """Add EXTRA to the project settings file, which already names the db."""
        path = self.root / ".claude" / "shipgate.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(extra)
        path.write_text(json.dumps(data), encoding="utf-8")

    def assert_bad_forge(self, proc):
        self.assertEqual(proc.stdout, "")
        for part in (str(self.root / ".claude" / "shipgate.json"), "forge",
                     '"bitbucket"', "github, gitlab"):
            self.assertIn(part, proc.stderr)

    def events(self):
        out = self.run_j("--db", self.db, "log", "--json", rc=0).stdout
        return json.loads(out)["events"]


class TestCloseout(CloseoutCase):
    """T014, FR-009 to FR-014, SC-006, ADR 0026 as amended (the squash order)."""

    def test_without_evidence_it_prints_the_observe_script_and_the_rerun(self):
        self.opened()
        text = self.closeout()
        self.assertIn("mktemp -d", text)
        self.assertIn(f"gh pr view {self.URL}", text)
        self.assertIn("closeout --stream=feat/7-x --observed=", text)
        self.assertEqual(self.steps(text), [])

    def test_not_merged_exits_4_and_writes_nothing(self):
        self.opened()
        before = len(self.events())
        text = self.closeout("--observed", self.observed(pr="OPEN"), rc=4)
        self.assertIn("not merged (forge gh: OPEN", text)
        self.assertIn("nothing to close", text)
        self.assertEqual(self.steps(text), [])
        self.assertEqual(len(self.events()), before)

    def test_unknown_is_not_merged(self):
        self.opened()
        self.closeout("--observed", self.observed(pr=None, merged_local=False), rc=4)

    def test_the_steps_in_order(self):
        self.opened()
        text = self.closeout("--observed", self.observed())
        steps = self.steps(text)
        kinds = [re.match(r"\d+\. \[(\w+)\]", step).group(1) for step in steps]
        self.assertEqual(kinds, ["skip", "run", "run", "ask", "ask", "run", "run"], text)
        self.assertIn("capture-done is recorded and the ledger is empty", steps[0])
        self.assertIn("--type=flow-completed", steps[1])
        self.assertIn(f'test -z "$(git -C {MAIN_TREE} status --porcelain)" && git -C '
                      f"{MAIN_TREE} merge --ff-only origin/main", steps[2])
        self.assertIn("Tag the release", steps[3])
        self.assertIn("Prune", steps[4])
        self.assertIn("report to lead t2 (send t2)", steps[5])
        self.assertEqual(steps[6],
            f"7. [run] last, one Bash call: git -C {MAIN_TREE} worktree remove "
            f"{WORK_TREE} && git -C {MAIN_TREE} branch -d feat/7-x")

    def test_the_flow_completed_payload_carries_the_evidence(self):
        self.opened()
        step = self.steps(self.closeout("--observed", self.observed()))[1]
        data = json.loads(shlex.split(step.split("] ", 1)[1])[-1].split("=", 1)[1])
        self.assertEqual(data["reason"], "merged")
        self.assertEqual(data["url"], self.URL)
        self.assertIn("forge gh: MERGED", data["evidence"])

    def test_the_printed_flow_completed_runs(self):
        self.opened()
        step = self.steps(self.closeout("--observed", self.observed()))[1]
        proc = subprocess.run(step.split("] ", 1)[1], shell=True, cwd=str(self.root),
                              env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.events()[-1]["type"], "flow-completed")

    def test_the_ledger_step_runs_only_with_entries(self):
        self.opened()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ledger.md").write_text("- 2026-11-20 — gotcha: a\n- b\n",
                                                     encoding="utf-8")
        step = self.steps(self.closeout("--observed", self.observed()))[0]
        self.assertTrue(step.startswith("1. [run] residual capture: 2 untriaged entries"),
                        step)

    def test_no_capture_done_runs_the_full_capture(self):
        self.append("feat/8-y", "flow-started", {"request": "x"})
        self.opened("feat/8-y")
        step = self.steps(self.closeout(
            "--observed", self.observed(branch="feat/8-y"), stream="feat/8-y"))[0]
        self.assertTrue(step.startswith("1. [run] full Capture"), step)

    def test_a_squash_merge_asks_and_deletes_after_the_worktree(self):
        self.opened()
        text = self.closeout("--observed", self.observed(merged_local=False))
        steps = self.steps(text)
        squash = [s for s in steps if "squash-merged" in s]
        self.assertEqual(len(squash), 1, text)
        self.assertTrue(squash[0].startswith("6. [ask]"), squash[0])
        # The ask step prints no command: a flow that runs the steps in order must
        # not delete the ref before the worktree goes (git refuses then, exit 128).
        self.assertNotIn("update-ref", squash[0])
        self.assertEqual(steps[-1], f"8. [run] last, one Bash call: git -C {MAIN_TREE} "
                                    f"worktree remove {WORK_TREE}")
        lines = text.splitlines()
        alt = lines[lines.index("  " + steps[-1]) + 1].strip()
        self.assertEqual(alt, f"when the user chose step 6: git -C {MAIN_TREE} worktree "
                              f"remove {WORK_TREE} && git -C {MAIN_TREE} update-ref -d "
                              f"refs/heads/feat/7-x {HEAD}")

    def test_an_ignored_file_makes_the_removal_an_ask_step(self):
        """F60, the user's ruling: git deletes ignored files with the worktree, so a
        worktree that holds one is removed only when the user chooses it. The step
        shows the count and the files; unchosen, the worktree and the branch stay and
        the report names them."""
        self.opened()
        text = self.closeout("--observed", self.observed(worktree_files=["!! .env"]))
        steps = self.steps(text)
        kinds = [re.match(r"\d+\. \[(\w+)\]", step).group(1) for step in steps]
        self.assertEqual(kinds, ["skip", "run", "run", "ask", "ask", "ask", "run", "run"])
        self.assertEqual(steps[5], f"6. [ask] remove the worktree {WORK_TREE}: it holds 1 "
                                   "ignored or untracked path (.env), deleted with the "
                                   "worktree. Run nothing here: the last step runs it")
        self.assertIn("; the worktree and the branch go next only if the user chose step 6; "
                      f"else name the worktree {WORK_TREE} and the branch feat/7-x as kept",
                      steps[6])
        self.assertNotIn("go next;", steps[6])
        self.assertEqual(steps[7], f"8. [run] last, one Bash call, only when the user chose "
                                   f"step 6: git -C {MAIN_TREE} worktree remove {WORK_TREE} "
                                   f"&& git -C {MAIN_TREE} branch -d feat/7-x")
        ask = next(line for line in text.splitlines() if line.startswith("ask once"))
        self.assertIn(f'"Remove worktree feat/7-x" runs: git -C {MAIN_TREE} worktree remove '
                      f"{WORK_TREE} && git -C {MAIN_TREE} branch -d feat/7-x)", ask)

    def test_an_untracked_file_makes_the_removal_an_ask_step(self):
        """Git refuses to remove a worktree with an untracked file; the step names the
        file, and a chosen removal that git refuses stops."""
        self.opened()
        text = self.closeout("--observed", self.observed(worktree_files=["?? notes.txt"]))
        removal = [s for s in self.steps(text) if "remove the worktree" in s]
        self.assertEqual(len(removal), 1, text)
        self.assertIn("1 ignored or untracked path (notes.txt)", removal[0])

    def test_a_worktree_with_no_such_file_is_removed_with_no_question(self):
        """The user's ruling: with none, the removal runs with no question. A changed
        tracked file is none of them: git refuses that removal itself (SC-007)."""
        self.opened()
        for files in ((), (" M src/a.py",)):
            with self.subTest(files=files):
                text = self.closeout("--observed", self.observed(worktree_files=files))
                self.assertNotIn("remove the worktree", text)
                self.assertNotIn("Remove worktree", text)
                self.assertTrue(self.steps(text)[-1].startswith(
                    "7. [run] last, one Bash call: "), text)

    def test_unobserved_worktree_files_make_the_removal_an_ask_step(self):
        """No guessing: when the worktree's files were not observed, the removal is
        asked."""
        self.opened()
        text = self.closeout("--observed", self.observed(worktree_files=None))
        removal = [s for s in self.steps(text) if "remove the worktree" in s]
        self.assertEqual(len(removal), 1, text)
        self.assertIn("its files were not observed", removal[0])

    def test_the_removal_step_shows_the_count_and_the_first_files(self):
        self.opened()
        files = ["!! node_modules/"] + [f"!! cache/{n}.tmp" for n in range(6)]
        text = self.closeout("--observed", self.observed(worktree_files=files))
        removal = next(s for s in self.steps(text) if "remove the worktree" in s)
        self.assertIn("it holds 7 ignored or untracked paths (node_modules/, cache/0.tmp, "
                      "cache/1.tmp, cache/2.tmp, cache/3.tmp, …), deleted with the worktree",
                      removal)

    def test_an_asked_removal_and_a_squash_deletion_run_together(self):
        """The squash deletion needs the worktree gone first, so its line names both
        steps."""
        self.opened()
        text = self.closeout("--observed", self.observed(merged_local=False,
                                                         worktree_files=["!! .env"]))
        steps = self.steps(text)
        self.assertTrue(steps[5].startswith("6. [ask] remove the worktree"), steps[5])
        self.assertTrue(steps[6].startswith("7. [ask] delete the squash-merged"), steps[6])
        self.assertTrue(steps[-1].startswith("9. [run] last, one Bash call, only when the "
                                             "user chose step 6: "), steps[-1])
        lines = text.splitlines()
        alt = lines[lines.index("  " + steps[-1]) + 1].strip()
        self.assertTrue(alt.startswith("when the user chose steps 6 and 7: "), alt)
        self.assertIn("update-ref -d refs/heads/feat/7-x", alt)

    def test_no_squash_step_after_a_merge_commit(self):
        self.opened()
        self.assertNotIn("update-ref", self.closeout("--observed", self.observed()))

    def test_every_project_step_is_an_ask_step(self):
        """The user's ruling on F25 and F26, in the plan: a local, a forced and a
        formerly `(run)` project step are each `[ask]`, named in the one question."""
        (self.root / ".claude" / "shipgate.md").write_text(
            CLOSEOUT_CONFIG.split("## Close-out")[0] + "## Close-out\n\n"
            "- Prune (run): git remote prune origin\n- Clean: git branch -D old\n",
            encoding="utf-8")
        self.opened()
        text = self.closeout("--observed", self.observed())
        project = [step for step in self.steps(text) if "(Close-out," in step]
        self.assertEqual([step.split("] ", 1)[0] for step in project],
                         ["4. [ask", "5. [ask"], text)
        ask = next(line for line in text.splitlines() if line.startswith("ask once"))
        self.assertIn('"Prune (run)" runs: git remote prune origin; "Clean" runs: git '
                      'branch -D old', ask)

    def test_one_question_names_the_ask_steps_and_the_record(self):
        self.opened()
        text = self.closeout("--observed", self.observed())
        ask = [line for line in text.splitlines() if line.startswith("ask once")]
        self.assertEqual(len(ask), 1, text)
        self.assertIn('header "Close-out"', ask[0])
        self.assertIn("multi-select", ask[0])
        record = self.record(text)
        head, body, end = record[0], record[1], record[-1]
        self.assertEqual(len(record), 3, record)
        self.assertTrue(head.endswith(" --batch <<'EOF'"), head)
        self.assertEqual(end, "EOF")
        words = shlex.split(head.split(" <<", 1)[0])
        self.assertIn("--actor=user", words)
        line = json.loads(body)
        self.assertEqual(line["type"], "gate-decision")
        data = line["data"]
        self.assertEqual((data["gate"], data["mode"], data["raised_by"]),
                         ("close-out", "ask", "user"))
        self.assertNotIn("source", data)

    def test_each_option_shows_the_command_the_user_approves(self):
        """F53: the question names each [ask] step's command beside its label, so the
        user approves a command, not a name; the squash step shows its update-ref."""
        self.opened()
        text = self.closeout("--observed", self.observed(merged_local=False))
        ask = next(line for line in text.splitlines() if line.startswith("ask once"))
        self.assertIn('"Tag the release" runs: once the version-bump commit is on main, '
                      'run claude plugin tag --push in shipgate/; "Prune" runs: git '
                      'remote prune origin; "Delete branch feat/7-x" runs: git -C ', ask)
        self.assertIn(f"update-ref -d refs/heads/feat/7-x {HEAD}", ask)

    def test_the_forge_setting_chooses_the_cli(self):
        """T009: with a URL whose host names no forge, the `forge` setting decides."""
        self.settings({"forge": "gitlab"})
        self.opened()
        text = self.closeout()
        self.assertIn("glab mr list --source-branch=feat/7-x", text)
        self.assertNotIn("gh pr", text)

    def test_a_bad_forge_setting_stops_the_close_out(self):
        """T009: a value outside its set in the settings file exits 2 and names the
        file, the key, the value and the set, even when the URL names the forge."""
        self.URL = "https://github.com/o/r/pull/7"
        self.opened()
        self.settings({"forge": "bitbucket"})
        for args in ((), ("--observed", self.observed())):
            with self.subTest(args=args):
                proc = self.run_j("closeout", "--stream", self.S, *args, rc=2)
                self.assert_bad_forge(proc)

    def test_no_question_without_an_ask_step(self):
        (self.root / ".claude" / "shipgate.md").write_text(
            CLOSEOUT_CONFIG.split("## Close-out")[0], encoding="utf-8")
        self.opened()
        text = self.closeout("--observed", self.observed())
        self.assertNotIn("ask once", text)
        self.assertNotIn("[ask]", text)

    def test_a_rerun_skips_what_is_done(self):
        self.opened()
        self.append(self.S, "flow-completed", {"reason": "merged"})
        text = self.closeout("--observed", self.observed(local=None, worktree=False))
        steps = self.steps(text)
        self.assertTrue(steps[1].startswith("2. [skip] flow-completed"), steps[1])
        self.assertTrue(steps[-1].startswith("7. [skip]"), steps[-1])

    def test_a_stream_whose_branch_has_another_name_exits_4(self):
        """The user's round-3 ruling: stream `feature/7-x`, recorded PR and branch
        `7-x` merged and in a worktree: the close-out exits 4, names the sweep, and
        plans no worktree removal and no branch deletion."""
        s = "feature/7-x"
        self.append(s, "flow-started", {"request": "x"})
        self.append(s, "capture-done", {"promoted": [], "dropped": []})
        self.opened(s)
        before = len(self.events())
        text = self.closeout("--observed", self.observed(branch="7-x"), stream=s, rc=4)
        self.assertIn("journal.py sweep", text)
        self.assertEqual(self.steps(text), [])
        self.assertNotIn("worktree remove", text)
        self.assertNotIn("branch -d", text)
        self.assertEqual(len(self.events()), before)

    def test_no_worktree_switches_the_checkout_first(self):
        self.opened()
        d = self.observed(worktree=False)
        (d / "worktrees.txt").write_text(
            f"worktree {MAIN_TREE}\nHEAD {HEAD}\nbranch refs/heads/feat/7-x\n",
            encoding="utf-8")
        last = self.steps(self.closeout("--observed", d))[-1]
        self.assertIn(f'test -z "$(git -C {MAIN_TREE} status --porcelain)" && git -C '
                      f"{MAIN_TREE} switch main && git -C {MAIN_TREE} branch -d feat/7-x",
                      last)

    def test_no_force_flag_anywhere(self):
        self.opened()
        for d in (self.observed(), self.observed(merged_local=False)):
            text = self.closeout("--observed", d)
            body = [line for line in text.splitlines() if not line.startswith("No step")]
            for line in body:
                for word in line.split():
                    self.assertNotIn(word, ("--force", "-f", "-D", "-ff"), line)
        self.assertIn("No step takes --force, -f or -D.", text)

    def test_a_hostile_stream_name_is_quoted(self):
        # A valid git refname: no space, but quotes, `;` and `$(...)` are allowed.
        name = "feat/x';touch${IFS}pwned;$(touch${IFS}pwned2)"
        self.append(name, "flow-started", {"request": "x"})
        self.opened(name)
        text = self.closeout("--observed", self.observed(branch=name), stream=name)
        last = self.steps(text)[-1].split("] ", 1)[1]
        self.assertEqual(shlex.split(last.split("&& ")[-1])[-1], name)
        proc = subprocess.run(["/bin/sh", "-c", "echo " + shlex.quote(name)],
                              cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), name)
        self.assertFalse((self.root / "pwned").exists())
        self.assertFalse((self.root / "pwned2").exists())

    def test_an_unknown_stream_exits_1(self):
        self.run_j("closeout", "--stream", "feat/nope", rc=1)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TestCloseoutInScratchRepos(unittest.TestCase):
    """T015, SC-005, SC-007: the printed commands run against real git. A dirty worktree
    and a branch git calls unmerged survive; a clean merged worktree and its branch go."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        home = self.tmp / "home"
        home.mkdir()
        (home / ".gitconfig").write_text("", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k != SESSION_ENV and not k.startswith("GIT_")}
        self.env.update({
            "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.invalid",
            "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.invalid",
            "CLAUDE_CONFIG_DIR": str(home),
        })
        self.origin = self.tmp / "origin.git"
        self.main = self.tmp / "main"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.tmp, "clone", "-q", str(self.origin), str(self.main))
        self.git(self.main, "commit", "-q", "--allow-empty", "-m", "base")
        self.git(self.main, "push", "-q", "origin", "main")
        claude = self.main / ".claude"
        claude.mkdir()
        self.db = claude / "shipgate.db"
        (claude / "shipgate.json").write_text(json.dumps({"version": 1, "db": str(self.db)}),
                                               encoding="utf-8")
        (self.main / ".git" / "info" / "exclude").write_text(".claude/\n", encoding="utf-8")
        self.journal("init")

    def git(self, cwd, *args, ok=True):
        proc = subprocess.run(["git", *args], cwd=str(cwd), env=self.env,
                              capture_output=True, text=True)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def journal(self, *args, rc=0):
        proc = subprocess.run([sys.executable, str(JOURNAL), *map(str, args)],
                              cwd=str(self.main), env=self.env, capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, rc, proc.stdout + proc.stderr)
        return proc.stdout

    def stream(self, branch, worktree=True):
        """A branch with one commit, a worktree for it, and a journaled stream."""
        tree = self.tmp / branch.replace("/", "-")
        if worktree:
            self.git(self.main, "worktree", "add", "-q", "-b", branch, str(tree))
        else:
            self.git(self.main, "switch", "-q", "-c", branch)
            tree = self.main
        (tree / f"{branch.replace('/', '-')}.txt").write_text("work\n", encoding="utf-8")
        self.git(tree, "add", ".")
        self.git(tree, "commit", "-q", "-m", f"work on {branch}")
        self.git(tree, "push", "-q", "origin", branch)
        for etype, data in (("flow-started", {"request": "x"}),
                            ("capture-done", {"promoted": [], "dropped": []})):
            self.journal("--db", self.db, "append", "--stream", branch, "--type", etype,
                         "--data", json.dumps(data))
        return tree

    def merge(self, branch, squash=False):
        """Merge on the 'forge': a merge commit, or a squash, pushed to origin/main."""
        scratch = self.tmp / "forge-clone"
        if not scratch.exists():
            self.git(self.tmp, "clone", "-q", str(self.origin), str(scratch))
        self.git(scratch, "fetch", "-q", "origin")
        self.git(scratch, "reset", "-q", "--hard", "origin/main")
        if squash:
            self.git(scratch, "merge", "-q", "--squash", f"origin/{branch}")
            self.git(scratch, "commit", "-q", "-m", f"squash {branch}")
        else:
            self.git(scratch, "merge", "-q", "--no-ff", "-m", f"merge {branch}",
                     f"origin/{branch}")
        self.git(scratch, "push", "-q", "origin", "main")

    def plan(self, branch, forge=None, rc=0):
        script = self.journal("closeout", "--stream", branch)
        body = "\n".join(line[2:] for line in script.splitlines() if line.startswith("  "))
        proc = subprocess.run(["/bin/sh", "-c", body], cwd=str(self.main), env=self.env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        observed = Path(proc.stdout.strip().split("observed: ", 1)[1])
        self.addCleanup(shutil.rmtree, str(observed), True)
        if forge is not None:
            (observed / "forge.json").write_text(json.dumps(forge), encoding="utf-8")
        return self.journal("closeout", "--stream", branch, "--observed", observed, rc=rc)

    def last(self, plan, alt=False):
        lines = plan.splitlines()
        at = max(i for i, line in enumerate(lines) if re.match(r"^\s+\d+\. \[", line))
        if alt:
            return lines[at + 1].split(": ", 1)[1]
        return re.split(r"last, one Bash call[^:]*: ", lines[at], maxsplit=1)[1]

    def update_main(self, plan):
        """Step 3, as the plan orders it: the integration branch first."""
        step = [line for line in plan.splitlines() if line.startswith("  3. [run] ")]
        self.assertEqual(len(step), 1, plan)
        proc = self.run_sh(step[0].split("] ", 1)[1])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def run_sh(self, command):
        return subprocess.run(["/bin/sh", "-c", command], cwd=str(self.tmp), env=self.env,
                              capture_output=True, text=True)

    def branches(self):
        return self.git(self.main, "branch", "--format=%(refname:short)").stdout.split()

    def test_a_clean_merged_worktree_and_its_branch_go(self):
        tree = self.stream("feat/1-clean")
        self.merge("feat/1-clean")
        plan = self.plan("feat/1-clean")
        self.assertNotIn("remove the worktree", plan)
        self.update_main(plan)
        proc = self.run_sh(self.last(plan))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(tree.exists())
        self.assertNotIn("feat/1-clean", self.branches())

    def test_a_dirty_worktree_survives(self):
        tree = self.stream("feat/2-dirty")
        self.merge("feat/2-dirty")
        (tree / "notes.txt").write_text("unsaved\n", encoding="utf-8")
        plan = self.plan("feat/2-dirty")
        self.assertIn("1 ignored or untracked path (notes.txt)", plan)
        self.update_main(plan)
        proc = self.run_sh(self.last(plan))
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue((tree / "notes.txt").exists())
        self.assertIn("feat/2-dirty", self.branches())

    def test_an_ignored_file_makes_the_removal_an_ask_step(self):
        """F60 against real git: `worktree remove` deletes a worktree that holds only an
        ignored file, so the plan asks first and names the file."""
        tree = self.stream("feat/11-ignored")
        self.merge("feat/11-ignored")
        with open(self.main / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
            fh.write(".env\n")
        (tree / ".env").write_text("SECRET=1\n", encoding="utf-8")
        plan = self.plan("feat/11-ignored")
        self.assertIn("1 ignored or untracked path (.env)", plan)
        self.assertIn("last, one Bash call, only when the user chose step", plan)
        self.update_main(plan)
        proc = self.run_sh(self.last(plan))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(tree.exists())

    def test_hidden_untracked_files_still_make_the_removal_an_ask_step(self):
        """F61: with `status.showUntrackedFiles=no`, plain `git status --ignored` lists
        no ignored file (probed: no output, exit 0) while `worktree remove` still
        deletes it; the observe script overrides the setting."""
        tree = self.stream("feat/12-hidden")
        self.merge("feat/12-hidden")
        self.git(self.main, "config", "status.showUntrackedFiles", "no")
        with open(self.main / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
            fh.write(".env\n")
        (tree / ".env").write_text("SECRET=1\n", encoding="utf-8")
        plan = self.plan("feat/12-hidden")
        self.assertIn("1 ignored or untracked path (.env)", plan)

    def test_a_squash_merged_branch_survives_unless_chosen(self):
        tree = self.stream("feat/3-squash")
        self.merge("feat/3-squash", squash=True)
        head = self.git(tree, "rev-parse", "HEAD").stdout.strip()
        forge = {"state": "MERGED", "url": "https://forge.invalid/o/r/pull/3",
                 "headRefName": "feat/3-squash", "headRefOid": head, "baseRefName": "main",
                 "mergedAt": "2026-11-20T10:02:11Z", "mergeCommit": None}
        plan = self.plan("feat/3-squash", forge)
        self.assertNotIn("branch -d", self.last(plan))
        self.update_main(plan)
        proc = self.run_sh(self.last(plan))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(tree.exists())
        self.assertIn("feat/3-squash", self.branches())

    def test_a_chosen_squash_deletion_runs_after_the_worktree(self):
        tree = self.stream("feat/4-squash")
        self.merge("feat/4-squash", squash=True)
        head = self.git(tree, "rev-parse", "HEAD").stdout.strip()
        forge = {"state": "MERGED", "url": "https://forge.invalid/o/r/pull/4",
                 "headRefName": "feat/4-squash", "headRefOid": head, "baseRefName": "main",
                 "mergedAt": "2026-11-20T10:02:11Z", "mergeCommit": None}
        plan = self.plan("feat/4-squash", forge)
        self.update_main(plan)
        proc = self.run_sh(self.last(plan, alt=True))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(tree.exists())
        self.assertNotIn("feat/4-squash", self.branches())

    def test_a_moved_branch_survives_the_chosen_deletion(self):
        tree = self.stream("feat/5-moved")
        self.merge("feat/5-moved", squash=True)
        head = self.git(tree, "rev-parse", "HEAD").stdout.strip()
        forge = {"state": "MERGED", "url": "https://forge.invalid/o/r/pull/5",
                 "headRefName": "feat/5-moved", "headRefOid": head, "baseRefName": "main",
                 "mergedAt": "2026-11-20T10:02:11Z", "mergeCommit": None}
        plan = self.plan("feat/5-moved", forge)
        self.git(tree, "commit", "-q", "--allow-empty", "-m", "later work")
        proc = self.run_sh(self.last(plan, alt=True))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("feat/5-moved", self.branches())

    def test_a_branch_never_committed_to_is_not_merged_when_main_moves_on(self):
        """F1 against real git: the stream's branch holds no commit of its own, and
        another branch merges into main after it was cut. Git alone must not call it
        merged, so the close-out exits 4 and plans no step."""
        tree = self.tmp / "feat-8-empty"
        self.git(self.main, "worktree", "add", "-q", "-b", "feat/8-empty", str(tree))
        self.git(tree, "push", "-q", "origin", "feat/8-empty")
        for etype, data in (("flow-started", {"request": "x"}),
                            ("capture-done", {"promoted": [], "dropped": []})):
            self.journal("--db", self.db, "append", "--stream", "feat/8-empty", "--type",
                         etype, "--data", json.dumps(data))
        self.stream("feat/9-other")
        self.merge("feat/9-other")
        plan = self.plan("feat/8-empty", rc=4)
        self.assertIn("not merged", plan)
        self.assertIn("first-parent", plan)
        self.assertTrue(tree.exists())
        self.assertIn("feat/8-empty", self.branches())

    def test_the_base_is_read_from_origin_head(self):
        """F5: the observe script writes the integration branch git names."""
        self.git(self.main, "push", "-q", "origin", "main:trunk")
        self.git(self.main, "remote", "set-head", "origin", "trunk")
        self.stream("feat/10-base")
        script = self.journal("closeout", "--stream", "feat/10-base")
        body = "\n".join(line[2:] for line in script.splitlines() if line.startswith("  "))
        proc = self.run_sh(f"cd {shlex.quote(str(self.main))} && {body}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        observed = Path(proc.stdout.strip().split("observed: ", 1)[1])
        self.addCleanup(shutil.rmtree, str(observed), True)
        self.assertEqual((observed / "base.txt").read_text(encoding="utf-8"), "trunk\n")
        tip = self.git(self.main, "rev-parse", "origin/trunk").stdout.strip()
        self.assertIn(tip, (observed / "first-parent.txt").read_text(encoding="utf-8"))

    def test_in_place_the_checkout_switches_first(self):
        self.stream("feat/6-inplace", worktree=False)
        self.merge("feat/6-inplace")
        plan = self.plan("feat/6-inplace")
        self.update_main(plan)
        proc = self.run_sh(self.last(plan))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("feat/6-inplace", self.branches())
        self.assertEqual(self.git(self.main, "branch", "--show-current").stdout.strip(),
                         "main")

    def test_in_place_a_dirty_checkout_stays(self):
        self.stream("feat/7-inplace", worktree=False)
        self.merge("feat/7-inplace")
        (self.main / "notes.txt").write_text("unsaved\n", encoding="utf-8")
        proc = self.run_sh(self.last(self.plan("feat/7-inplace")))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.git(self.main, "branch", "--show-current").stdout.strip(),
                         "feat/7-inplace")


class TestSweep(CloseoutCase):
    """T016, FR-018 to FR-020, SC-008 in shape: one proposal per dormant stream from one
    list query; `--apply` appends the terminal events and names a stream that moved."""

    def setUp(self):
        super().setUp()
        self.rows = []

    def dormant(self, stream, days=20, url=None):
        ts = (datetime.now(timezone.utc) - timedelta(days=days, hours=1)).isoformat()
        n = len([r for r in self.rows if r["stream"] == stream])
        self.rows.append({"stream": stream, "version": n + 1, "type": "flow-started",
                          "data": {"request": "x"}, "ts": ts, "actor": "orchestrator@s1"})
        if url:
            self.rows.append({"stream": stream, "version": n + 2, "type": "mr-opened",
                              "data": {"ref": "#1", "url": url}, "ts": ts,
                              "actor": "orchestrator@s1"})

    def load(self):
        raw = self.root / "rows.jsonl"
        raw.write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        self.run_j("--db", self.db, "import", raw, rc=0)

    def evidence(self, prs, refs=(), merged=(), first_parent=()):
        """The observed files; ``prs`` None writes no forge.json (git evidence only)."""
        d = self.root / "sweep-observed"
        d.mkdir(exist_ok=True)
        if prs is not None:
            (d / "forge.json").write_text(json.dumps(prs), encoding="utf-8")
        base = [f"{BASE_TIP} refs/heads/main", f"{ORIGIN_MAIN} refs/remotes/origin/main"]
        (d / "refs.txt").write_text("\n".join(base + list(refs)) + "\n", encoding="utf-8")
        (d / "merged.txt").write_text("\n".join(base + list(merged)) + "\n",
                                      encoding="utf-8")
        (d / "base.txt").write_text("main\n", encoding="utf-8")
        (d / "first-parent.txt").write_text(f"{ORIGIN_MAIN}\n{BASE_TIP}\n" + "".join(
            f"{oid}\n" for oid in first_parent), encoding="utf-8")
        (d / "worktrees.txt").write_text(f"worktree {MAIN_TREE}\nHEAD {BASE_TIP}\n"
                                         "branch refs/heads/main\n", encoding="utf-8")
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
        for f in d.iterdir():
            os.utime(f, (old, old))
        return d

    def pr(self, head, state, n):
        return {"state": state, "url": f"https://forge.invalid/o/r/pull/{n}",
                "headRefName": head, "headRefOid": HEAD, "baseRefName": "main",
                "mergedAt": "2026-10-02T09:00:00Z" if state == "MERGED" else None,
                "mergeCommit": None}

    def sweep(self, *args, rc=0):
        return self.run_j("sweep", *args, rc=rc).stdout

    def proposals(self, text):
        return [line.split()[:2] for line in text.splitlines()
                if re.match(r"^  (flow-completed|flow-abandoned|unknown|keep) ", line)]

    def test_without_evidence_it_prints_one_list_query(self):
        self.dormant("feat/1-a")
        self.load()
        text = self.sweep()
        self.assertEqual(text.count("gh pr list --state all"), 1)
        self.assertIn("sweep --observed=", text)

    def test_every_disposition_and_its_source(self):
        self.dormant("feat/1-a")
        self.dormant("feat/2-b")
        self.dormant("feat/3-c")
        self.dormant("feat/4-d")
        self.dormant("feat/5-e")
        self.load()
        d = self.evidence(
            [self.pr("feat/1-a", "MERGED", 1), self.pr("feat/2-b", "CLOSED", 2),
             self.pr("feat/3-c", "OPEN", 3)],
            refs=[f"{HEAD} refs/remotes/origin/feat/5-e"])
        text = self.sweep("--observed", d)
        self.assertEqual(self.proposals(text), [
            ["flow-completed", "feat/1-a"], ["flow-abandoned", "feat/2-b"],
            ["keep", "feat/3-c"], ["unknown", "feat/4-d"], ["keep", "feat/5-e"]])
        lines = {l.split()[1]: l for l in text.splitlines() if l.startswith("  ")}
        self.assertIn("dormant 20d", lines["feat/1-a"])
        self.assertIn("forge gh: MERGED", lines["feat/1-a"])
        self.assertIn("git: no local or remote branch", lines["feat/4-d"])
        self.assertIn("forge: no PR/MR for feat/5-e, and a stream with no PR/MR is never "
                      "merged", lines["feat/5-e"])
        self.assertIn("proposed: 1 flow-completed, 1 flow-abandoned, 1 unknown (you "
                      "decide; --apply appends nothing for them), 2 keep", text)
        self.assertIn(f"sweep --observed={d} --apply", text)

    def test_a_branch_on_the_first_parent_line_is_kept(self):
        """F1: a dormant stream whose branch never got a commit of its own sits on
        main's first-parent line; the sweep keeps it."""
        old = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432"
        self.dormant("feat/1-a")
        self.dormant("feat/2-b")
        self.load()
        d = self.evidence(
            None, refs=[f"{old} refs/heads/feat/1-a", f"{HEAD} refs/heads/feat/2-b"],
            merged=[f"{old} refs/heads/feat/1-a", f"{HEAD} refs/heads/feat/2-b"],
            first_parent=[old])
        self.assertEqual(self.proposals(self.sweep("--observed", d)),
                         [["keep", "feat/1-a"], ["flow-completed", "feat/2-b"]])

    def test_with_a_forge_answer_a_stream_with_no_pr_is_never_completed(self):
        """F24, the user's ruling: the forge answered and holds no PR/MR for the
        stream, so a git merge alone proposes keep."""
        self.dormant("feat/2-b")
        self.load()
        d = self.evidence([], refs=[f"{HEAD} refs/heads/feat/2-b"],
                          merged=[f"{HEAD} refs/heads/feat/2-b"])
        self.assertEqual(self.proposals(self.sweep("--observed", d)),
                         [["keep", "feat/2-b"]])

    def test_only_dormant_streams(self):
        self.dormant("feat/1-a")
        self.dormant("feat/2-live", days=1)
        self.load()
        text = self.sweep("--observed", self.evidence([]))
        self.assertEqual([p[1] for p in self.proposals(text)], ["feat/1-a"])
        self.assertNotIn(self.S, text)

    def test_apply_appends_with_reason_evidence_and_url(self):
        self.dormant("feat/1-a")
        self.dormant("feat/2-b")
        self.dormant("feat/3-c")
        self.load()
        d = self.evidence([self.pr("feat/1-a", "MERGED", 1),
                           self.pr("feat/2-b", "CLOSED", 2), self.pr("feat/3-c", "OPEN", 3)])
        before = len(self.events())
        self.sweep("--observed", d)
        self.assertEqual(len(self.events()), before)
        self.sweep("--observed", d, "--apply")
        rows = {e["stream"]: e for e in self.events()[before:]}
        self.assertEqual(set(rows), {"feat/1-a", "feat/2-b"})
        self.assertEqual(rows["feat/1-a"]["type"], "flow-completed")
        self.assertEqual(rows["feat/1-a"]["data"]["reason"], "merged")
        self.assertEqual(rows["feat/1-a"]["data"]["url"], "https://forge.invalid/o/r/pull/1")
        self.assertIn("forge gh: MERGED", rows["feat/1-a"]["data"]["evidence"])
        self.assertEqual(rows["feat/2-b"]["type"], "flow-abandoned")

    def test_a_stream_that_moved_is_skipped_and_named(self):
        self.dormant("feat/1-a")
        self.load()
        d = self.evidence([self.pr("feat/1-a", "MERGED", 1)])
        self.append("feat/1-a", "deviation", {"note": "touched after the observation"})
        out = self.sweep("--observed", d, "--apply")
        self.assertIn("skipped feat/1-a", out)
        self.assertNotIn("flow-completed", [e["type"] for e in self.events()
                                            if e["stream"] == "feat/1-a"])

    def test_no_branch_and_no_pr_of_its_name_is_unknown(self):
        """F44, the user's round-4 ruling: no slug guess in the sweep. An old
        `feature/<slug>` stream whose PR head is `fix/<slug>` (open, merged, or two
        heads) and whose own branch is gone is `unknown`: the user decides, the line
        shows what the sweep looked for, and `--apply` appends nothing for it."""
        self.dormant("feature/1-a")
        self.dormant("feature/2-b")
        self.dormant("feature/3-c")
        self.load()
        d = self.evidence([self.pr("fix/1-a", "OPEN", 1), self.pr("fix/2-b", "MERGED", 2),
                           self.pr("fix/3-c", "MERGED", 3),
                           self.pr("renovate/3-c", "CLOSED", 4)],
                          refs=[f"{HEAD} refs/remotes/origin/fix/1-a"])
        before = len(self.events())
        text = self.sweep("--observed", d)
        self.assertEqual(self.proposals(text), [["unknown", "feature/1-a"],
                                                ["unknown", "feature/2-b"],
                                                ["unknown", "feature/3-c"]])
        line = next(l for l in text.splitlines() if "feature/2-b" in l)
        self.assertIn("forge: no PR/MR for feature/2-b; git: no local or remote branch "
                      "feature/2-b", line)
        self.assertNotIn("guess", text)
        self.assertIn("proposed: 0 flow-completed, 0 flow-abandoned, 3 unknown", text)
        self.assertEqual(self.sweep("--observed", d, "--apply").strip(),
                         "nothing to append")
        self.assertEqual(len(self.events()), before)

    def test_without_forge_evidence_a_gone_branch_is_unknown(self):
        """A squash-merged branch deleted after its merge leaves nothing for git to
        read; the sweep no longer calls that abandoned."""
        self.dormant("feat/1-a")
        self.load()
        self.assertEqual(self.proposals(self.sweep("--observed", self.evidence(None))),
                         [["unknown", "feat/1-a"]])

    def test_the_recorded_pr_counts_whatever_its_head(self):
        """F46 by removal: the recorded PR/MR is the stream's own evidence, not a guess,
        so the sweep reads it although its head has another name."""
        self.dormant("feature/2-b", url="https://forge.invalid/o/r/pull/2")
        self.load()
        text = self.sweep("--observed", self.evidence([self.pr("fix/2-b", "MERGED", 2)]))
        self.assertEqual(self.proposals(text), [["flow-completed", "feature/2-b"]])
        self.assertNotIn("guess", text)

    def test_with_no_forge_configured_the_recorded_urls_choose_it(self):
        """F13: the sweep's one list query uses the forge most dormant streams'
        `mr-opened` URLs name when the config names none."""
        (self.root / ".claude" / "shipgate.md").write_text(
            "# shipgate configuration — demo\n", encoding="utf-8")
        self.dormant("feat/1-a", url="https://github.example.invalid/o/r/pull/1")
        self.dormant("feat/2-b", url="https://github.example.invalid/o/r/pull/2")
        self.dormant("feat/3-c", url="https://gitlab.example.invalid/g/p/-/merge_requests/3")
        self.load()
        text = self.sweep()
        self.assertEqual(text.count("gh pr list --state all"), 1, text)
        self.assertNotIn("glab", text)

    def test_the_forge_setting_beats_the_recorded_urls(self):
        """T009: the `forge` setting chooses the list query; the URLs do not."""
        self.settings({"forge": "gitlab"})
        self.dormant("feat/1-a", url="https://github.example.invalid/o/r/pull/1")
        self.load()
        text = self.sweep()
        self.assertEqual(text.count("glab mr list --all"), 1, text)
        self.assertNotIn("gh pr", text)

    def test_a_bad_forge_setting_stops_the_sweep(self):
        """T009: a value outside its set in the settings file exits 2, even when the
        config's legacy line names a forge."""
        self.dormant("feat/1-a", url="https://github.example.invalid/o/r/pull/1")
        self.load()
        self.settings({"forge": "bitbucket"})
        for args in ((), ("--observed", self.evidence([]))):
            with self.subTest(args=args):
                self.assert_bad_forge(self.run_j("sweep", *args, rc=2))

    def test_with_no_forge_and_no_url_the_sweep_reads_git_only(self):
        (self.root / ".claude" / "shipgate.md").write_text(
            "# shipgate configuration — demo\n", encoding="utf-8")
        self.dormant("feat/1-a")
        self.load()
        self.assertIn("no forge CLI", self.sweep())

    def test_apply_needs_evidence(self):
        self.sweep("--apply", rc=2)

    def test_twenty_streams_twenty_proposals_from_one_list(self):
        prs = []
        for n in range(20):
            self.dormant(f"old/{n}-x", days=8 + n)
            prs.append(self.pr(f"old/{n}-x", ("MERGED", "CLOSED", "OPEN")[n % 3], n))
        self.load()
        text = self.sweep("--observed", self.evidence(prs))
        self.assertEqual(len(self.proposals(text)), 20)


class TestCloseoutAndTheApprovalPath(CloseoutCase):
    """T019: the close-out question and record never pass for #22's go (ADR 0023), and
    a finished stream holds no command gate."""

    SESSION = "sess-closeout"

    def reply(self, answers):
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "reply", "--session", self.SESSION, "--json"],
            input=json.dumps({"via": "question", "answers": answers}),
            cwd=str(self.root), env=self.env(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_the_header_is_no_gate_header(self):
        j = load_journal_module()
        self.assertNotIn(j.reply_word(j.CLOSEOUT_HEADER), ("commit", "publish"))

    def test_an_answer_under_the_header_records_no_go(self):
        self.opened()
        env = {**self.env(), SESSION_ENV: self.SESSION}
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "append", "--stream",
             self.S, "--type", "go-requested", "--data",
             json.dumps({"gate": "publish", "question": "q"})],
            cwd=str(self.root), env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for answer in ("Tag the release, Delete branch feat/7-x", "publish", "push",
                       "yes", "all", "feat/7-x"):
            with self.subTest(answer=answer):
                plan = self.reply([{"header": "Close-out", "answer": answer,
                                    "multi_select": True}])
                self.assertEqual(plan["recorded"], [])
                self.assertEqual([e["type"] for e in plan["events"]], ["reply-witnessed"])

    def test_no_open_request_plans_nothing(self):
        plan = self.reply([{"header": "Close-out", "answer": "Tag the release",
                            "multi_select": True}])
        self.assertEqual(plan["events"], [])

    def test_an_option_label_is_never_a_recorder_word(self):
        j = load_journal_module()
        for label in ("Push", "publish.", " Yes ", "OK!", "go", "approve", "all",
                      "commit", "y"):
            with self.subTest(label=label):
                got = j._option_label(label, 4)
                self.assertTrue(got.startswith("Step 4: "), got)
                self.assertIsNone(j.GATE_WORDS.get(j.reply_word(got)))
                self.assertNotIn(j.reply_word(got), j.GENERAL_WORDS)
        self.assertEqual(j._option_label("Tag the release", 4), "Tag the release")

    def run_record(self, record):
        return subprocess.run(["/bin/sh", "-c", "\n".join(record) + "\n"],
                              cwd=str(self.root), env=self.env(), capture_output=True,
                              text=True)

    def test_the_printed_record_passes_the_journal(self):
        """F22: the user's words go into the heredoc as they are; an apostrophe needs
        no shell quoting."""
        self.opened()
        record = self.record(self.closeout("--observed", self.observed()))
        record = [line.replace("<the close-out question>", "Which close-out steps?")
                      .replace("<the steps the user chose>", "Tag the release (don't tick)")
                  for line in record]
        proc = self.run_record(record)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = self.events()[-1]
        self.assertEqual((row["type"], row["actor"], row["data"]["gate"],
                          row["data"]["decision"]),
                         ("gate-decision", "user", "close-out",
                          "Tag the release (don't tick)"))

    def test_the_hook_reads_the_record_and_lets_it_pass(self):
        """F14, F22: the PreToolUse hook reads the quoted heredoc. The record as
        printed passes it; the same record with a `source` marker does not."""
        from test_hooks import run_hook
        self.opened()
        record = [line.replace("<the close-out question>", "Which steps?")
                      .replace("<the steps the user chose>", "Tag the release")
                  for line in self.record(self.closeout("--observed", self.observed()))]
        payload = {"session_id": "sess-hook", "cwd": str(self.root), "tool_name": "Bash"}
        passed = run_hook("pre_tool_use",
                          {**payload, "tool_input": {"command": "\n".join(record)}},
                          self.root, env_extra={"CLAUDE_CONFIG_DIR": str(self.user)})
        self.assertEqual((passed.returncode, passed.stdout), (0, ""), passed.stderr)
        forged = [record[0], record[1].replace('"gate":', '"source": "question", "gate":'),
                  record[2]]
        held = run_hook("pre_tool_use",
                        {**payload, "tool_input": {"command": "\n".join(forged)}},
                        self.root, env_extra={"CLAUDE_CONFIG_DIR": str(self.user)})
        self.assertEqual(held.returncode, 0, held.stderr)
        self.assertEqual(json.loads(held.stdout)["hookSpecificOutput"]["permissionDecision"],
                         "deny")

    def test_the_record_with_its_placeholders_is_refused(self):
        """F14: the printed record, run as it is, is no decision of the user's."""
        self.opened()
        before = len(self.events())
        proc = self.run_record(self.record(self.closeout("--observed", self.observed())))
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertIn("placeholder", proc.stderr)
        self.assertEqual(len(self.events()), before)
        for key, value in (("question", "<the close-out question>"),
                           ("decision", "<the steps the user chose>")):
            for force in ((), ("--force", "--force-reason", "test")):
                with self.subTest(key=key, force=bool(force)):
                    data = {"gate": "close-out", "question": "q", "decision": "d",
                            "mode": "ask", "raised_by": "user"}
                    data[key] = value
                    proc = self.run_j("--db", self.db, "append", "--stream", self.S,
                                      "--type", "gate-decision", "--actor", "user",
                                      *force, "--data", json.dumps(data))
                    self.assertEqual(proc.returncode, 4, proc.stderr)
        self.assertEqual(len(self.events()), before)

    def test_a_finished_stream_holds_no_command_gate(self):
        """After flow-completed, a tag push from the work branch passes: `authorize`
        reads no live stream (ADR 0026, Consequences)."""
        self.opened()
        self.append(self.S, "flow-completed", {"reason": "merged"})
        out = self.run_j("--db", self.db, "authorize", "--gate", "publish", "--branch",
                         self.S, "--json", rc=0).stdout
        answer = json.loads(out)
        self.assertEqual((answer["verdict"], answer["reason"]), ("pass", "not-live"))


class TestThisRepoConfig(unittest.TestCase):
    """T018: this repo's own **Close-out** section names the tag and the tick; both are
    asked, like every project step."""

    def test_both_steps_are_named(self):
        j = load_journal_module()
        root = Path(__file__).resolve().parents[2]
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(FORGE)}):
            rules = j.closeout_rules(root, root)
        self.assertEqual([r["label"] for r in rules], ["Tag the release", "Tick the child"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
