# packages/contracts

The single readable statement of the things that must agree across components: the upload
contract, metric names, job statuses and failure codes, alert rule keys, resource limits and
the OpenAPI snapshot.

It holds **no logic**. A constant that silently drifts from the code it describes is worse
than no constant, so `tests/test_contracts.py` imports the module that actually enforces each
value (the forecasting library, the API settings, the error hierarchy, `alerts.py`) and fails
when the two disagree.

```
src/forecastops_contracts/__init__.py   constants (typed Final tuples/dicts)
openapi.json                            generated snapshot of the API document
tests/test_contracts.py                 drift tests
```

## Regenerating the API snapshot

The OpenAPI document changes whenever a route, schema or bound changes:

```bash
./.venv/bin/python scripts/export-openapi.py           # rewrite packages/contracts/openapi.json
./.venv/bin/python scripts/export-openapi.py --check   # exit 1 if it is stale
```

CI runs the drift test, so a forgotten regeneration fails the build rather than shipping a
stale contract.
