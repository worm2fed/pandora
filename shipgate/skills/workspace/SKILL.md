---
name: workspace
description: First step before any feature work — get onto the right branch off a clean base instead of silently building on whatever's checked out. Detects git state, branches off the up-to-date integration branch (main/master/develop, never hardcoded) using the repo's naming convention, confirms before switching, and offers a worktree when isolation is wanted. Use at the very start of a feature/bug, or when resuming and unsure which branch you should be on.
---

# Workspace

Before exploring, designing, or writing anything, make sure the work will land on the **right
branch off a clean base**. The failure this prevents is concrete: starting a feature on top of
an unrelated branch that happened to be checked out, so the new work builds on someone else's
WIP and the diff is polluted. Establishing the workspace costs a few seconds; untangling a
feature branched off the wrong base does not.

**Never silently operate on the checked-out branch. Always confirm before switching or
creating a branch.**

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## Which repo — resolve this FIRST if repos are nested

Some checkouts are an **umbrella**: a scaffolding repo with each real project a nested git repo
beneath it. Detect this by the **nested repos, not the absence of the umbrella's own `.git`** —
the umbrella *is* itself a git repo, so a naive "is this a git repo?" check answers *yes* and it
looks branchable. It is not: if nested `*/.git` directories exist (e.g. `source/*/.git`), you
are in an umbrella and its own branch is off-limits. Branching the umbrella by mistake is the
recurring failure this section exists to stop.

**Hard rule: never run a branch-changing command — `git switch -c`, `git checkout -b`,
`git worktree add`, branch creation/deletion/reset — in the umbrella.** So:

1. Resolve the **target repo** first — from the issue/request or the impact map
   (`route-and-map`). `cd` into it and do *all* branch/state work there.
2. If the change spans repos, branch in **each affected repo**, never once at the umbrella level.
3. The only time you branch the umbrella itself is when the change genuinely targets its own
   scaffolding files — rare. Confirm explicitly with the user before ever doing so.

The config's **Repo layout** section describes the umbrella and where projects live. With no
config and no nested repos, the working dir is the repo and this section doesn't apply.

## Steps

> All steps below run **inside the target repo** — `cd` there first (per the section above),
> never in the umbrella.

1. **Detect git state** (in the target repo). Current branch (`git branch --show-current`),
   clean or dirty (`git status --porcelain`), and whether the current branch already belongs to
   this work. If switching would disturb a dirty tree, surface that and stop — let the user
   stash/commit/decide. Don't clobber uncommitted work.

2. **Resume or new?**
   - If the checked-out branch is already this feature's branch (matches the issue/slug), you're
     set — continue, no switch.
   - Otherwise it's new work → propose a new branch (next steps).

3. **Pick the base — detect, don't assume.** Find the integration branch rather than hardcoding
   `master`: `git symbolic-ref refs/remotes/origin/HEAD` (or `git remote show origin`) typically
   reveals `main`/`master`/`develop`. Fetch so it's current, and branch off *that*, not off the
   current checkout.

4. **Build the branch name.** Precedence: the config's **Branching** section, then a branch rule
   in the repo's `CLAUDE.md`, otherwise the default:
   ```
   <type>/<issue-id>-<slug>
   ```
   - **type** — `feat` (new feature), `fix` (bug), or `chore` (refactor / deps / docs /
     maintenance). Infer from the work and confirm.
   - **issue-id** — the issue id from your tracker, if one exists; this is the same id `clarify`
     records in the PRD, so capture it once here and reuse it downstream. **Untracked work: omit
     the segment** — `<type>/<slug>` is fine.
   - **slug** — short kebab-case summary of the change.
   - e.g. `feat/1234-add-export-filters`, `fix/1290-date-off-by-one`, `chore/1301-bump-deps`.

5. **Propose and confirm.** State it plainly — "branch `feat/1234-add-export-filters` off
   `main` (fetched, up to date)?" — and wait for confirmation before `git switch -c`. The
   **default is branch-in-place** in the current checkout: no dependency reinstall, and a running
   Docker stack bound to the repo path keeps pointing at your code.

6. **Offer a worktree only when isolation is wanted.** If the user wants their current checkout
   left untouched or needs features in parallel, use `git worktree add .worktrees/<slug> -b
   <branch> <base>` instead. Call out the costs so it's an informed choice: each worktree needs
   its own dependency install (costly if the project has heavy dependencies), and a dev stack
   bound to the main repo path won't see worktree code without reconfiguration. Don't default to this.

## Output

Report the active branch, the base it was cut from, whether it's in-place or a worktree, and any
caveats (dirty tree handled, deps to install). Then hand off to Route & Map.

If you're already on the correct branch for this work, this whole step collapses to a one-line
confirmation — it's a guard, not ceremony.
