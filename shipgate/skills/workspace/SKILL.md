---
name: workspace
description: First phase before any feature work — get onto the right branch off a clean base instead of silently building on whatever's checked out. Detects git state, branches off the up-to-date integration branch (main/master/develop, never hardcoded) using the repo's naming convention, confirms before switching, and offers a worktree when isolation is wanted. Use at the very start of a feature/bug, or when resuming and unsure which branch you should be on.
---

# Workspace

Before exploring, designing, or writing anything, make sure the work will land on the **right
branch off a clean base**. The failure this prevents is concrete. A feature starts on top of an
unrelated branch that happened to be checked out. The new work then builds on someone else's
WIP, and the diff is polluted. Establishing the workspace costs a few seconds. Untangling a
feature branched off the wrong base does not.

**Never silently operate on the checked-out branch. Always confirm before switching or
creating a branch.**

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## Which repo — resolve this FIRST if repos are nested

Some checkouts are an **umbrella**: a scaffolding directory with each real project a nested git
repo beneath it. Detect an umbrella by the **nested repos, never by the umbrella's own
`.git`**. An umbrella may be a git repo itself. Then a naive "is this a git repo?" check
answers *yes*, and the umbrella looks branchable; it is not. An umbrella may also be a plain
folder. Then git commands fail at the root, and the repos are one level down. Either way, if
nested `*/.git` directories exist (e.g. `source/*/.git`), you are in an umbrella, and its own
branch is off-limits. Branching the umbrella by mistake is the recurring failure this section
exists to stop.

**Hard rule: never run a branch-changing command in the umbrella.** Such commands are
`git switch -c`, `git checkout -b`, `git worktree add`, and branch creation/deletion/reset. So:

1. Resolve the **target repo** first, from the issue/request or the impact map
   (`route-and-map`). `cd` into it. Do *all* branch/state work there.
2. If the change spans repos, branch in **each affected repo**. Never branch once at the
   umbrella level.
3. Branch the umbrella itself only when the change genuinely targets its own scaffolding
   files. That case is rare. Confirm explicitly with the user before you ever do so.

The config's **Repo layout** section describes the umbrella and where projects live. With no
config and no nested repos, the working dir is the repo, and this section doesn't apply.

## Steps

> All steps below run **inside the target repo**. `cd` there first (per the section above).
> Never run them in the umbrella.

1. **Detect git state** (in the target repo). Find the current branch
   (`git branch --show-current`). Check whether the tree is clean or dirty
   (`git status --porcelain`). Check whether the current branch already belongs to this work.
   If switching would disturb a dirty tree, surface that and stop. Let the user
   stash/commit/decide. Don't clobber uncommitted work.

2. **Resume or new?**
   - If the checked-out branch is already this feature's branch (it matches the issue/slug),
     you're set. Continue, with no switch.
   - Otherwise it's new work. Propose a new branch (next steps).

3. **Pick the base — detect, don't assume.** Find the integration branch rather than
   hardcoding `master`. `git symbolic-ref refs/remotes/origin/HEAD` (or
   `git remote show origin`) typically reveals `main`/`master`/`develop`. Fetch so the
   integration branch is current. Branch off *that*, not off the current checkout.

4. **Build the branch name.** Take the first rule that exists: the config's **Branching**
   section, then a branch rule in the repo's `CLAUDE.md`, otherwise the default:
   ```
   <type>/<issue-id>-<slug>
   ```
   - **type** — `feat` (new feature), `fix` (bug), or `chore` (refactor / deps / docs /
     maintenance). Infer it from the work and confirm it.
   - **issue-id** — the issue id from your tracker, if one exists. This is the same id that
     `clarify` records in the PRD. So capture it once here and reuse it downstream.
     **Untracked work: omit the segment.** `<type>/<slug>` is fine.
   - **slug** — a short kebab-case summary of the change.
   - e.g. `feat/1234-add-export-filters`, `fix/1290-date-off-by-one`, `chore/1301-bump-deps`.

5. **Propose and confirm.** State the proposal plainly: "branch `feat/1234-add-export-filters`
   off `main` (fetched, up to date)?" Wait for confirmation before `git switch -c`. The
   **default is branch-in-place** in the current checkout. Then there is no dependency
   reinstall, and a running Docker stack bound to the repo path keeps pointing at your code.

6. **Offer a worktree only when isolation is wanted.** The user may want the current checkout
   left untouched, or may need features in parallel. Then use
   `git worktree add .worktrees/<slug> -b
   <branch> <base>` instead. Call out the costs, so the choice is an informed one. Each
   worktree needs its own dependency install, which is costly if the project has heavy
   dependencies. A dev stack bound to the main repo path won't see worktree code without
   reconfiguration. Don't default to a worktree.
   **The path is part of the contract.** Run that command from the target repo, so the
   worktree lands in its `.worktrees/<slug>`. Add `.worktrees/` to `.git/info/exclude` once.
   The SessionStart hook and the HUD look there, one level deep. They also look in a
   `.worktrees/` beside an umbrella's repos, for worktrees made by hand. A worktree anywhere
   else is invisible to them. The status brief and the pane then show no position for the live
   work. A session opened in the worktree is "already on the branch" (step 2). From the main
   checkout, go to the worktree rather than check the branch out a second time.

7. **Never move started work silently.** A branch that carries changes can move into a
   worktree, out of one, or to another checkout. It moves only with the same proposal and
   confirmation as a new branch. On a journaled project, it also needs a `deviation` event
   naming the new path
   (`{"note":"branch moved into a worktree .worktrees/<slug>: <why>"}`). That way the next
   session and the HUD find the work where the journal says. The usual trigger is a second
   issue wanting the same checkout. Then **stop and ask**. Either finish or park the first
   issue, or put the *second* in a worktree. Do the worktree only on the user's explicit
   say-so, and never inside epic mode's one-issue-at-a-time loop.

## Output

Report the active branch and the base it was cut from. Say whether it's in-place or a worktree
(with its path). Name any caveats (dirty tree handled, deps to install). Then hand off to
Route & Map.

If you're already on the correct branch for this work, this whole phase collapses to a
one-line confirmation. It's a guard, not ceremony.

## Record the start (journaled projects)

On a project whose config declares a **Journal**, the established branch is where the flow gets
a name. Append it here, the moment it happens, not later. Use one `--batch` (JSONL on stdin):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream <branch> --batch <<'EOF'
{"type":"flow-started","data":{"request":"add export filters","branch":"feat/1234-add-export-filters"}}
{"type":"phase-entered","data":{"phase":"workspace","note":"in place, off main"}}
EOF
```

When the branch lives in a worktree, say so in that `note`, and put the path in `refs`
(`{"phase":"workspace","note":"worktree, off main","refs":[".worktrees/add-export-filters"]}`).
The journal is where a later session learns where the work is.

`flow-started` names the flow. `phase-entered workspace` puts the stream in its first phase, so
the next phase's entry is a single step forward. This matters because `append` refuses a
forward jump over a phase it was never told about. A stream holding only `flow-started` has no
phase at all.

The stream is named for the branch you just established. There is one stream per issue, so an
epic's children each get their own (`epic/<slug>` for the epic-level work itself). A stream of
that name may already be in the status brief. A phase skill that ran before the branch existed
opened it (`route-and-map` on `main`, or a bug diagnosed before its fix branch). It is the same
flow. Append only the `phase-entered workspace` line, a backward step that the gate allows.
Continue on that stream, with no second `flow-started`. Keep `request` to one line. The
journal records position and pointers to artifacts, never their contents. A missing or
unreadable database is an infrastructure failure, not a reason to skip the append. Surface it
loudly. Continue un-journaled only with the user's acknowledgement.
