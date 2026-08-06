"""Identity task for the Arize experiment.

The artifact under evaluation is the skill text itself, so there is no model
output to generate. The experiment exists only because Arize evaluation tasks
bind to experiments rather than to raw dataset examples, so this task carries
each skill's text through unchanged for the evaluator to judge.
"""


def task(dataset_row):
    props = dataset_row.get("additional_properties", dataset_row)
    return props["skill_body"]
