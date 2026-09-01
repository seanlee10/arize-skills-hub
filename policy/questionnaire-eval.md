# to-questionnaire — quality rubric

Hub-owner-owned. Source of truth for the Arize evaluator template that scores
`to-questionnaire` output. Changing the criteria here means cutting a new
evaluator version; the two must not drift apart.

Placeholders are **single-brace**. The CLI help says `{{variable}}`, but the
working `skill-static-scan` evaluator uses `{skill_name}` / `{skill_body}`, and
that is what the server stores.

The rubric scores the questionnaire, not the skill text. Every criterion below
is one the skill states about its own output, so this measures the skill against
what it promised rather than against an outside opinion.

## The wrapper is not scored

Step 3 of the skill says to write the questionnaire to a file and report the
path. The evaluation harness is a single model call with no filesystem, so the
skill cannot comply: all eight rows of the first run narrated the write instead
(`**Path:** to-questionnaire-<slug>.md`), and three wrapped the document in a
code fence.

That is a mismatch between the skill and the harness, not a defect in the
questionnaire. Penalising it would score the harness. The rubric therefore reads
past the wrapper and scores the document, while requiring the explanation to
note that a wrapper was present — that observation is exactly the kind of thing
the improvement loop should act on, and it would be lost if the rubric silently
ignored it.

## Diagnostic in progress: the explanation is deliberately short

Four wordings of this rubric lost between two and six of eight rows to
`NOT_PARSABLE` — a complete, well-argued explanation followed by a label the
choice list did not contain — and the failure rate did not track the wording.
The suspicion is weight rather than phrasing: the scan's evaluator, a short
prompt with a binary label, has never failed this way, while this one asks for
six criteria, quoted evidence for each, a note on the wrapper, and then an enum.

This version cuts the explanation to a sentence or two to test that. It is a
measurement, not a destination: a short explanation is worse fuel for the
improvement loop, which reads these to decide what to change. If the theory
holds, the answer is to split the criteria into separate judgements, not to keep
this.

## Measured under this version

Both sides scored with the same rubric version, eight rows each, none lost:

    original skill    5× SOLID, 3× WEAK        0.54
    after the loop    6× EXCELLENT, 2× SOLID   0.92

A score is only comparable against another taken with the same rubric version.
The original skill scored 0.67 under the long-explanation wording and 0.54 under
this one — the short rubric is harsher, not more lenient as expected, so a
number carried across versions would have pointed the wrong way.

## Scale

Four levels, so a change is visible. PASS/FAIL leaves the loop nothing to move.

    UNUSABLE 0 · WEAK 0.33 · SOLID 0.67 · EXCELLENT 1

Upper case, and the prompt forbids a qualifier. Version 1 used lower-case words
and two of eight rows came back `NOT_PARSABLE` — the grader wrote a complete,
well-reasoned explanation and then a label the choice list did not contain. Both
failures were boundary calls ("Not enough to drop a grade.", "Minor."), which is
where a hedged label like "solid, bordering on excellent" gets written. A row
that fails this way is not a low score, it is a missing measurement, and it
silently shrinks the denominator a before/after comparison depends on.

---

```text
You are reviewing a discovery questionnaire produced by a skill called "to-questionnaire". The skill's job: someone faces a decision they cannot resolve alone, and a specific other person holds the missing knowledge. The questionnaire is the document handed to that person.

These were the inputs:

Situation: {situation}
Recipient: {recipient}
What the sender needs back: {needed_back}

--- BEGIN OUTPUT ---
{output}
--- END OUTPUT ---

The output may be wrapped in narration, a reported file path, or a code fence. Read past any wrapper and judge the questionnaire itself. Do not raise or lower the grade for the wrapper.

Judge the questionnaire on the criteria the skill sets for itself:

STRUCTURE - Does it carry a title, a Purpose line naming the decision at stake, a From/To line, a Context paragraph, a How-to-answer note covering deadline and effort, the questions themselves, and a closing catch-all? A missing section is a defect only if the questionnaire needed it.

COVERAGE - Is every item the sender said they need back reachable by some question? An unanswerable questionnaire is the primary failure of this skill.

ONE IDEA PER QUESTION - The skill states questions must never be compound. A question joining two asks with "and" or "or", where the recipient could answer one and leave the other, violates this.

ORDER - Are the questions most-important-first? Async means the sender may get one pass, so what matters most must not sit at the bottom.

PITCH - Does the Context carry what this specific recipient lacks, and no more? Explaining a system to the engineer who built it wastes the one pass; withholding background from a non-technical recipient makes the questions unanswerable. Judge against the recipient named above.

TARGETING THE GAP - Do the questions aim at what the recipient knows and the sender does not? Questions the sender could have answered alone are wasted.

Grade the questionnaire:

EXCELLENT - every criterion met; a recipient could answer it in one pass and the sender would have what they need.
SOLID - meets the criteria with a minor lapse: one section thin, one question that could be sharper.
WEAK - a criterion is clearly violated: a compound question, a needed item nobody asks about, context pitched at the wrong reader.
UNUSABLE - the recipient could not usefully answer, or what came back would not resolve the sender's decision.

In one or two sentences, name the criterion that decided the grade and quote the text that decided it.

When a questionnaire sits between two grades, give it the lower one.

Respond with exactly one of these four words and nothing else: UNUSABLE, WEAK, SOLID, EXCELLENT. No qualifier, no punctuation, no second word.
```
