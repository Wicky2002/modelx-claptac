# U1: information status

Issue: [#9](https://github.com/Wicky2002/modelx-claptac/issues/9).

The console uses independent labels rather than one exclusive status. A reading can
be **observed**, **disputed**, **stale**, and part of a **replay** simultaneously.
Road passability and planned paths are **inferred**. Reference shelter capacities,
population estimates, and fleet entries are **synthetic**. Unreported occupancy
stays unknown; it is not treated as zero when displaying available space.

`atlas/dashboard/dev/information.py` assembles read-only labels from evidence,
conflict flags, timestamps, and causal inputs. Map details, event inspectors, and
intelligence evidence show these labels. Archived benchmark evidence uses its
recorded clock and is explicitly labelled as simulation data.

LiveReplay persists its context in SQLite and stamps inputs with scenario
provenance before ingestion. The console banner remains after stop, completion,
and restart. It shows the scenario's simulated date (when available), or elapsed
scenario time. Agent ingestion still uses wall time; the display clock does not
change scheduling or freshness rules. Ditwah's compressed and rescaled inputs
remain clearly marked as rehearsal data.

Decision cards distinguish proposals and approval records from execution. Alerts
distinguish language sends from recipient acknowledgement. The default LogChannel
is explicitly a local simulation, with no public delivery receipt.

## Verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check atlas tests
. .venv/bin/activate
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e -- information.spec.ts
```

Use an absolute `ATLAS_PYTHON` path if the interpreter is not on PATH (the server
runs from the repository root). `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can point to an
installed Chrome. `ATLAS_SCREENSHOT_DIR` optionally captures the real test screens.
The browser test starts a fresh temporary SQLite database with external messaging,
MQTT, and model calls disabled. Review images are committed under
`docs/screenshots/u1/`.
