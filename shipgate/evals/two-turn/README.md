# The two-turn check of SC-010

SC-010 (the approval-path PRD, ADR 0023) asks that the flow records a go request and asks
with the gate header, and that after the reply "it can go" it records a read go and asks
no confirming question. `claude plugin eval` cannot judge this: it runs one prompt, and its
sessions have no `AskUserQuestion` tool. `two_turn.py` drives one interactive session under
a pty instead, on the fixture in `fixture.sh`.

## When it runs

After the merge of the release and before its tag. An installed `shipgate` plugin is loaded
over a `--plugin-dir` copy of the same name, so the check runs against the installed copy:
fast-forward the checkout that the installed plugin reads to the merged `main` first, and
check that `claude plugin list` shows the new version. A failure gets a fix PR before any tag.

## How to run it

```bash
python3 shipgate/evals/two-turn/two_turn.py --model <model> --out <scratch dir> \
  [--config-dir <the account that pays>] [--home <scratch HOME>] [--reply-mode prompt]
```

Run it once per session model in use. It exits 0 on a pass, 1 on a fail and 2 when the
session could not be driven (no gate question in turn 1). `<out>/result.json` lists each
check; `<out>/screen.txt` holds the screen text, the first thing to read on a fail.

- `--reply-mode answer` (the default) types the reply into the question's free-text row;
  `--reply-mode prompt` closes the question with Esc and types the reply as a prompt. Both
  are typed replies to an open go request.
- A new directory opens with the trust dialog; the driver accepts it.
- Each run costs about one short session of the model: about $0.50 on Opus, more on a
  larger model.
