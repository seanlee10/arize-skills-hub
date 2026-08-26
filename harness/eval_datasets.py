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
        targets[skill] = EvalTarget(
            skill=skill,
            dataset_id=dataset_id,
            reference=entry.get("reference") or None,
        )
    return targets
