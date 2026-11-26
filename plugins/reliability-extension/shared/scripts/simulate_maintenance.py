"""Compare failure, scheduled replacement, and inspection policies using a Weibull fit."""

import argparse
import json
import math
from pathlib import Path
import random
from statistics import mean, quantiles


def number(value, label, minimum=0, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < minimum or (positive and value == minimum)):
        raise ValueError(f"Invalid {label}")
    return value


def count(value, label, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid {label}")
    return value


def simulate(life_fit, scenario):
    fleet = scenario["fleet"]
    settings = scenario["simulation"]
    costs = scenario["consequences"]
    assumptions = scenario["assumptions"]
    model = life_fit["model"]
    if life_fit["status"] != "completed" or model not in ("weibull_2p", "weibull_3p"):
        raise ValueError("A completed two- or three-parameter Weibull fit is required")
    for field in ("part_number", "duty_group"):
        if life_fit[field] != fleet[field]:
            raise ValueError(f"Life fit and scenario differ on {field}")
    if life_fit["synthetic"] is not scenario["synthetic"]:
        raise ValueError("Life fit and scenario must agree on synthetic status")
    gamma = number(life_fit["gamma_operating_hours"], "Weibull location", minimum=-math.inf)
    if model == "weibull_2p" and gamma != 0:
        raise ValueError("A two-parameter Weibull must have zero location")
    for field in ("replacement_restores_as_new_after_each_replacement",
                  "successive_lives_independent_and_identically_distributed",
                  "same_fitted_life_distribution_for_all_strategies",
                  "cost_and_duty_stationary"):
        if assumptions[field] is not True:
            raise ValueError(f"This model requires {field}")
    if not scenario["cost_basis_reference"].strip():
        raise ValueError("Cost basis reference is required")

    beta = number(life_fit["beta"], "Weibull shape", positive=True)
    eta = number(life_fit["eta_operating_hours"], "Weibull scale", positive=True)
    annual_hours = number(fleet["scheduled_operating_hours_per_year"], "annual hours", positive=True)
    years = number(settings["horizon_years"], "horizon years", positive=True)
    horizon = number(years * annual_hours, "horizon hours", positive=True)
    replications = count(settings["replications"], "replications", minimum=2)
    rate = number(settings["real_discount_rate_per_year"], "discount rate")
    production_rate = number(costs["lost_production_value_per_downtime_hour"], "production loss rate")
    matched = settings["common_random_numbers_across_strategies"]
    if type(matched) is not bool:
        raise ValueError("Common random numbers setting must be boolean")
    ages = []
    for group in fleet["starting_age_groups"]:
        age = number(group["age_operating_hours"], "starting age")
        ages.extend([age] * count(group["bearing_count"], "bearing count"))
    if not ages:
        raise ValueError("At least one fleet bearing is required")

    event_costs = {}
    for kind in ("failure_replacement", "scheduled_replacement"):
        item = costs[kind]
        event_costs[kind] = (number(item["direct_cost_per_event"], f"{kind} direct cost"),
                             number(item["downtime_operating_hours"], f"{kind} downtime"))
    results = {}
    policies = scenario["strategies"]
    shared_seed = count(settings["random_seed"], "random seed", minimum=0)
    for name, policy in policies.items():
        if name not in ("run_to_failure", "current_practice", "scheduled_replacement",
                        "condition_based_inspection"):
            results[name] = {"status": "unsupported", "reason": "Policy event logic is not implemented"}
            continue
        interval = math.inf
        inspection = None
        policy_costs = event_costs.copy()
        if name == "condition_based_inspection":
            try:
                inspection = read_inspection(policy, assumptions)
                for kind in ("inspection", "inspection_triggered_replacement"):
                    item = costs[kind]
                    policy_costs[kind] = (number(item["direct_cost_per_event"], f"{kind} direct cost"),
                                          number(item["downtime_operating_hours"], f"{kind} downtime"))
            except (KeyError, ValueError, TypeError) as error:
                results[name] = {"status": "unsupported", "reason": str(error)}
                continue
        elif name != "run_to_failure":
            interval = number(policy["replace_at_operating_hours"], f"{name} replacement age",
                              positive=True)
        seed_generator = random.Random(shared_seed if matched else f"{shared_seed}:{name}")
        totals = []
        for _ in range(replications):
            metrics = dict(failures=0, scheduled_replacements=0, inspections=0,
                           inspection_triggered_replacements=0, downtime_operating_hours=0.0,
                           discounted_direct_cost=0.0, discounted_production_loss=0.0)
            for age in ages:
                # Per-bearing streams keep replacement draws matched even when event counts differ.
                seed = seed_generator.getrandbits(64)
                rng = random.Random(seed)
                detection_rng = random.Random(f"inspection:{seed}") if inspection else None
                run_bearing(age, interval, beta, eta, annual_hours, horizon, rate,
                            production_rate, policy_costs, rng, metrics, gamma=gamma,
                            inspection=inspection, detection_rng=detection_rng)
            metrics["discounted_total_cost"] = (metrics["discounted_direct_cost"]
                                                + metrics["discounted_production_loss"])
            totals.append(metrics)
        results[name] = {"status": "completed", "fleet_metrics": {
            key: summarize([replication[key] for replication in totals]) for key in totals[0]
        }}
        if math.isfinite(interval):
            # Report the simulated age limit. Run-to-failure and inspection use no age limit.
            results[name]["replace_at_operating_hours"] = interval

    return {"status": "completed" if any(r["status"] == "completed" for r in results.values())
            else "unsupported", "scenario_id": scenario["scenario_id"],
            "synthetic": scenario["synthetic"], "currency": costs["currency"],
            "horizon_years": years, "replications": replications, "fleet_size": len(ages),
            "life_model": {"model": model, "beta": beta, "eta_operating_hours": eta,
                           "gamma_operating_hours": gamma}, "strategies": results}


def read_inspection(policy, assumptions):
    if (assumptions["inspection_detection_trials_independent_given_detectable_deterioration"] is not True
            or type(assumptions["false_positive_probability"]) not in (int, float)
            or assumptions["false_positive_probability"] != 0):
        raise ValueError("Inspection model requires independent detection trials and zero false positives")
    interval = number(policy["interval_operating_hours"], "inspection interval", positive=True)
    pf = number(policy["pf_interval_operating_hours"], "P–F interval", positive=True)
    detection = number(policy["detection_probability_per_inspection_during_pf_interval"],
                       "inspection detection probability")
    if detection > 1:
        raise ValueError("Inspection detection probability cannot exceed one")
    lead = number(policy["intervention_lead_operating_hours"], "intervention lead time")
    return interval, pf, detection, lead


def run_bearing(age, interval, beta, eta, annual_hours, horizon, rate,
                production_rate, event_costs, rng, metrics, *, gamma,
                inspection=None, detection_rng=None):
    def record(kind, counter, event_at):
        direct, downtime = event_costs[kind]
        observed_downtime = min(downtime, horizon - event_at)
        discount = math.exp(-math.log1p(rate) * (event_at / annual_hours))
        metrics[counter] += 1
        metrics["downtime_operating_hours"] += observed_downtime
        metrics["discounted_direct_cost"] += direct * discount
        metrics["discounted_production_loss"] += production_rate * observed_downtime * discount
        return event_at + observed_downtime

    elapsed = 0.0
    while elapsed < horizon:
        # Conditional survival adds an exponential increment to cumulative hazard at current age.
        # Below gamma the shifted Weibull has zero cumulative hazard.
        hazard = (max(0.0, age - gamma) / eta) ** beta
        failure_age = gamma + eta * (hazard + rng.expovariate(1)) ** (1 / beta)
        to_failure = max(0.0, failure_age - age)
        to_replacement = max(0.0, interval - age)
        failure = to_failure <= to_replacement
        kind = "failure_replacement" if failure else "scheduled_replacement"
        counter = "failures" if failure else "scheduled_replacements"
        operating_time = min(to_failure, to_replacement)
        if inspection:
            spacing, pf, probability, lead = inspection
            operating_at_inspection = spacing
            while operating_at_inspection < operating_time:
                check_at = elapsed + operating_at_inspection
                if check_at >= horizon:
                    break
                after_check = record("inspection", "inspections", check_at)
                elapsed += after_check - check_at  # Downtime advances the clock but does not age the bearing.
                remaining = to_failure - operating_at_inspection
                if remaining <= pf and detection_rng.random() < probability:
                    # Charge a replacement only when it can finish within the remaining warning time.
                    if lead + event_costs["inspection_triggered_replacement"][1] < remaining:
                        operating_time = operating_at_inspection + lead
                        kind = "inspection_triggered_replacement"
                        counter = "inspection_triggered_replacements"
                        break
                next_inspection = operating_at_inspection + spacing
                if next_inspection <= operating_at_inspection:
                    raise ValueError("Inspection interval cannot advance at the input's numerical precision")
                operating_at_inspection = next_inspection

        event_at = elapsed + operating_time
        if event_at >= horizon:
            break
        next_elapsed = record(kind, counter, event_at)
        if next_elapsed <= elapsed and age == 0:
            raise ValueError("Event timing cannot advance at the input's numerical precision")
        elapsed, age = next_elapsed, 0


def summarize(values):
    percentiles = quantiles(values, n=100, method="inclusive")
    return {"mean": mean(values), "p05": percentiles[4], "p95": percentiles[94]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("life_fit", type=Path)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args()
    try:
        result = simulate(json.loads(args.life_fit.read_text(encoding="utf-8-sig")),
                          json.loads(args.scenario.read_text(encoding="utf-8-sig")))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        print(json.dumps({"status": "unsupported", "reason": str(error)}))
        return 2
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
