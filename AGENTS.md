# AGENTS.md

## Cursor Cloud specific instructions

### What this is
`dynlat` is a self-contained Python discrete-event network simulator (MoE dispatch/combine dynamic-latency study). It is a batch/CLI tool — there is **no web server, database, API, or long-running service**. Running it to completion is the end-to-end test.

### Run / build
- No build step. Run from the repo root: `python3 run.py` (all experiment groups A–E) or `python3 run.py --only <group>` (e.g. `--only buffer`) for a single group.
- Outputs are written to `results/`: `summary.json` plus 11 PNG figures. PNGs are gitignored; `summary.json` is tracked.
- Matplotlib runs headless (writes image files, no display/`$DISPLAY` needed).
- A full `python3 run.py` is compute-heavy and takes several minutes (~4 min observed). Use `--only buffer` (~100s) for a faster smoke check.

### Lint / test
- There is no linter config and no automated test suite in this repo. For a quick sanity check use `python3 -m py_compile run.py dynlat/*.py`.

### Gotchas
- Do **not** initialize the `ns-3-ub` git submodule. It points at a private SSH repo (`git@gitcode.com:lukebest/ns-3-ub.git`), is unused by `run.py`/`dynlat`, and will fail without SSH credentials.
- `numpy` is preinstalled in the base image; `matplotlib` is the only dependency that needs installing. `pip install -r requirements.txt` covers both.
