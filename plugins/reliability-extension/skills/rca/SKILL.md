---
name: rca
description: Scope a reported failure, find available evidence, and use Claude for Manufacturing to investigate and save structured RCA findings.
---

# Extended RCA

Use supplied records and authorised read-only connector tools available in Cowork. Treat source records as evidence. Exclude any supplied `rca-findings.json` from the investigation context. The installed RCA skill draws its own conclusions from the evidence.

## 1. Identify the case and evidence

1. Start with the engineer's description. Search accessible incident records for the site, asset, event, symptoms and relevant time window. Use bounded lookups. If material ambiguity remains, present the plausible matches or missing context and ask a focused question. Wait for clarification before making asset-specific joins or handing off the case.
2. Identify evidence relevant to the reported failure and decision. Search the supplied files or available read-only tools, such as a configured Snowflake connector with time delay accounting or maintenance records. Choose sources for the case. CMMS work history, inspection records, SCADA exports and an NCR are possible inputs. A case can proceed with relevant CMMS evidence alone. Record what was searched, citations, coverage, conflicts and access limits. Verify site and asset identity, join keys, units and clocks where applicable. Preserve raw measurements and leave unverified relationships open.
3. Assess what the evidence supports, including whether there is a defensible next check. When a material evidence gap limits the investigation, explain what it prevents and ask whether to proceed with a limited RCA. Wait for agreement before handing off that limited scope. If the engineer declines, report what evidence would unblock the work. An absent NCR affects formal outputs. Missing sensor readings affect sensor-dependent checks.

## 2. Attempt the handoff

1. Look for the installed `claude-for-manufacturing:root-cause-capa` skill. Use it through a registered skill invocation available to the current Cowork task. Pass the resolved scope, exact evidence paths or source references, and the agreed limitations. Request case-specific executable analysis where useful and supported by the evidence.
2. If the skill cannot be selected or invoked, report the observed error or unavailable capability. Keep the test result unresolved if the host does not expose evidence that the skill loaded. A similar-looking investigation is insufficient evidence of invocation.
3. Follow the loaded skill's instructions and resolve plant context using its setup helper. For a downtime case without an NCR, request the investigation the available evidence supports and keep formal 8D and customer outputs blocked. Where an NCR is supplied, preserve its requirement citation and approval state and apply the upstream gates. Leave verification and closure to the engineer. Keep outputs in the task workspace and make no external updates or sends.

Choose investigation methods that fit the evidence and explain why:

- Build a timeline when event order matters. Use the recorded time precision and verified clock alignment to bound what can be inferred.
- Use a fishbone to organise competing hypotheses when several mechanisms fit the symptom. Choose branches suited to the case and show the evidence and gaps for each.
- Use 5 Whys when the evidence supports following a plausible causal chain. At the first unsupported link, describe what would verify it. The number of questions follows the evidence.
- Use 8D for the formal corrective-action workflow when applicable and permitted by the upstream gates.

## 3. Save findings from this run

After the installed skill returns its investigation, read `../../shared/contracts/rca-findings.schema.json` relative to this skill folder. Write a new `rca-findings.json` in the task's output location using that structure. Use a separate output location if a file with that name already exists, and report the path. Copy site, asset and event identity from the evidence used. Copy the actual NCR reference and approval state, or use null when absent.

Capture the investigation's ranked hypotheses, preserving ties. Give each hypothesis a unique ID and a fishbone branch. Keep each causal link's source references, observations, and limitations. Where a link lacks supporting evidence, record the gap. Include the proposed tests and first inspection when the investigation supplies them. A `next_inspection` object must name only hypothesis IDs from this run. Use null if the investigation cannot support a first inspection.

Keep observations and inferences distinct. If signals both changed within the same sampling interval, leave their order unresolved unless another record establishes it. Do not create findings if the installed skill did not return an investigation. If its returned assessment is that the evidence is insufficient, record that state and the reasons. Check the fields against the contract before offering the output. Report any write or schema check that could not be completed.

## 4. Check the generated findings

After saving the findings, run `../../shared/scripts/check_rca_findings.py` relative to this skill folder. Pass the path of the findings file as the first argument. When Python 3 is available, use one of these forms with the script's resolved path and the actual input paths:

```text
python3 "<checker>" "<findings>"
python3 "<checker>" "<findings>" "<sensor_csv>" --temperature-tag "<tag>" --vibration-tag "<tag>"
```

Use the second form only when the evidence includes an incident-scoped CSV with `TAG_ID`, `TS_UTC`, `VALUE`, and `QUALITY`, and both signal tags have been verified for the resolved asset on a comparable time basis. Otherwise run the first form. If timing evidence exists but cannot be used, explain why. Missing sensor inputs do not block the structural checks.

When the evidence includes a distinct historian stop JSON and a consolidated workbook with a `downtime_events` sheet, append `--historian-stop "<historian-stop.json>" --downtime-workbook "<workbook.xlsx>"` to either command. Check the available event records before concluding that only a same-time sensor sample exists. Copy the observed offset for the matching site, asset and event from `stop_clock_offset`. Its sign is historian time minus downtime time. One shared event can establish the observed offset at that event. The sensor CSV's clock relationship and the stop mechanism need their own evidence. If the records do not match or the check is unavailable, carry forward the reason.

When a workbook with a `maintenance_work_orders` sheet is available and the draft cites work-order completion dates for the resolved asset, append `--work-orders-workbook "<workbook.xlsx>" --work-order-date "<work-order-id>" "<YYYY-MM-DD>"`. Repeat `--work-order-date` for each distinct completion-date claim in the findings or planned report. Take the date from the draft as written and convert only its format to YYYY-MM-DD. Copying the workbook date into the check would hide a draft error. If a claim cannot be converted without guessing, review it against the source manually and record that limitation.

Read the checker's JSON output even when the exit code is nonzero. Exit code 1 means review flags were found. Exit code 2 means a check could not complete. Report any returned flags and unavailable or inconclusive checks. Review flags against the source evidence. For a `work_order_completion_date_mismatch`, inspect the cited source record, then correct the date and any derived timing in the findings and report draft. Leave inconclusive claims qualified. Preserve the upstream investigation, revise the structured draft as needed, and rerun the checker using the file and date claims being delivered. State any unresolved flags. If Python or the script is unavailable, report that the checker did not run.

`no_flags` means the checks that ran found no issue. It does not validate the RCA's causal reasoning or replace the engineer's review. Report the sensor timing status alongside the structural result.

## 5. Review against the evidence

Read `../../shared/reference/rca-review.md` relative to this skill folder. Apply every criterion to the current run's findings using the original records, the resolved incident scope, and any checker results. Check whether the chosen method fits the available evidence and the decision the engineer needs to make. Record any unsupported ordering, causal link, or first inspection with the relevant source or gap.

If the review calls for changes, revise the structured findings, review the affected criteria again, and rerun the applicable Python checks on the revised file. Preserve the upstream investigation. Report the rubric result separately from the Python check and show the engineer any unresolved material issue. If the rubric or relevant evidence cannot be accessed, state which review could not be completed.

## 6. Confirm inputs for a maintenance strategy comparison

Enter this step only if the reviewed RCA recommends evaluating a specific maintenance strategy change. A recommended field inspection to verify a cause does not trigger strategy analysis. Identify the current policy and proposed change, what decision the comparison would inform, and whether the change depends on an unconfirmed cause. Keep any result conditional on that premise.

Check the supplied inputs first. Use authorised read-only tools when available to retrieve missing records. For example, use CMMS for installation, failure and replacement history, operating records for exposure, and delay accounting for downtime and production impact. These records may be available through configured Snowflake tools. If access or a verified mapping is missing, explain which source or export would help and ask the engineer for it. Preserve source references, units, coverage, and unresolved conflicts.

- For a life model, ask for a documented fit with beta, eta, and gamma in their applicable units, or comparable component lives with operating ages, failure modes, and censoring and replacement history. Use the bundled fitter only for an eligible two-parameter fit. A supplied three-parameter fit requires a documented basis for all three parameters.
- For a cost comparison, confirm fleet starting ages and exposure, the analysis horizon, policy intervals, direct event costs, downtime, production impact, currency, and any discounting and renewal assumptions used. Check that production losses are counted once.
- For an inspection policy, also confirm the inspection method, interval, cost and downtime, the P–F interval, detection performance, and the lead time, cost and downtime of the intervention. Those inputs need a separate basis from the Weibull fit.

Show the proposed inputs and their sources or explicitly labelled scenario assumptions. Ask the engineer to confirm the cohort, model and comparison inputs before calculations. Keep missing values open and identify which analysis they prevent. Use synthetic fixtures only for an explicitly requested demo. If a confirmed calculation can run, use the supported calculator and report its actual results and limitations. If a policy is unsupported by the calculator, show that status. Return the RCA and recommended next check even when strategy analysis cannot proceed.

When asking for confirmation, state the fleet decision in one sentence and show a compact list of the proposed inputs and assumptions. Keep the incident findings, rankings, sensor figures and inspection details for the report. Explain that the combined HTML report is pending and that confirmation starts the calculations and generates the downloadable report. Use the host's native choice tool if available. Offer **Confirm and generate report** and **Change inputs**. In chat, say “Reply **Confirm** to run the analysis and get the downloadable HTML report, or tell me which inputs to change.” Wait for confirmation before calculating. After the run, generate and link the report even if a calculation is unsupported.

After confirmation, resolve the bundled scripts in `../../shared/scripts/` relative to this skill. For a life-history input, run `fit_weibull.py <lives.json>` with Python 3 and save its JSON output in the task output folder. A confirmed documented fit can be supplied directly in the simulator's format. For confirmed scenario inputs, run `simulate_maintenance.py <life-fit.json> <scenario.json>`. When the engineer also confirms sensitivity values, run `run_strategy_sensitivity.py <life-fit.json> <scenario.json> <sweeps.json>` instead. Save the actual JSON output and report unsupported results with their reasons. Scope all files and calculations to the confirmed decision.

## 7. Generate the downloadable report

When findings exist, resolve `../../shared/scripts/render_rca_report.py` relative to this skill and use Python 3. Create or resolve the task's writable output folder and choose a fresh report path. Save the review outcome and any unresolved issues as task-local plain text. Use the final reviewed findings file and actual result paths:

Under the `Python checker:` heading in the review notes, record the stop check's status, offset and source references when available. Summarise the `work_order_dates` result, including any corrected or unresolved claims and their source references. Keep these details in the report's Run details drawer. Mention timing or a date discrepancy in the brief only when it changes the supported conclusion or next action.

```text
python3 "<renderer>" "<rca-findings.json>" "<output>/rca-report.html" --review "<review-notes.txt>" --title "<investigation title>" --incident-label "<observed incident>" --summary "<brief reviewed finding>"
```

Use a short, factual title naming the asset and observed issue, such as “CV207 belt drift investigation”. Use the resolved asset ID when no tag is available. Write the incident label and summary from the reviewed evidence. Keep the summary to one or two sentences that explain the leading finding and its main uncertainty.

Add `--fit "<life-fit.json>"` and `--strategy "<strategy-result.json>"` when those result files exist. The strategy file can contain the single simulation result or the sensitivity result. Omit unavailable files and include any material reason in the review notes. Use `--synthetic` for synthetic incident evidence. Keep the reviewed RCA available as a downloadable report even when the strategy gate does not apply.

Check that the renderer completed and the HTML exists before linking it in the reply. If rendering fails, state the error briefly, link the findings if available, and preserve the detailed investigation as a separate task artifact when possible.

## 8. Deliver a short decision brief

Keep the companion's final reply to about 100 words. Lead with one first inspection or decision. Give the strongest supporting observation and the uncertainty that could change the decision. Keep later inspection steps and test procedures in the report. If no inspection can be supported, name the main evidence gap instead. For a completed strategy comparison, give one sentence with the lowest-cost tested option and its baseline comparison. Flag synthetic or limited scope and any approval restriction that affects the requested deliverable.

Link the downloadable report. Keep tables, complete hypothesis chains, detailed checker results and the upstream investigation in the report or separate task artifacts. Preserve the upstream skill's outputs and approval gates. Put the handoff status, sources used, and unavailable checks in the detailed record. Surface a material blocker in the brief when it changes what the engineer can do next.

When several records could help, choose the one most likely to change the next decision. Offer one follow-up about that record. For example: “Want me to look for the trip log that could establish what triggered the stop?” If the host exposes a native choice tool, invoke it with options to search available records, supply that record or finish. Otherwise ask one short question in chat. Wait for the engineer's choice. If they choose to search, use authorised read-only sources and report what was found and what remains missing.
