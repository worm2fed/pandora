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

## Which repo — resolve this FIRST if repos are nested

If the working directory contains nested git repos beneath it (e.g. an umbrella/meta repo with
`*/.git` in subdirectories), resolve the **target repo** first — from the request or the impact
map (`route-and-map`) — and do *all* branch/state work inside it. Never branch the umbrella
itself unless the change genuinely targets its own files, and confirm with the user before doing
so. A plain single-repo project skips this entirely: the working dir is the repo.

## Steps

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

4. **Build the branch name from the repo's convention.** If `CLAUDE.md` documents a branch rule,
   follow it. Otherwise use the default:
   ```
   <type>/<issue-id>-<slug>
   ```
   - **type** — `feat` (new feature), `fix` (bug), or `chore` (refactor / deps / docs /
     maintenance). Infer from the work and confirm.
   - **issue-id** — the tracker issue number if one exists (on GitHub, via `gh`); this is the
     same id `clarify` records in the PRD, so capture it once here and reuse it downstream.
     **Untracked work: omit the segment** — `<type>/<slug>` is fine.
   - **slug** — short kebab-case summary of the change.
   - e.g. `feat/42-export-csv`, `fix/add-null-guard`, `chore/bump-deps`.

5. **Propose and confirm.** State it plainly — "branch `feat/42-export-csv` off
   `main` (fetched, up to date)?" — and wait for confirmation before `git switch -c`. The
   **default is branch-in-place** in the current checkout: no dependency reinstall, and a running
   Docker stack bound to the repo path keeps pointing at your code.

6. **Offer a worktree only when isolation is wanted.** If the user wants their current checkout
   left untouched or needs features in parallel, use `git worktree add .worktrees/<slug> -b
   <branch> <base>` instead. Call out the costs so it's an informed choice: each worktree needs
   its own dependency install (costly if the project has heavy dependencies), and any dev stack
   bound to the main repo path won't see worktree code without reconfiguration. Don't default to this.

## Output

Report the active branch, the base it was cut from, whether it's in-place or a worktree, and any
caveats (dirty tree handled, deps to install). Then hand off to Route & Map.

If you're already on the correct branch for this work, this whole step collapses to a one-line
confirmation — it's a guard, not ceremony.
