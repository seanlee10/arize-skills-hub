# arize-skills-hub

A shared registry for agent skills. Teams register a skill here, and any agent
that loads the registry can use it.

Because a skill is natural-language instruction that agents follow, registering
one is closer to granting execution privileges than to adding a document. A
single malicious or careless skill reaches every consumer of the registry. Every
skill that lands on `main` is therefore scanned automatically before anyone
depends on it.

## Registering a skill

Create one directory under `skills/` containing a single `SKILL.md`:

```
skills/
  your-skill-name/
    SKILL.md
```

`SKILL.md` is the skill: a description of when it applies, and the procedure an
agent should follow. There is no required schema — write it for the agent that
will read it.

Open a pull request. When it merges to `main`, the scan runs against your skill
and nothing else; unchanged skills are not re-scanned.

## What the scan checks

Two stages, in order. The first is deterministic and free; the second costs a
model call and only runs on what survives the first.

**1. Pattern rules** — `policy/rules.yaml`

Regular expressions for violations that need no judgment: instructions to send
data to an external endpoint, references to credentials or credential files,
classic prompt-injection phrasing, obfuscated payloads. A match fails the skill
immediately and the judge is never called.

**2. LLM judge** — `policy/static-scan.md`, run as an Arize evaluator

For everything a regular expression cannot see. The judge reads the whole skill
and rules on three questions:

- **Prompt injection** — does it try to override, nullify, or redefine
  instructions that come from outside the skill?
- **Data exfiltration** — does it send data the skill handles anywhere its
  stated purpose does not require? Hidden recipients count, and an instruction
  to conceal such a step from the user is disqualifying on its own.
- **Privilege escalation** — does it demand capabilities, credentials, tools, or
  file access beyond what it needs to do its job?

The judge rules on what the instructions would cause an agent to *do*, not on
how alarming the wording sounds. A skill whose subject matter is security is not
the same as a skill that is itself unsafe.

### Why two stages

Rules alone miss a paraphrase. A judge alone spends model latency and cost on
violations that are not in doubt, and its verdicts are not reproducible. Running
rules first means blatant cases are decided deterministically and for free — so
the more obviously malicious a skill is, the faster and cheaper it is rejected.

The two fixtures under `skills/_fixtures/` exist to keep both stages honest.
`malicious-sample` is caught by the rules. `email-composer` trips no rule at all
— it instructs a hidden BCC to an external address and tells the agent to hide
that from the user — and is caught only by the judge. If a rule ever fires on
`email-composer`, the rules have grown broader than intended.

## Running the scan locally

```bash
pip install -r requirements.txt
export ARIZE_API_KEY=...          # or configure an `ax` profile

python -m harness.static_scan --skill skills/your-skill-name --dry-run
```

| Flag | Effect |
|---|---|
| `--skill PATH` | Scan one skill directory. Use this while writing a skill. |
| `--all` | Scan every registered skill, ignoring the git diff. |
| `--dry-run` | Judge and report, but skip the Slack notification and the failing exit code. |

With no flags the scan selects targets from the last commit's diff, which is what
CI does.

## When the scan fails

The workflow exits non-zero and posts to Slack with the commit, the author, each
violation, and a link to the run. The GitHub Actions job summary is written on
**every** run, pass or fail, so a quiet Slack channel means "nothing was wrong"
rather than "the workflow is broken".

The verdict rule is deliberately blunt: any rule match, or a judge verdict of
`FAIL`, fails the skill. Severity is reported for triage but does not decide
anything. There is no severity threshold, because a threshold is an invitation to
argue about where to set it.

If the scan cannot reach a verdict — the API key is missing, Arize is
unreachable, a skill comes back unjudged — that is a failure, not a pass. The
gate does not fail open.

## Repository layout

```
skills/
  <name>/SKILL.md         registered skills, team-owned
  _fixtures/              deliberate violations, excluded from the default scan

policy/                   judgment criteria, hub-owned (see CODEOWNERS)
  rules.yaml              deterministic patterns
  static-scan.md          the judge prompt
  arize.yaml              Arize resource ids

harness/                  the scanner
  static_scan.py          CLI entry point
  rules.py                pattern matching
  arize_judge.py          the Arize evaluation pipeline
  targets.py              which skills this commit needs scanned
  report.py               job summary and Slack payload
  findings.py             the shared result type

docs/superpowers/         design and implementation notes
```

Fixtures live one level deeper than real skills, at
`skills/_fixtures/<name>/SKILL.md`. The scan's target glob is
`skills/*/SKILL.md`, so it does not match them — they are scanned only when named
explicitly with `--skill`.

## Ownership

`skills/` belongs to the teams that register skills. Edit your own freely.

`policy/` belongs to the hub maintainers and is protected by `CODEOWNERS`. It
holds the criteria every skill is judged against, so changing it changes the bar
for everyone — including, otherwise, for whoever is trying to get a skill past
it.

Changing `policy/` re-scans every registered skill, not just the changed ones. A
tightened rule that left already-registered skills on the old criteria would
leave a hole in the gate.

## For hub maintainers

The judge is an Arize evaluator rather than a direct model call, so the judgment
prompt is a versioned resource that can be inspected and tuned in the Arize UI,
every scan leaves an audit trail, and verdict drift over time is visible.

`policy/static-scan.md` is the source of truth for the evaluator's template.
Changing the criteria means updating both — they must not drift apart.

`policy/arize.yaml` points at the space, dataset, and evaluator the scan uses.
Because scan data accumulates in a shared dataset and Arize has no per-example
delete, pruning means deleting and recreating the dataset and updating that file.
Until that happens, each run's experiment covers everything accumulated so far.

Required repository secrets: `ARIZE_API_KEY` and `SLACK_WEBHOOK_URL`. Both must
be **secrets**, never repository variables — variables are readable through the
API and are not masked in workflow logs, and this repository is public.

Toolchain: `arize` 8.44.0 with `arize-ax-cli` 0.28.1. The CLI's dependency pin
still names `arize==8.43.1`, so pip reports a conflict; it is cosmetic, and 8.43.1
cannot deserialize the experiments the scan creates.
