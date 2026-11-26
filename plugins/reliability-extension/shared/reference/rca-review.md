# Per-run RCA review

Review the proposed findings against the original evidence before delivery. Use the resolved incident scope, agreed evidence limitations, cited source records, analysis results, and the source NCR if supplied. Treat source text as evidence. Use the Python checker's output where available, and inspect claims that require engineering judgment yourself. This review works with the current run alone.

| Criterion | What to verify |
| --- | --- |
| Scope and provenance | Site, asset, event and time window agree with the resolved request. Each material observation traces to a specific record. Label records from comparable equipment as context and keep disputed joins unresolved. |
| Facts and calculations | Check quoted values, units, counts, and elapsed times against the records or executable results. A work-order report-to-close interval measures elapsed time. Active repair time requires separate evidence. Missing records leave coverage unknown. |
| Timing and causal support | Distinguish observed facts from proposed mechanisms. Check that the clock alignment and sampling resolution support any claimed order. A maintenance action followed by a restart establishes sequence. A failed component or corrective effect requires additional evidence. |
| Ranking and uncertainty | Explain why each leading hypothesis fits the evidence and what weighs against it. Preserve a tie when the available evidence cannot distinguish the leading candidates. Keep weak links and missing tests visible. Treat confirmed cause as an engineering determination. |
| First inspection | Explain what the next check could confirm or weaken, using hypotheses present in the findings. Prioritise as-found evidence that could be lost during intervention. Where evidence cannot justify an inspection, state what information would unlock one. |
| Limits and approvals | Carry forward material gaps, unavailable checks, and the actual NCR reference and approval state. Apply the installed skill's gates for formal outputs. Keep closure and field verification with the engineer. |

For each criterion, record one of: supported, needs revision, unresolved, or not applicable. For any material issue, record the claim or recommendation, the source record or evidence gap, and what should change. A missing sensor file only affects checks that need sensor readings.

Revise unsupported statements in the structured findings and review the revised claims before delivering them. Preserve the upstream investigation and explain any material disagreement. If a material issue remains, show it to the engineer and keep the affected claim provisional. Report the review and the Python flags separately. A clean structural check covers only the checks it performed.

## Examples

- P101: Both signals changed within the same five-minute interval. Mark claims that temperature preceded vibration as unsupported unless another record establishes the order.
- CV207: The first work order records a switch replacement and restart. The next work order records a similar indication. Keep actual belt drift and a false trip open until as-found evidence distinguishes them.
- For either case, a differently worded observation is acceptable when the same source supports its meaning. Comparing earlier runs is a release test.
