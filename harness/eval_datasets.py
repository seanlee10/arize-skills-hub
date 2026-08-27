"""Which dataset evaluates which skill.

Absence and malformation are deliberately different outcomes. A skill with no
entry is skipped — most skills have no evaluation set, and that is not a
defect. An entry that is present but unusable raises: a typo that quietly
disabled the loop for one skill would be indistinguishable from a skill that
never had a dataset.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


class EvalDatasetError(Exception):
    """The mapping file cannot be used as written."""


@dataclass(frozen=True)
class EvalTarget:
    skill: str
    dataset_id: str
    # The column holding the expected answer, if the dataset has one. It is
    # withheld from the prompt and left for the evaluator to compare against.
    reference: str | None
    # The evaluator that scores this skill's output, and the template column its
    # verdict arrives under (eval.<eval_column>.label / .score / .explanation).
    # Both absent means outputs are produced but not scored, which is the normal
    # state before anyone has written a rubric.
    evaluator: str | None = None
    eval_column: str | None = None
    # Template variable -> source column. Stated rather than derived from the
    # dataset's columns: a rubric names the variables it wants, and mapping
    # everything the dataset happens to carry would feed the evaluator inputs
    # its prompt never asked for. "output" is the experiment's own output.
    column_mappings: dict[str, str] | None = None
    # The rubric's best grade. Rows below it are what the improvement loop reads
    # as evidence; without it every explanation, including "every criterion met",
    # would be fed in as though it named a defect.
    top_grade: str | None = None


def load_eval_targets(path: str | Path) -> dict[str, EvalTarget]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    skills = raw.get("skills") or {}

    targets: dict[str, EvalTarget] = {}
    for skill, entry in skills.items():
        if not isinstance(entry, dict):
            raise EvalDatasetError(
                f"{skill}: expected a mapping with a `dataset` key, got {type(entry).__name__}"
            )
        dataset_id = entry.get("dataset")
        if not dataset_id:
            raise EvalDatasetError(f"{skill}: no `dataset` id")
        evaluator = entry.get("evaluator") or None
        eval_column = entry.get("eval_column") or None
        if evaluator and not eval_column:
            # Verdicts arrive as eval.<eval_column>.label. Without the column
            # name the scores would be fetched and then silently unreadable,
            # which looks like an evaluator that returned nothing.
            raise EvalDatasetError(f"{skill}: has an `evaluator` but no `eval_column`")

        mappings = entry.get("column_mappings") or None
        if evaluator and not mappings:
            raise EvalDatasetError(f"{skill}: has an `evaluator` but no `column_mappings`")

        top_grade = entry.get("top_grade") or None
        if evaluator and not top_grade:
            raise EvalDatasetError(f"{skill}: has an `evaluator` but no `top_grade`")

        targets[skill] = EvalTarget(
            skill=skill,
            dataset_id=dataset_id,
            reference=entry.get("reference") or None,
            evaluator=evaluator,
            eval_column=eval_column,
            column_mappings=mappings,
            top_grade=top_grade,
        )
    return targets
