"""Flag wording changes in the leading hypotheses and first inspection of matched RCA runs."""

import argparse
import json
from pathlib import Path


MATCH_FIELDS = ("site", "asset_id", "event_id", "ncr")


def normalized(text):
    return " ".join(text.casefold().split())


def leading_titles(findings):
    hypotheses = findings["hypotheses"]
    if not hypotheses:
        return {}
    best_rank = min(hypothesis["rank"] for hypothesis in hypotheses)
    # IDs are local to each run. Compare all titles at the best rank, including ties.
    return {normalized(hypothesis["title"]): hypothesis["title"]
            for hypothesis in hypotheses if hypothesis["rank"] == best_rank}


def inspection_action(findings):
    inspection = findings["next_inspection"]
    return None if inspection is None else inspection["action"]


def compare_runs(before, after):
    mismatches = [field for field in MATCH_FIELDS if before[field] != after[field]]
    if mismatches:
        return {"status": "not_comparable", "mismatched_fields": mismatches}

    flags = []
    if before["assessment"] != after["assessment"]:
        flags.append({"code": "assessment_changed", "before": before["assessment"],
                      "after": after["assessment"]})

    old_leaders, new_leaders = leading_titles(before), leading_titles(after)
    if old_leaders.keys() != new_leaders.keys():
        flags.append({
            "code": "leading_hypotheses_need_review",
            "removed_titles": [old_leaders[key] for key in sorted(old_leaders.keys() - new_leaders.keys())],
            "added_titles": [new_leaders[key] for key in sorted(new_leaders.keys() - old_leaders.keys())],
        })

    old_action, new_action = inspection_action(before), inspection_action(after)
    if normalized(old_action or "") != normalized(new_action or ""):
        flags.append({"code": "inspection_needs_review", "before": old_action, "after": new_action})

    return {
        "status": "review_required" if flags else "no_flags",
        "flags": flags,
        "scope": "Text comparison only. Review paraphrases and any change in engineering meaning.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--matched-inputs", action="store_true", required=True,
                        help="Confirm both runs used the same evidence, request and scope")
    args = parser.parse_args()
    try:
        before = json.loads(args.before.read_text(encoding="utf-8-sig"))
        after = json.loads(args.after.read_text(encoding="utf-8-sig"))
        result = compare_runs(before, after)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        result = {"status": "comparison_unavailable", "reason": str(error)}

    print(json.dumps(result, indent=2))
    return {"no_flags": 0, "review_required": 1}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
