# Evaluation dataset sources

The uploaded copy in Arize is the one the loop reads; these files are the source
it was built from, kept so a dataset can be audited or rebuilt.

`to-questionnaire.json` carries an extra `stress` field per example, recording
what that scenario is meant to probe. **`stress` is not uploaded.** It names the
failure mode under test, so a task or evaluator that saw it would be told the
answer — the example would stop measuring anything. Strip it before upload:

    python3 -c "import json;d=json.load(open('policy/eval-datasets/to-questionnaire.json'));json.dump([{k:v for k,v in r.items() if k!='stress'} for r in d],open('/tmp/up.json','w'))"
    ax datasets create -n to-questionnaire-eval -s <space_id> -f /tmp/up.json

`dialog-summary` has no file here: it uses `samsum_small`, which already existed
in the space and was not built for this repo.
