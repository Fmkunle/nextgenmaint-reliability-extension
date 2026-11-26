"""Run supplied maintenance strategy sensitivity points for an offline report."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from simulate_maintenance import number, simulate


AXES = {
    "replacement_interval": (
        ("strategies", "scheduled_replacement", "replace_at_operating_hours"), "operating hours"
    ),
    "inspection_interval": (
        ("strategies", "condition_based_inspection", "interval_operating_hours"), "operating hours"
    ),
    "detection_probability": (
        ("strategies", "condition_based_inspection",
         "detection_probability_per_inspection_during_pf_interval"), "probability"
    ),
    "production_loss_rate": (
        ("consequences", "lost_production_value_per_downtime_hour"), "currency per downtime hour"
    ),
}


def input_container(scenario, path):
    current = scenario
    for key in path[:-1]:
        current = current[key]
    return current


def point(value, result):
    means = {
        name: policy["fleet_metrics"]["discounted_total_cost"]["mean"]
        for name, policy in result["strategies"].items() if policy["status"] == "completed"
    }
    lowest = min(means.values(), default=None)
    # A lowest simulated cost is an economic comparison among the completed policies.
    return {
        "value": value,
        "lowest_mean_cost_strategies": [name for name, cost in means.items() if cost == lowest],
        "strategies": result["strategies"],
    }


def run_sensitivity(life_fit, scenario, sweeps):
    if not isinstance(sweeps, dict) or not sweeps:
        raise ValueError("Supply at least one named assumption and its test values")
    if scenario["simulation"]["common_random_numbers_across_strategies"] is not True:
        raise ValueError("Sensitivity comparisons require matched random draws")

    validated = []
    for axis, values in sweeps.items():
        if axis not in AXES:
            raise ValueError(f"Unsupported sensitivity assumption: {axis}")
        if not isinstance(values, list) or not values:
            raise ValueError(f"{axis} requires a nonempty list of test values")
        path, unit = AXES[axis]
        baseline_value = input_container(scenario, path)[path[-1]]
        for value in values:
            number(value, axis, positive=axis.endswith("_interval"))
            if axis == "detection_probability" and value > 1:
                raise ValueError("Detection probability cannot exceed one")
        if len(set(values)) != len(values):
            raise ValueError(f"{axis} contains duplicate test values")
        validated.append((axis, path, unit, baseline_value, sorted(values)))

    baseline = simulate(life_fit, scenario)
    if baseline["status"] != "completed":
        raise ValueError("No baseline strategy completed")
    axes = {}
    for axis, path, unit, baseline_value, values in validated:
        points = []
        for value in values:
            if value == baseline_value:
                result = baseline
            else:
                # Copy the baseline for each point so changes never carry across axes.
                variant = deepcopy(scenario)
                input_container(variant, path)[path[-1]] = value
                result = simulate(life_fit, variant)
            points.append(point(value, result))
        axes[axis] = {"unit": unit, "baseline_value": baseline_value, "points": points}

    return {
        "status": "completed",
        "method": "one_assumption_at_a_time",
        "baseline": baseline,
        "axes": axes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("life_fit", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("sweeps", type=Path, help="JSON object mapping assumption names to test values")
    args = parser.parse_args()
    try:
        inputs = [json.loads(path.read_text(encoding="utf-8-sig"))
                  for path in (args.life_fit, args.scenario, args.sweeps)]
        result = run_sensitivity(*inputs)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        print(json.dumps({"status": "unsupported", "reason": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
