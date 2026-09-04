# herdr

The [Herdr](https://github.com/herdrdev/herdr) agent skill, packaged as a plugin so it can
be pinned and customised.

Herdr is a terminal multiplexer that recognises coding agents running inside its panes. The
skill teaches a Claude session to drive it: split a pane, start a named sibling agent, run a
command somewhere else, read that pane's output, wait for a state change.

It self-gates on `HERDR_ENV=1` and stops when not running inside a Herdr pane, so installing
it is harmless on a machine without Herdr.

## Provenance

`skills/herdr/SKILL.md` is **not authored here**. It is redistributed verbatim from
`herdrdev/herdr`, tag `v0.8.2`, path `skills/herdr/SKILL.md`, under Apache-2.0.

Upstream ships the same file inside the binary, so an installed Herdr can print the copy
that matches itself:

```sh
herdr --skill
```

That output is byte-identical to the repository file for the same release — which is why
this plugin tracks a Herdr *version*, not a branch. A skill fetched from upstream `main` can
describe CLI syntax a released binary does not have.

## Updating after a Herdr upgrade

```sh
herdr --version                                   # note the new version
herdr --skill > skills/herdr/SKILL.md             # release-matched copy
```

Then update the version in `NOTICE`, and bump this plugin in
`.claude-plugin/plugin.json` and the marketplace entry.

Re-running this **discards local customisations**. Diff before overwriting if `NOTICE`
records any.

## Customising

The file is Apache-2.0, so it may be modified — but section 4(b) requires that a modified
file carry a prominent notice saying it was changed. When editing `skills/herdr/SKILL.md`:

1. add a short note at the top of the file stating it was modified from upstream, and
2. record what changed under **Modifications** in `NOTICE`.

Prefer additive edits kept in one clearly marked block: the whole file is replaced wholesale
on the next upgrade, and a contiguous block is far easier to reapply than edits scattered
through the text.

## Licence

Apache-2.0 — see `LICENSE` and `NOTICE`. This differs from the other plugins in this
marketplace, which are MIT; the upstream licence travels with the file.
