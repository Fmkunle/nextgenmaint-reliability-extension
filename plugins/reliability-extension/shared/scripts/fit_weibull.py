"""Fit a two-parameter Weibull to one cohort with administrative right censoring."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random


def read_cohort(data):
    cohort = data["cohort"]
    cutoff = data["observation_cutoff"]
    if (cohort["complete_observation_from_installation"] is not True
            or cohort["delayed_entry"] is not False
            or cohort["independent_installations"] is not True):
        raise ValueError("Fit requires independent lives observed from installation")
    for field in ("part_number", "duty_group"):
        if not isinstance(cohort[field], str) or not cohort[field].strip():
            raise ValueError(f"Missing cohort {field}")

    ages, failures, identifiers, modes = [], [], set(), set()
    for row in data["installations"]:
        identifier = row["installation_id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
            raise ValueError("Installation IDs must be nonempty and unique")
        identifiers.add(identifier)
        age = row["age_operating_hours"]
        if type(age) not in (float, int) or not math.isfinite(age) or age <= 0:
            raise ValueError(f"Invalid operating age for {identifier}")
        event, state, mode = row["event_observed"], row["end_state"], row["failure_mode"]
        if type(event) is not int or (event, state) not in ((1, "failed"), (0, "active_at_cutoff")):
            raise ValueError(f"Inconsistent outcome for {identifier}")
        ages.append(age)
        if event:
            if not isinstance(mode, str) or not mode.strip():
                raise ValueError(f"Missing failure mode for {identifier}")
            failures.append(age)
            modes.add(mode)
        elif mode is not None:
            raise ValueError(f"Unexpected failure mode for censored installation {identifier}")

    if len(modes) != 1:
        raise ValueError("Fit requires observed failures in one identified failure mode")
    if len(ages) > len(failures) and (
        cutoff["non_informative_censoring_assumed"] is not True or not cutoff["basis"]
    ):
        raise ValueError("Fit requires a documented non-informative censoring assumption")
    return ages, failures, modes.pop()


def failure_probability(beta, eta, gamma, start_age, end_age):
    """Return risk by end_age given survival to start_age, with all ages in hours."""
    if (not all(map(math.isfinite, (beta, eta, gamma, start_age, end_age)))
            or beta <= 0 or eta <= 0 or not 0 <= start_age <= end_age):
        raise ValueError("Expected valid Weibull parameters and an ordered operating-age window")
    if start_age == end_age or end_age <= gamma:
        return 0.0
    start = max(0.0, start_age - gamma)
    end = end_age - gamma
    # Use the hazard increment directly, avoiding division of small survivals.
    # Computing its relative change separately retains precision for short windows.
    fraction = (-math.expm1(-beta * math.log1p((end_age - start_age) / start))
                if start else 1.0)
    if not fraction:
        return 0.0
    try:
        increment = math.exp(beta * (math.log(end) - math.log(eta)) + math.log(fraction))
    except OverflowError:
        return 1.0
    return -math.expm1(-increment)


def empirical_failure_curve(ages, failures):
    """Kaplan–Meier failure estimates at observed ages, including censor-only ages."""
    removed_at = Counter(ages)
    failed_at = Counter(failures)
    at_risk = len(ages)
    survival = 1.0
    curve = []
    for age, removed in sorted(removed_at.items()):
        failed = failed_at[age]
        # At tied ages, censored units remain at risk for the failures at that age.
        survival *= 1 - failed / at_risk
        curve.append({"age_operating_hours": age, "at_risk": at_risk, "failures": failed,
                      "right_censored": removed - failed, "failure_probability": 1 - survival})
        at_risk -= removed
    return curve


def estimate(ages, failures, *, profile_interval=False):
    count = len(failures)
    if not count:
        raise ValueError("No observed failures in this sample")
    # Centre log ages at the largest age so the exponential weights cannot overflow.
    anchor = math.log(max(ages))
    logs = [math.log(age) - anchor for age in ages]
    failure_mean = math.fsum(math.log(age) - anchor for age in failures) / count
    if failure_mean >= 0:
        raise ValueError("No finite Weibull shape estimate for these failure ages")

    def profile(shape):
        weights = [math.exp(shape * value) for value in logs]
        total = math.fsum(weights)
        weighted_mean = math.fsum(w * x for w, x in zip(weights, logs)) / total
        log_scale = math.log(total / count) / shape
        score = 1 / shape + failure_mean - weighted_mean
        likelihood = count * (math.log(shape) - shape * log_scale
                              + (shape - 1) * failure_mean - 1)
        return score, log_scale, likelihood

    low, high = 0.0, 1.0
    # The profiled score decreases with shape, so bracket its single positive root.
    while profile(high)[0] > 0:
        high *= 2
    for _ in range(100):
        middle = (low + high) / 2
        if profile(middle)[0] > 0:
            low = middle
        else:
            high = middle
    beta = (low + high) / 2
    _, log_scale, peak = profile(beta)
    eta = math.exp(anchor + log_scale)
    if not profile_interval:
        return beta, eta, None

    # The asymptotic 95% likelihood-ratio cutoff for one profiled parameter is 3.84146.
    threshold = peak - 3.841458820694124 / 2
    upper = beta * 2
    while profile(upper)[2] > threshold:
        upper *= 2

    def limit(outside):
        inside = beta
        for _ in range(100):
            middle = (inside + outside) / 2
            if profile(middle)[2] >= threshold:
                inside = middle
            else:
                outside = middle
        return (inside + outside) / 2

    return beta, eta, [limit(0), limit(upper)]


def uncertainty_samples(installations):
    """Resample independent lives as age/outcome pairs for pointwise risk intervals."""
    attempts = 400
    rng = random.Random(104)
    records = [(row["age_operating_hours"], row["event_observed"]) for row in installations]
    samples = []
    for _ in range(attempts):
        draw = rng.choices(records, k=len(records))
        try:
            beta, eta, _ = estimate([age for age, _ in draw],
                                    [age for age, failed in draw if failed])
        except (ValueError, OverflowError):
            # Some draws have no failures or no finite maximum-likelihood estimate.
            continue
        samples.append({"beta": beta, "eta_operating_hours": eta})
    # Suppress percentile intervals when excluding unstable draws could dominate the tails.
    usable = len(samples) >= 0.975 * attempts
    return {"method": "paired_nonparametric_bootstrap", "attempted": attempts,
            "successful": len(samples), "confidence_level": 0.95,
            "status": "available" if usable else "unavailable",
            "parameter_samples": samples if usable else []}


def fit(data):
    ages, failures, mode = read_cohort(data)
    beta, eta, interval = estimate(ages, failures, profile_interval=True)
    return {
        "status": "completed",
        "model": "weibull_2p",
        "synthetic": data.get("synthetic", False),
        "part_number": data["cohort"]["part_number"],
        "duty_group": data["cohort"]["duty_group"],
        "failure_mode": mode,
        "failures": len(failures),
        "right_censored": len(ages) - len(failures),
        "beta": beta,
        "eta_operating_hours": eta,
        "gamma_operating_hours": 0,
        "beta_profile_likelihood_95_interval": interval,
        "empirical_failure_curve": empirical_failure_curve(ages, failures),
        "risk_uncertainty": uncertainty_samples(data["installations"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lives", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.lives.read_text(encoding="utf-8-sig"))
        result = fit(data)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        print(json.dumps({"status": "unsupported", "reason": str(error)}))
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
