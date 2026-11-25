# shipgate glossary

One term per concept. Every skill, agent, command, the README and the config template use
these terms and no synonyms, so a model reading two files never has to guess whether two
words mean two things.

**Contract names are fixed.** Journal event names and payload fields, CLI subcommands and
flags, config section names and keys, setting keys, file and directory names, skill and
agent names: prose uses them exactly as written. Everything else here is a prose term.

## Flow and position

| Term | Definition | Not to be confused with |
|---|---|---|
| **flow** | The eight-phase process (Workspace → Route & Map → Explore → Clarify → Design → Implement → Review → Capture), and one run of it for one piece of work (`flow-started` … `flow-completed`). | *stream* (the journal's record of a run); the *review-feedback cycle* (the Review↔Implement loop after an MR/PR opens, a named loop, not a phase). |
| **phase** | One of the eight. Contract: the `phase-entered.data.phase` values. | *step* (a numbered instruction inside a skill); a Workflow script's internal stages. |
| **step** | A numbered instruction inside a skill ("Step 3 — Write the PRD"). | *phase*. |
| **gate** | A point where the flow may stop and go back: the Clarify gate, the verify gate, the review verdict, the parity gate, the publish gate, the Stop hook. | *check* (one verification inside a phase or gate: the acceptance-criteria check, the branch check); the `check` subcommand (what a session still owes the journal). |
| **verify gate** | Run the one command that proves a claim, read the whole output, report with the evidence (`verify` skill; recorded as `verify-run`). | The review workflow's refuter pass (its `verify` arg); the Review phase ("independent verification"); the orchestrator's filtering pass. |
| **UI task** | A Build Plan task whose `file(s):` paths match a glob of the `ui.globs` setting; a script computes it, never the model (ADR 0031). Its `task-done` needs a registered screenshot at each width of `ui.widths`, or a *screens waiver*. | a task the model judges visual; the impact map's old `UI` tag (gone). |
| **evidence root** | The directory outside every repository that holds the screenshots of UI tasks: `$CLAUDE_CONFIG_DIR/shipgate/evidence`, else `~/.claude/shipgate/evidence`, with one directory per project and one per stream. `journal.py screens` writes it; the journal deletes its files when a stream ends and at each register, and files over 30 days at those moments (there is no timer). | the session scratchpad; the project's `.claude/` directory. |
| **screens waiver** | A `deviation` with `kind: screens-waived`, `task_ids` and a reason in `note`: why no screenshot of a UI task could be taken. The user reads the reason in the digest. It clears no Stop gate finding. | a Stop gate waiver (`kind: gate-waived`). |
| **executive contract** | The rule for `executive` mode (the `autonomy` setting), stated once, in `feature`'s section **The executive contract**: what the orchestrator records where, and the escalation contract. The config's **Extra escalations** extends the escalation contract. | *ask* mode (every gate question goes to the user); the *escalation contract* (the list inside it). |
| **confirm batch** | The risky executive assumptions (class `domain`, `data` or `behaviour`, no source) and the blindspot and UI candidates that clarify puts to the user in one dialog before design, at most 4 with the run's escalations; `journal.py assumptions --risky` computes it from the PRD (ADR 0029). The `clarify_confirm` setting `off` turns the dialog off. | an open clarification marker (`[NEEDS CLARIFICATION]`, an escalation that blocks `clarify-passed`); the veto list in a phase summary. |
| **escalation contract** | The list inside the executive contract: the cases the orchestrator still asks the user about in `executive` mode. Stated in `feature`'s section **The executive contract**, and extended by the config's **Extra escalations**. | the *executive contract* (the whole rule, recording included). |
| **position** | Where a stream stands: its phase, last events, gate decisions. Read from the journal, never inferred. | — |
| **journal** | The append-only event log (`scripts/journal.py`; "flow journal" in full). | *database* (the SQLite file that holds it: the `db` setting). |
| **stream** | The journal's event sequence for one piece of work, named for its branch. Contract: `--stream`. | *flow*; `--feature` (a `status` filter by slug). |
| **status brief** | The output of `journal.py status`: the bound streams in full and one count line for the rest, injected by the SessionStart hook (ADR 0024). `--all` prints every stream. | A subagent's *brief*. |
| **bound stream** | A stream this session drives (it wrote the stream last) or the checkout names (the branch, or the one live stream the nested branches name). The status brief prints only bound streams in full. | a *live* stream (any stream with an event in the last 7 days). |
| **ownership mark** | The line "another session wrote this Nm ago" on a stream that another session wrote within 30 minutes. Hook rows and go rows do not count. | — |
| **close-out** | The plan `journal.py closeout` computes for a merged stream from observed forge and git evidence: residual capture, `flow-completed`, the integration branch, the project's **Close-out** steps, the report, then the worktree and the branch. `[run]` steps run with no question; `[ask]` steps wait for one question, and so does the worktree removal when the worktree holds an ignored or untracked path or its files were not observed (ADR 0025, ADR 0026). | *Capture* (the phase); the user's "merged" (a trigger, never evidence). |
| **sweep** | `journal.py sweep`: a proposed `flow-completed`, `flow-abandoned`, `unknown` (the user decides) or keep for each dormant stream, from one forge list query and the stream's exact names; `--apply` appends the terminal ones after one confirmation. | the *close-out* (one merged stream, with git steps). |
| **handoff brief** | The output of `journal.py handoff --stream S`: one stream's position plus what a fresh session needs to continue it (role, next task, open gates, the rules that bind, where to report). Built from the journal, the artifacts and the config (ADR 0021). | The *status brief* (the bound streams and a count line, at every session start); a subagent's *brief*. |
| **journaled / un-journaled** | A project whose project settings file `.claude/shipgate.json` has a `db` that is not null (a missing `db` means the default database), so the hooks enforce the flow / one with no project settings file or with `"db": null`, where phase is inferred from the artifacts present. A skill tests it so: the status brief is present, or `.claude/shipgate.json` exists and `journal.py config db` prints a `db` that is not null. | — |
| **config** | The behaviour in words that the skills read: the project config `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file `$CLAUDE_CONFIG_DIR/shipgate.md`, else `~/.claude/shipgate.md`. The files layer per section by the rule in `config-template.md`'s header (ADR 0018). Say "project config" or "user file" when the contrast matters. | a *settings file*; the repo's `CLAUDE.md`. |
| **setting** | One key of a settings file, with a value from a fixed set: a word from a list, a number in a range, a path, a glob or a regex. `settings.schema.json` names each setting with its default and scope, and `journal.py config` prints its value and source (ADR 0028). | the *config* (behaviour in words). |
| **settings file** | A JSON file of settings: the project settings file `.claude/shipgate.json`, which also marks the project root, or the user settings file `$CLAUDE_CONFIG_DIR/shipgate.settings.json`, else `~/.claude/shipgate.settings.json`. Per key, the nearer file wins. Written by `setup` or by hand. | the *config*; the *database*. |
| **legacy line** | A setting that a config still writes as a `- Key: value` bullet, such as `- Mode: executive` under `## Autonomy`. It is read until the grace date; `/shipgate:setup` moves it into a settings file. | a config bullet that holds behaviour in words. |
| **grace date** | The last day on which a release reads legacy lines without saying that the grace has ended: the release day of the migration plus 60 days (`x-legacy-until` in `settings.schema.json`). The first release after it stops reading legacy lines. | — |
| **SessionStart hook, Stop hook, PreToolUse hook, PostToolUse hook, FileChanged hook, UserPromptSubmit hook** | The plugin's hooks, named by their harness event. | — |
| **auto-capture** | The hooks recording artifact writes as `artifact-written` events. Contract: `enforce.auto_capture`. | *Capture* (the phase). |
| **go** | The user's approval of one gate (`commit` or `publish`) on one stream (ADR 0023). A `gate-decision` with `decision` equal to the gate, `raised_by: user` and a `source` marker: `question`, `prompt`, `dialog` or `shell`. A publish go also satisfies the commit gate. It lasts until the stream's next `task-done`. | a *ready verdict* (it opens no commit and no push); *approval* in general. |
| **go request** | The record that the flow put one gate of one stream to the user. Contract: `go-requested`. | the *question* itself (the request keeps its text). |
| **reply** | The user's answer: a question answer or a typed prompt. | a subagent report or a relayed message (a prompt that starts with a tag is no reply). |
| **exact go** | A go that the reply states in a fixed form: the gate word as a question answer, a stream name as a selected label, or a typed reply from the built-in word list. | any other reply, which gets a *confirming question*. |
| **witness** | The record that the user replied to an open go request with a reply that is no exact go. It holds no text. Only the recorder writes it. Contract: `reply-witnessed`. | a go (a witness authorizes nothing). |
| **confirming question** | The one gate question the flow asks after a witnessed reply, with the gate header and the gate word as the first option, after a new go request. The recorder records the click as an exact go (ADR 0023, amendment). | the read go of 0.28.0 (`source: read`), which #52 retired: the journal refuses it. |
| **recorder** | The hook that writes an exact go or a witness from a reply (`hooks/reply.py`, on UserPromptSubmit and on PostToolUse for `AskUserQuestion`). It is not a model tool call: the PreToolUse hook refuses a model's command that runs it. | `journal.py reply` (it plans the rows and writes nothing). |
| **command gate** | The PreToolUse check that holds a model's `git commit`, `git push`, `gh pr create` and `glab mr create` until the stream holds a go. Contract: `enforce.command_gate`, `journal.py authorize`. | the *publish gate* of `mr-opened`. |
| **harness** | The agent runtime that executes the skills, hooks, subagents and tools. Named as a product only where the product matters (install, built-in commands). | *host* (the machine, as opposed to a container). |

## Artifacts

| Term | Definition | Not to be confused with |
|---|---|---|
| **artifact** | One of the three documents the flow produces: PRD, ADR, worklog. Contract: `artifact_homes`, `artifact-written`. | *source-of-truth artifact*. |
| **PRD** | What and why: FR-### and SC-###. Lives at the PRD home (`artifact_homes.prd`). | *design*. |
| **ADR** | One decision fork, immutable once accepted. | — |
| **worklog** | The Design + Build Plan document beside the PRD. Contract: `<name>.worklog.md`, `artifact_homes.worklog`, `design-committed.data.worklog`. | — |
| **design** | The worklog's Design section: the how. | *PRD*; *ADR*. |
| **build plan** | The worklog's Build Plan section: ordered tasks (T###), tests as tasks. | — |
| **task** | One build plan item with a "done when". Contract: `task-done`, `task_ids`. | *slice* (a group of tasks introducing new domain shapes). |
| **impact map** | Route & Map's output: primary home, modules touched, obligations, risk signals. | *blast radius* (one number inside it). |
| **source-of-truth artifact** | The primary document or code a brief or a port derives from; it outranks any digest of it. | *artifact*. |
| **reference implementation** | The vetted code new code mirrors, named in the worklog's **Reference implementation** section and in the worker brief; chosen by reading and by code signals, never by being the nearest sibling. | *source-of-truth artifact* (what a brief or port derives from). |
| **ledger** | The staging inbox for learnings (the `ledger` setting, default `docs/ledger.md`), triaged at Capture. | *journal*; *knowledge base*. |

## Roles

| Term | Definition | Not to be confused with |
|---|---|---|
| **orchestrator** | The main session running the flow: routes, dispatches subagents, filters findings, records decisions; the `feature` skill is its playbook. Contract: actor role `orchestrator`, `raised_by: orchestrator`. | *session* (the harness process, with an id); a *worker*. |
| **worker** | A subagent the orchestrator dispatches to implement. It runs on the *worker tier*: one tier below the session, never below Opus. The review fan uses the same tier. Contract: actor role `worker`. | *mechanic* (the cheapest-tier subagent for very mechanical sub-work). |
| **very mechanical** | Work whose brief fixes the exact edit and leaves no call to make: a rename, a pattern applied file by file, collected output. Work that touches a type, a data encoding, a business rule or money never is. The only work that goes to a mechanic; defined in `model-tiers`. | *small* (a small change can still need a call). |
| **subagent** | Any agent dispatched by the Agent tool or a Workflow script: `code-explorer`, `code-architect`, `code-reviewer`, a worker. | *agent* (the definition file, or the `Agent` tool). |
| **explorer / architect / reviewer** | Short for the three bundled subagents. | — |
| **finder / refuter** | The two stages of the review workflow: a finder is a reviewer instance; a refuter tries to disprove one finding with evidence. | — |
| **brief** | The self-contained instructions handed to a subagent. Qualified by recipient at its first mention in a section (worker brief, reviewer brief, explorer brief); a bare "the brief" later in that section means that one. Contract: `finderBrief`, `brief` args. | *status brief*. |
| **fan** | The parallel dispatch of 2-3 subagents (explorer fan, reviewer fan). | — |
| **lens** | Qualified wherever the context does not make the kind clear: a *thinking lens* (a mental model applied at a phase; config `Thinking lenses`), a *review lens* (correctness, conventions+design, simplicity+security, and the *canon lens*), an *explorer lens* (one explorer's focus). | — |
| **canon lens** | The review lens that holds the style canon: one `code-reviewer` that loads the style skills the config's Style section names and scores each broken canon rule as a convention violation (ADR 0012). Contract: the review workflow's `canon` lens and `styleSkills`. | the *conventions+design* lens (the repo's CLAUDE.md and the agreed design, not the style canon). |

## Knowledge

| Term | Definition | Not to be confused with |
|---|---|---|
| **knowledge base** | The durable knowledge layer: the stores the config declares (repo docs by default, a wiki or vault over MCP). | The harness's *built-in memory*. |
| **store** | One backend of the knowledge base. | — |
| **learning** | A piece of knowledge worth keeping (gotcha, decision, style call); appended to the ledger, promoted at Capture. | a review *finding*. |
| **recall / capture / promote / triage** | Pull knowledge before work / write it after / move a ledger line to its home / walk the ledger. | *Capture* (the phase that does the last three). |

## Review

| Term | Definition | Not to be confused with |
|---|---|---|
| **finding** | One reported problem from a reviewer (or one grounded observation from an explorer), with `file:line`, confidence and severity. | *issue* (a tracker issue). |
| **ruling** | The orchestrator's decision on one finding or on gating a trivial diff, recorded as `gate-decision`. | *verdict*. |
| **verdict** | Review's outcome: Ready or Not ready (`ready` / `not-ready`). | — |
| **round** | One review → fix → re-review pass; capped at two. | a worker's dispatch round (model-tiers). |

## Prose

| Term | Definition | Not to be confused with |
|---|---|---|
| **report** | Prose a person reads: a reviewer's findings, a verify result, a debug hypothesis or root cause, a phase summary, a verdict. | an *artifact* (PRD, ADR, worklog). |
| **Writing for people** | The output-style rule every report follows (ADR 0006): sentences of about 20 words with one idea each, common words, one term per concept, one action per step, active voice, every fact kept. The `writing_style` setting `ste-80` extends it to the artifacts. | ASD-STE100 itself (the plugin adopts the principles, not the specification). |

## Code signals

| Term | Definition | Not to be confused with |
|---|---|---|
| **code signals** | The per-file numbers `scripts/signals.py` computes from git history and the import graph; the `code_signals` settings. | — |
| **code graph** | The structure `scripts/signals.py` reads from codegraph's index when the `codegraph` CLI is on `PATH` (ADR 0007): file edges, the tests a diff reaches, and symbol queries through `signals.py graph`. Without it, the regex scanner gives the file edges. The `code_graph` setting: `auto \| off \| root`. | *codegraph*, the third-party tool that builds the index; the *regex scanner*, the fallback. |
| **risk signals** | Those numbers as presented in an impact map, a brief or a suspect list (the "Risk signals" block). | — |
| **risk ranking** | The top files of a hotspots call in risk order, with their `fix`, `churn` and `fan_in` labels and the structure `source` (ADR 0013). Contract: the hotspots JSON's `ranking`, carried by `design-committed` and `review-verdict`. | *risk signals* (the whole table); `fileRisk` (the review workflow's path → risk map). |
| **graph note** | The one line a signals JSON carries when a repository has no usable graph index: why, and how to build one. Contract: `graph_note`. | the *advisory* (shown once per project; the graph note is on every call). |
| **fix-rate** | Share of a file's commits that are fixes. Contract spellings: `fix%` (table), `fix_rate` (JSON). | — |
| **own share** | The current git identity's share of a directory's in-window commits, a number `scripts/signals.py` computes per `--by-dir` row; below 0.10 the row is `unfamiliar`. No name or email leaves the script. Contract: `own_share`, `unfamiliar`, `own_reason`. | *top share* (`top_share`: the share of a file's busiest author, whoever that is). |

## Git and forge

| Term | Definition | Not to be confused with |
|---|---|---|
| **integration branch** | The branch work branches off and merges into (main / master / develop), detected, never hardcoded. | — |
| **forge / tracker** | GitHub or GitLab (CLI `gh` / `glab`) / where issues live. | — |
| **MR/PR** | The merge or pull request. Contract keeps `MR` in `mr-opened` and the `MR watcher` section. | — |
| **umbrella** | A scaffolding directory — a git repo of its own or a plain folder — with real repos nested beneath it; never branched. | — |
| **epic / child issue** | A tracked decomposition / one of its issues, each its own branch, stream and MR/PR. | — |
