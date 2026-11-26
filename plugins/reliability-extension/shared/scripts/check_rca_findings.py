"""Check findings references, sensor timing, stop records, and work-order dates."""

import argparse
import csv
from datetime import date, datetime
import json
import math
from pathlib import Path
import re
from zipfile import BadZipFile


SIGNAL = r"(?:temperature|heat|vibration)"
ORDER_CLAIM = re.compile(
    rf"\b(?P<first>{SIGNAL})(?:\s+(?:rose|increased|started|began|changed))?"
    rf"\s+(?:before|ahead of|prior to|led|then)\s+(?P<second>{SIGNAL})\b",
    re.IGNORECASE,
)


def first_change_window(samples):
    """Bound the first observed change from the initial value."""
    samples.sort()
    if len(samples) < 2 or len({time for time, _ in samples}) != len(samples):
        return None
    initial = samples[0][1]
    for index, (time, value) in enumerate(samples[1:], start=1):
        if value != initial:
            return samples[index - 1][0], time
    return None


def read_samples(path, tags):
    samples = {tag: [] for tag in tags}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            tag = row["TAG_ID"]
            if tag not in samples:
                continue
            # Dropping a bad reading could hide an earlier change.
            value = float(row["VALUE"])
            time = datetime.fromisoformat(row["TS_UTC"].replace("Z", "+00:00"))
            if row["QUALITY"] != "GOOD" or not math.isfinite(value) or time.utcoffset() is None:
                raise ValueError(f"Unusable sensor sample for {tag}")
            samples[tag].append((time, value))
    return samples


def check_references(findings):
    issues = []
    ids = [hypothesis["id"] for hypothesis in findings["hypotheses"]]
    if len(set(ids)) != len(ids):
        issues.append({"code": "duplicate_hypothesis_id"})
    inspection = findings["next_inspection"]
    if inspection is not None:
        for reference in inspection["distinguishes_hypothesis_ids"]:
            if reference not in ids:
                issues.append({"code": "unknown_inspection_hypothesis", "reference": reference})
    return issues


def check_signal_order(findings, temperature_window, vibration_window):
    issues = []
    windows = {"temperature": temperature_window, "heat": temperature_window,
               "vibration": vibration_window}
    for hypothesis in findings["hypotheses"]:
        for index, link in enumerate(hypothesis["causal_links"], start=1):
            claim = link["claim"]
            for match in ORDER_CLAIM.finditer(claim):
                first, second = (windows[word.lower()] for word in match.groups())
                # A first-change window is open at its start and closed at its end.
                if first is None or second is None or first[1] > second[0]:
                    issues.append({
                        "code": "signal_order_needs_review",
                        "hypothesis_id": hypothesis["id"],
                        "causal_link": index,
                        "claim": claim,
                    })
    return issues


def aware_timestamp(value):
    timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("Stop timestamp must include a time zone")
    return timestamp


def workbook_rows(workbook_path, sheet, columns):
    """Yield source rows and close the workbook when the caller finishes reading."""
    # The structural and sensor checks also work without this dependency.
    from openpyxl import load_workbook

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        rows = workbook[sheet].iter_rows(values_only=True)
        headers = next(rows, ())
        if any(headers.count(column) != 1 for column in columns):
            raise ValueError(f"{sheet} is missing required columns or has duplicate headers")
        for values in rows:
            yield dict(zip(headers, values))
    finally:
        workbook.close()


def check_stop_offset(findings, historian_path, workbook_path):
    identity = ("site", "asset_id", "event_id")
    event_key = tuple(findings[field] for field in identity)
    historian = json.loads(historian_path.read_text(encoding="utf-8-sig"))
    if tuple(historian[field] for field in identity) != event_key:
        return {"status": "inconclusive", "reason": "Historian stop does not match the findings identity"}

    columns = (*identity, "start", "source_system", "source_ref")
    matches = [row for row in workbook_rows(workbook_path, "downtime_events", columns)
               if tuple(row[field] for field in identity) == event_key]

    if len(matches) != 1:
        return {"status": "inconclusive", "reason": "Expected exactly one matching downtime record",
                "matching_downtime_records": len(matches)}
    downtime, = matches
    if (not downtime["source_system"] or not historian["source_system"]
            or downtime["source_system"] == historian["source_system"]
            or not downtime["source_ref"] or not historian["source_ref"]):
        return {"status": "inconclusive", "reason": "Distinct source systems and record references are required"}

    offset = (aware_timestamp(historian["timestamp_utc"]) - aware_timestamp(downtime["start"])).total_seconds()
    return {"status": "checked", "historian_minus_downtime_seconds": offset,
            "historian_source_ref": historian["source_ref"], "downtime_source_ref": downtime["source_ref"],
            "scope": "One shared event. Sensor CSV clock relationship and stop cause remain unverified by this check."}


def check_work_order_dates(findings, workbook_path, claims):
    columns = ("site", "asset_id", "maintenance_wo", "completed_at", "source_ref")
    wanted = {work_order for work_order, _ in claims}
    matches = {work_order: [] for work_order in wanted}
    for row in workbook_rows(workbook_path, "maintenance_work_orders", columns):
        work_order = row["maintenance_wo"]
        if (work_order in wanted and row["site"] == findings["site"]
                and row["asset_id"] == findings["asset_id"]):
            matches[work_order].append(row)

    results, issues = [], []
    for work_order, claimed in claims:
        result = {"work_order": work_order, "claimed_date": claimed}
        candidates = matches[work_order]
        if len(candidates) != 1:
            result.update(status="inconclusive", reason="Expected one scoped work-order record",
                          matches=len(candidates))
        else:
            row = candidates[0]
            result["source_ref"] = row["source_ref"]
            try:
                claimed_date = date.fromisoformat(claimed)
                if claimed_date.isoformat() != claimed:
                    raise ValueError("Claim must use YYYY-MM-DD")
                source = row["completed_at"]
                # Excel may store a date cell as a datetime. Compare its recorded calendar day.
                source_date = source.date() if isinstance(source, datetime) else source
                if not isinstance(source_date, date):
                    source_date = date.fromisoformat(source_date)
                if not row["source_ref"]:
                    raise ValueError("Source record reference is missing")
            except (ValueError, TypeError) as error:
                result.update(status="inconclusive", reason=str(error))
            else:
                result.update(status="matches" if claimed_date == source_date else "mismatch",
                              source_date=source_date.isoformat())
                if result["status"] == "mismatch":
                    issues.append({"code": "work_order_completion_date_mismatch", **result})
        results.append(result)
    status = "inconclusive" if any(row["status"] == "inconclusive" for row in results) else "checked"
    return {"status": status, "claims": results}, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("findings", type=Path)
    parser.add_argument("sensor_csv", nargs="?", type=Path, help="Sensor export scoped to the incident window")
    parser.add_argument("--temperature-tag")
    parser.add_argument("--vibration-tag")
    parser.add_argument("--historian-stop", type=Path)
    parser.add_argument("--downtime-workbook", type=Path)
    parser.add_argument("--work-orders-workbook", type=Path)
    parser.add_argument("--work-order-date", nargs=2, action="append", default=[],
                        metavar=("WORK_ORDER", "YYYY-MM-DD"),
                        help="Claimed completion date in the report. Repeat for each claim.")
    args = parser.parse_args()
    sensor_inputs = (args.sensor_csv, args.temperature_tag, args.vibration_tag)
    if any(sensor_inputs) and not all(sensor_inputs):
        parser.error("Supply the sensor CSV and both tags together")
    if args.sensor_csv is not None and args.temperature_tag == args.vibration_tag:
        parser.error("Temperature and vibration must use distinct tags")
    if bool(args.historian_stop) != bool(args.downtime_workbook):
        parser.error("Supply the historian stop record and downtime workbook together")
    if bool(args.work_orders_workbook) != bool(args.work_order_date):
        parser.error("Supply the work-orders workbook and at least one date claim together")

    try:
        findings = json.loads(args.findings.read_text(encoding="utf-8-sig"))
        issues = check_references(findings)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "check_unavailable", "reason": str(error)}))
        return 2

    timing = {"status": "not_applicable", "reason": "No sensor inputs supplied"}
    if args.sensor_csv is not None:
        try:
            samples = read_samples(args.sensor_csv, (args.temperature_tag, args.vibration_tag))
            temperature = first_change_window(samples[args.temperature_tag])
            vibration = first_change_window(samples[args.vibration_tag])
            issues.extend(check_signal_order(findings, temperature, vibration))
            timing = {"status": "checked"}
            if temperature is None or vibration is None:
                timing = {"status": "inconclusive", "reason": "Could not bound both first changes"}
        except (OSError, ValueError, TypeError, KeyError) as error:
            # Keep structural findings available when the optional evidence cannot be read.
            timing = {"status": "check_unavailable", "reason": str(error)}

    stop = {"status": "not_applicable", "reason": "No stop record pair supplied"}
    if args.historian_stop is not None:
        try:
            stop = check_stop_offset(findings, args.historian_stop, args.downtime_workbook)
        except (OSError, ImportError, ValueError, TypeError, KeyError, AttributeError, BadZipFile) as error:
            stop = {"status": "check_unavailable", "reason": str(error)}

    dates = {"status": "not_applicable", "reason": "No work-order date claims supplied"}
    if args.work_orders_workbook is not None:
        try:
            dates, date_issues = check_work_order_dates(findings, args.work_orders_workbook, args.work_order_date)
            issues.extend(date_issues)
        except (OSError, ImportError, ValueError, TypeError, KeyError, AttributeError, BadZipFile) as error:
            dates = {"status": "check_unavailable", "reason": str(error)}

    unavailable = any(check["status"] == "check_unavailable" for check in (timing, stop, dates))
    status = "check_unavailable" if unavailable else "review_required" if issues else "no_flags"
    print(json.dumps({"status": status, "issues": issues, "sensor_timing": timing,
                      "stop_clock_offset": stop, "work_order_dates": dates}, indent=2))
    if unavailable:
        return 2
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
