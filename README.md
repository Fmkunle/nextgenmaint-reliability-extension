# NextGenMaint Reliability Extension

A Claude Cowork companion to Claude for Manufacturing. It helps engineers investigate equipment stops and, when the evidence supports a separate fleet decision, compare maintenance policies. The downloadable report links hypotheses to evidence, shows the first field check, and presents the Weibull and cost results when available.

## Run the synthetic demo

1. In Cowork, enable Claude for Manufacturing and upload [the companion ZIP](reliability-extension-cowork.zip).
2. Start a fresh task. Attach these seven files from [the P101 fixture folder](tests/fixtures/p101).

| Attachment | Purpose |
| --- | --- |
| `plant-context.txt` | Site and asset context |
| `historian-stop-event.json` | Stop event and timestamp |
| `consolidated-dataset.xlsx` | Asset master, downtime and maintenance work orders |
| `sensor-window.csv` | Incident sensor readings |
| `bearing-lives-demo.json` | Comparable bearing lives and right-censored observations |
| `simulation-inputs.json` | Fleet exposure, policy, downtime and cost assumptions |
| `sweeps.json` | Replacement and inspection intervals for sensitivity tests |

3. Send this prompt.

```text
/rca

Investigate synthetic downtime event DEMO-STOP-P101 for pump P101 at DEMO_MINE_A. Use the attached incident evidence for 09:45–10:00 UTC on 15 October 2026. No NCR is available. Give me the leading hypotheses, the key evidence gap and the first field check.

Separately, evaluate whether the synthetic fleet should change its current 6,000-operating-hour bearing replacement policy. Use the attached life history, simulation assumptions and sensitivity inputs. Ask me to confirm the proposed inputs before calculating. Keep the fleet decision separate from the cause of the P101 stop.

Attach the downloadable HTML report with the RCA, Weibull chart, remaining-life risk calculator and 10-year strategy comparison. Keep the task reply brief.
```

4. Check the proposed assumptions and select **Confirm and generate report**, or reply **Confirm** in chat. Open the downloadable HTML. Under **Reliability and maintenance strategy**, enter a bearing age of 4,500 h and 500 h until intervention. The synthetic estimate is about 15.4%, with an approximate interval of 11.8% to 20.0%.

For the CMMS-only case, start a fresh task, attach [CV207 work history](tests/fixtures/cmms-only/work-history.json) and ask `/rca CV207 stopped again during loading. Investigate the recurrence using the attached work history.` Confirm the incident and decide whether to proceed with a limited investigation when prompted.

## Validation and production scope

Run the numerical simulator checks with `python -B tests/test_maintenance_validation.py`. The supplied records are synthetic. Earlier Cowork runs exercised the two-plugin handoff, a CMMS-only investigation and strategy reporting. The latest ZIP was checked locally and still needs a fresh Cowork acceptance run.

The demo works with supplied files. A production rollout would need authorised read-only sources, site-specific asset and tag mappings, verified time alignment and data coverage, and reviewed lifetime and cost assumptions. Live Snowflake retrieval remains untested. Engineers verify causes and approve any maintenance strategy change.
