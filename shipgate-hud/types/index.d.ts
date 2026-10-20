// The $.state contract of shipgate-hud: every value the module keeps in $.state, declared
// under the plugin's name, and the vocabulary those values share with the hook modules.
// `claude plugin validate` holds each atom to it. The contract must be self-contained (no
// import, no runtime declaration), so the brand and the shared unions live here and the
// hook modules import them; their runtime lists and smart constructors live in the hooks.
// Every shape is a `type`, never an `interface`: the engine's JsonValue needs an index
// signature, which only a type alias gives.

// ---------------------------------------------------------------------------------------
// Brands
// ---------------------------------------------------------------------------------------

/**
 * A primitive tagged with what it means, so two meanings never mix at compile time. The tag
 * is a phantom: no value carries it. A string key, not a `unique symbol`: the contract may
 * not declare a value. Each brand has one smart constructor in the hooks, holding the one
 * commented cast to it.
 */
export type Brand<T, B extends string> = T & { readonly __brand: B }

/** A journal stream name as journal.py prints it (`feature/x`, `fix/1290-date-off-by-one`). Built by `streamName` (journal.ts). */
export type StreamName = Brand<string, 'StreamName'>

/** A git branch name, never `HEAD`. Built by `branchName` (journal.ts). */
export type BranchName = Brand<string, 'BranchName'>

/** A journal event's `seq`: a non-negative integer, unique and increasing in one journal. Built by `eventSeq` (journal.ts). */
export type EventSeq = Brand<number, 'EventSeq'>

/** An ISO 8601 timestamp that `Date.parse` reads. Built by `isoTime` (journal.ts). */
export type IsoTime = Brand<string, 'IsoTime'>

/** A Build Plan task id: `T` and digits (`T002`), as `check`'s grammar reads it (never `T001a`). Built by `taskId` (journal.ts). */
export type TaskId = Brand<string, 'TaskId'>

/** A PRD success criterion id: `SC-` and digits. Built by `criterionId` (journal.ts). */
export type CriterionId = Brand<string, 'CriterionId'>

/** A project-relative path the HUD may read: relative, no `..` segment, no drive or scheme. Built by `projectPath` (journal.ts). */
export type ProjectPath = Brand<string, 'ProjectPath'>

/**
 * A review round's identity across streams, built from the board's stream and round by
 * `roundId` (review.ts). Opaque: only compared for equality, never parsed back.
 */
export type RoundId = Brand<string, 'RoundId'>

// ---------------------------------------------------------------------------------------
// The journal's vocabulary (journal.py prints these; the HUD decodes and draws them)
// ---------------------------------------------------------------------------------------

/** The flow's phases, in flow order (journal.py PHASES). */
export type Phase =
  | 'workspace'
  | 'route-and-map'
  | 'explore'
  | 'clarify'
  | 'design'
  | 'implement'
  | 'review'
  | 'capture'

/**
 * A phase's mark on the timeline, as journal.py computes it. Before the current phase: `done`
 * (entered) or `skipped` (never entered). After it: `revisited` (entered before the stream
 * moved back past it) or `todo` (never entered). With no phase entered, every phase is `todo`.
 */
export type PhaseMark = 'done' | 'skipped' | 'current' | 'revisited' | 'todo'

/** A stream's lifecycle: `live`; `dormant` (no event for the dormant window); `terminal` (finished). */
export type Lifecycle = 'live' | 'dormant' | 'terminal'

/** Who raised a gate decision (`gate-decision.raised_by`; journal.py applies `orchestrator` as the default). */
export type RaisedBy = 'user' | 'orchestrator'

/** How a gate decision was taken (`gate-decision.mode`). */
export type GateMode = 'ask' | 'executive'

/** A verify-run's outcome. */
export type VerifyOutcome = 'pass' | 'fail'

/** A review verdict's value. */
export type VerdictValue = 'ready' | 'not-ready'

/** A success criterion's status in a review verdict (`review-verdict.criteria`). */
export type CriterionStatus = 'met' | 'unmet'

/** The orchestrator's word on a review finding in a verdict (`review-verdict.dispositions`). */
export type Disposition = 'fixed' | 'rejected' | 'deferred'

/** The event that authorized a publish. */
export type AuthorizedBy = 'review-verdict' | 'gate-decision'

/** How `position` found the stream's worklog: an event names it (`event`), or it is the slug-named worklog no other live stream claims (`name`). */
export type WorklogFrom = 'event' | 'name'

/** The phase a stream is in: since when, and whether an implied jump (not a `phase-entered`) put it there. */
export type CurrentPhase = {
  readonly phase: Phase
  readonly enteredAt: IsoTime
  readonly isImplied: boolean
}

/**
 * May the stream publish? Computed by journal.py with the helper `mr-opened` uses: held, or
 * authorized by the event at `seq`, recorded at `at`.
 */
export type PublishAuthorization =
  | { readonly kind: 'held' }
  | { readonly kind: 'authorized'; readonly by: AuthorizedBy; readonly seq: EventSeq; readonly at: IsoTime }

/**
 * One gate decision, as journal.py prints it. `gate` is an open vocabulary (a project may
 * name its own gates). `gate`, `question` and `decision` are null on a row from before the
 * canonical shape that lacks the key or holds a non-string; `mode` is null when absent or
 * outside GateMode.
 */
export type Decision = {
  readonly seq: EventSeq
  readonly gate: string | null
  readonly question: string | null
  readonly decision: string | null
  readonly raisedBy: RaisedBy
  readonly mode: GateMode | null
  readonly at: IsoTime
}

/** The last verify-run of the stream: its outcome, the tasks it covered, when. */
export type Verify = {
  readonly outcome: VerifyOutcome
  readonly taskIds: readonly TaskId[]
  readonly at: IsoTime
}

/**
 * The stream's last review verdict. `criteria` maps an SC id to its status (a criterion the
 * verdict did not judge has no key). `dispositions` is keyed by text, `<path>:<line or ?>`
 * (full or short path, no leading `./`), because the orchestrator writes the key and a
 * finding is matched to it by path suffix. A board captured after `at` ignores the
 * dispositions; a tick made against another `seq` is ignored.
 */
export type Verdict = {
  readonly seq: EventSeq
  readonly at: IsoTime
  readonly verdict: VerdictValue
  readonly criteria: Readonly<Partial<Record<CriterionId, CriterionStatus>>>
  readonly dispositions: Readonly<Record<string, Disposition>>
}

// ---------------------------------------------------------------------------------------
// A journal run's failure (stored by HudView.Failed, so declared here)
// ---------------------------------------------------------------------------------------

/** Where a decoded value did not have the expected shape: a JSON path (`$.features[2].stream`) and what was expected there. */
export type ShapeError = {
  readonly path: string
  readonly expected: string
}

/**
 * Why a journal.py run gave no value. `Cut`: the person denied or interrupted the call the
 * hook ran in. `CannotStart`: the process did not start. `Exited`: a non-zero exit, exit 1
 * for a stream `position` does not know among them. `Unsupported`: exit 2 with argparse's
 * text naming an argument (a flag or a subcommand) this journal.py does not know, an older
 * shipgate; only that text makes an exit 2 `Unsupported`. `Truncated`: stdout over the
 * engine's limit. `NotJson`: stdout did not parse. `BadShape`: it parsed into another shape.
 */
export type RunFailure =
  | { readonly kind: 'Cut' }
  | { readonly kind: 'CannotStart'; readonly message: string }
  | { readonly kind: 'Exited'; readonly exitCode: number; readonly stderr: string }
  | { readonly kind: 'Unsupported'; readonly argument: string }
  | { readonly kind: 'Truncated' }
  | { readonly kind: 'NotJson'; readonly message: string }
  | { readonly kind: 'BadShape'; readonly error: ShapeError }

/** A run failure other than a cut: a cut refresh writes nothing, so it is never a failure to show. */
export type RefreshFailure = Exclude<RunFailure, { readonly kind: 'Cut' }>

// ---------------------------------------------------------------------------------------
// Position v2: the stream the session is bound to, as the band and the pane draw it
// ---------------------------------------------------------------------------------------

/**
 * A Build Plan task's state, first match wins: `failed` (the last verify-run that covered it
 * failed), `done` (a `task-done` recorded), `debt` (ticked in the worklog, no `task-done`),
 * `open`.
 */
export type TaskState = 'done' | 'failed' | 'debt' | 'open'

/** A Build Plan task's line: its id, its title (null when the line has none), and the nearest heading above it in the Build Plan (null when none). */
export type TaskLine = {
  readonly id: TaskId
  readonly title: string | null
  readonly section: string | null
}

/**
 * A Build Plan task as the Plan tab draws it. `lastVerifyAt` is when the last verify-run that
 * covered the task ran: a failing one for `failed` (so never null there), a passing one, or
 * none, for the others.
 */
export type Task =
  | (TaskLine & { readonly state: 'failed'; readonly lastVerifyAt: IsoTime })
  | (TaskLine & { readonly state: Exclude<TaskState, 'failed'>; readonly lastVerifyAt: IsoTime | null })

/** An ADR the design committed to: its title (the file name when the frontmatter has none) and its frontmatter status (null when none). */
export type Adr = {
  readonly path: ProjectPath
  readonly title: string
  readonly status: string | null
}

/** One `##` section of the worklog's Design section, its body reflowed; `lead` / `Design` for the lead-in. */
export type DesignSection = {
  readonly slug: string
  readonly title: string
  readonly markdown: string
}

/** The design as the Design tab draws it: the committed ADRs and the worklog's Design sections. */
export type Design = {
  readonly adrs: readonly Adr[]
  readonly sections: readonly DesignSection[]
}

/** One `- **SC-NNN** — text` line of a PRD's Success criteria section. */
export type Criterion = {
  readonly id: CriterionId
  readonly text: string
}

/** The stream's worklog, how `position` found it, and its Build Plan tasks ([] when the Build Plan lists none). */
export type Plan = {
  readonly worklog: ProjectPath
  readonly from: WorklogFrom
  readonly tasks: readonly Task[]
}

/**
 * The stream's position, mapped from journal.py's `position --json` and the artifacts it
 * names. `plan` is null when the stream has no worklog (or it could not be read); `criteria`
 * is empty when no PRD is named or it lists none.
 */
export type Position = {
  readonly stream: StreamName
  readonly version: number
  readonly lifecycle: Lifecycle
  /** Null when the stream has entered no phase yet. */
  readonly current: CurrentPhase | null
  readonly phases: Readonly<Record<Phase, PhaseMark>>
  /** Newest first. */
  readonly decisions: readonly Decision[]
  readonly plan: Plan | null
  readonly lastVerify: Verify | null
  readonly design: Design
  readonly publish: PublishAuthorization
  readonly criteria: readonly Criterion[]
  readonly lastVerdict: Verdict | null
}

/** How the session is bound to its stream: it wrote to it (`Session`), or a checkout's branch names it (`Branch`). */
export type BindingVia = 'Session' | 'Branch'

/**
 * What the band and the pane show. `Off`: no journaled project (the hooks read any other kind
 * as journaled). `NoJournalScript`: a journaled project, but journal.py was not found.
 * `Unbound`: the session drives no stream; `nearby` are the live streams the checkout names.
 * `Bound`: the session's stream. `Failed`: the last refresh could not read the journal; the
 * text is built from `failure` when drawn (`failureText`); `stale` is the position shown
 * before it, null when none.
 */
export type HudView =
  | { readonly kind: 'Off' }
  | { readonly kind: 'NoJournalScript' }
  | { readonly kind: 'Unbound'; readonly nearby: readonly StreamName[] }
  | { readonly kind: 'Bound'; readonly via: BindingVia; readonly position: Position }
  | { readonly kind: 'Failed'; readonly failure: RefreshFailure; readonly stale: Position | null }

// ---------------------------------------------------------------------------------------
// ReviewState v2: the captured review rounds, the user's marks and ticks
// ---------------------------------------------------------------------------------------

/** The review workflow's severities, most severe first. */
export type Severity = 'BLOCKER' | 'HIGH' | 'MEDIUM' | 'LOW'

/** A finding's severity: one of the known four (any case on the wire), or another label as given, control characters out. */
export type FindingSeverity =
  | { readonly kind: 'known'; readonly severity: Severity }
  | { readonly kind: 'other'; readonly label: string }

/** A file's regression-risk label, as the review workflow's `fileRisk` argument names it. */
export type RiskLabel = 'top' | 'high' | 'mid' | 'low'

/** How a survivor was checked (review-workflow.js): its refuters held, some died, it was over the cap, or it was not targeted. */
export type Verification = 'held' | 'refuters-died' | 'unverified-cap' | 'not-targeted'

/** The fields every finding variant carries. `confidence` is null when the return's is not a finite number; `line` when the finding names none; `risk` when its file has no label. */
export type FindingCore = {
  readonly severity: FindingSeverity
  readonly confidence: number | null
  readonly file: string
  readonly line: number | null
  readonly summary: string
  readonly risk: RiskLabel | null
}

/** A refuter vote, the return's `quorum` text (`<refuting>/<asked>`) parsed: how many refuters counted as refuting, of how many asked. */
export type Quorum = {
  readonly refuting: number
  readonly asked: number
}

/** A finding that survived its refuters. */
export type SurvivorFinding = FindingCore & {
  readonly kind: 'survivor'
  readonly lenses: readonly string[]
  readonly verification: Verification
  readonly quorum: Quorum
}

/** A finding its refuters killed, lifted from the return's `killed[].finding`, with that entry's `quorum`. */
export type KilledFinding = FindingCore & {
  readonly kind: 'killed'
  readonly lenses: readonly string[]
  readonly quorum: Quorum
}

/** A finding under the confidence floor: never sent to refuters. */
export type BelowFloorFinding = FindingCore & {
  readonly kind: 'below-floor'
}

/** The user's word on a survivor, pressed in the pane. */
export type ReviewMark = 'accepted' | 'killed'

/** A survivor with the user's mark on it (null: none yet), so a mark stays with its finding. */
export type BoardSurvivor = {
  readonly finding: SurvivorFinding
  readonly mark: ReviewMark | null
}

/** The return's `counts`, the producer's keys; a key the return did not carry is null (drawn `?`). */
export type ReviewCounts = {
  readonly found: number | null
  readonly deduped: number | null
  readonly candidates: number | null
  readonly refuters: number | null
  readonly unverified: number | null
  readonly survivors: number | null
  readonly killed: number | null
}

/** The return's `coverage`: the refuter counts the board draws; null when the return did not carry one. */
export type ReviewCoverage = {
  readonly refutersRequested: number | null
  readonly refutersReported: number | null
  readonly unverified: number | null
}

/** The review workflow's return as the Review tab draws it, stamped with the stream it was captured under (null: none). */
export type ReviewBoard = {
  readonly stream: StreamName | null
  /** The round within its stream: 1 for the first return captured for it, then one more each time. */
  readonly round: number
  readonly runId: string | null
  readonly at: IsoTime
  readonly counts: ReviewCounts
  readonly coverage: ReviewCoverage
  readonly survivors: readonly BoardSurvivor[]
  readonly killed: readonly KilledFinding[]
  readonly belowFloor: readonly BelowFloorFinding[]
  readonly lensesRun: readonly string[]
  /** The return's `aborted` reason when the run stopped early; null otherwise. */
  readonly aborted: string | null
}

/** Which round the Review tab shows open: the newest, none (every round folded), or the one `id` names. */
export type OpenRound =
  | { readonly kind: 'newest' }
  | { readonly kind: 'folded' }
  | { readonly kind: 'round'; readonly id: RoundId }

/** The user's own word on a criterion, over the journal's: ticked (`on`) or unticked (`off`), made against the verdict `seq` (null: no verdict). */
export type TickOverride = {
  readonly state: 'on' | 'off'
  readonly seq: EventSeq | null
}

/** The user's tick on one criterion of one stream (null: a board captured with no stream). */
export type TickEntry = {
  readonly stream: StreamName | null
  readonly criterion: CriterionId
  readonly override: TickOverride
}

/**
 * The captured review rounds, newest first, at most five per stream, each holding its marks;
 * the tick overrides, at most one per stream and criterion (a criterion with no entry shows
 * the journal's status); and the open round.
 */
export type ReviewState = {
  readonly boards: readonly ReviewBoard[]
  readonly ticks: readonly TickEntry[]
  readonly open: OpenRound
}

// ---------------------------------------------------------------------------------------
// Values the hooks share that are never stored
// ---------------------------------------------------------------------------------------

/**
 * The tags of a `<task-notification>` user turn; `result` is the parsed JSON, null when absent
 * or unparsable. `status` stays text: the engine types a notification's status as a string
 * (`completed`, `failed`, `killed`, or another word its producer wrote).
 */
export type TaskNotification = {
  readonly toolUseId: string | null
  readonly taskId: string | null
  readonly status: string | null
  readonly summary: string | null
  /** The `<output-file>` the engine names: the task's full output, where a long result is kept whole. */
  readonly outputFile: string | null
  readonly result: unknown
}

/** The pane's tabs. */
export type Tab = 'flow' | 'plan' | 'design' | 'review'

declare module 'claude-code' {
  interface PluginState {
    'shipgate-hud': {
      /** What the band and the pane show; replaces v1's `position`, `lastError` and `isJournaled`. */
      view: Shaped<HudView>
      tab: Tab | null
      /** The Design section open in the pane; null means the first one. */
      designOpen: string | null
      /** The review rounds captured this session, with the user's marks and ticks. */
      review: Shaped<ReviewState>
    }
  }
}
