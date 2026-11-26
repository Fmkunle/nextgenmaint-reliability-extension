"""Render a self-contained RCA report from findings and optional computed results."""

import argparse
from html import escape
import json
import math
from pathlib import Path
import re
from statistics import quantiles
from string import Template

from fit_weibull import failure_probability


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "rca-report.html"
POLICY_NAMES = {
    "run_to_failure": "Run to failure",
    "current_practice": "Current practice",
    "scheduled_replacement": "Scheduled replacement",
    "condition_based_inspection": "Condition-based inspection",
}
REVIEW_CRITERIA = (
    "Scope and provenance", "Facts and calculations", "Timing and causal support",
    "Ranking and uncertainty", "First inspection", "Limits and approvals",
)
RUN_DETAIL_LABELS = (
    "Python checker", "Sensor timing", "Schema validation", "Handoff",
    "Strategy comparison", "Unresolved material issues",
)
REVIEW_HEADING = re.compile(
    r"(?<![\w])(" + "|".join(map(re.escape, REVIEW_CRITERIA + RUN_DETAIL_LABELS))
    + r")(?:\s*\([^:\n]*\))?\s*:", re.IGNORECASE,
)
REVIEW_STATUS = re.compile(
    r"^(supported|needs revision|unresolved|not applicable)(?=\s*[.:;]|$)[\s.:;]*",
    re.IGNORECASE,
)


def text(value):
    return escape(str(value))


def items(values):
    return "<ul>" + "".join(f"<li>{text(value)}</li>" for value in values) + "</ul>"


def evidence_group(label, css_class, rows):
    entries = "".join(f"<li>{text(row['observation'])}<span class='src'>"
                      f"{text(row['source_ref'])}</span></li>" for row in rows)
    content = f"<ul>{entries}</ul>" if entries else '<p class="none">None cited.</p>'
    return f'<div class="{css_class}"><h4>{label}</h4>{content}</div>'


def causal_step(link):
    support = link["evidence_for"]
    opposition = link["evidence_against"]
    # A dashed branch signals missing support, even when counterevidence exists.
    weak = "" if support else ' class="weak"'
    weak_label = "" if support else '<span class="weak-tag">Weak link</span>'
    markers = "".join(
        f'<span class="mark {tone if rows else "none"}"><i></i>{len(rows)} {tone}</span>'
        for tone, rows in (("for", support), ("against", opposition))
    )
    limitations = link["limitations"]
    gaps = f'<div class="l"><h4>Limitations</h4>{items(limitations)}</div>' if limitations else ""
    evidence = evidence_group("For", "f", support) + evidence_group("Against", "a", opposition)
    return (f'<li{weak}><p class="step-text">{text(link["claim"])}{weak_label}</p>'
            f'<div class="marks">{markers}<details class="ev"><summary>Evidence</summary>'
            f'<div class="ev-body">{evidence}{gaps}</div></details></div></li>')


def cause_paths(hypotheses):
    if not hypotheses:
        return '<div class="paths"><p>No ranked hypotheses available.</p></div>'
    primary, additional = [], []
    for index, hypothesis in enumerate(hypotheses):
        rank = hypothesis["rank"]
        tied = sum(item["rank"] == rank for item in hypotheses) > 1
        rank_label = f"Rank {rank}" + (" · tied" if tied else "")
        label = text(f"{hypothesis['id']} · {hypothesis['fishbone_branch']}")
        title = text(hypothesis["title"])
        # Anchors are document-local and never depend on model-generated IDs.
        anchor = f"cause-{index + 1}"
        node = f'<span class="node" data-anchor="{anchor}" aria-hidden="true"></span>'
        chain = '<ol class="chain">' + "".join(map(causal_step, hypothesis["causal_links"])) + "</ol>"
        if index < 2:
            primary.append(f'<article class="path reveal" aria-labelledby="{anchor}-title">'
                           f'<div class="path-head">{node}<div><div class="meta">'
                           f'<span class="label">{label}</span><span class="label{" tie" if tied else ""}">'
                           f'{rank_label}</span></div><h3 id="{anchor}-title" class="display">{title}</h3>'
                           f'</div></div>{chain}</article>')
        else:
            additional.append(f'<div class="third reveal">{node}<div><p class="label">{label} · {rank_label}</p>'
                              f'<p><b>{title}</b></p><details class="ev"><summary>View causal chain</summary>'
                              f'{chain}</details></div></div>')
    divider = '<div class="or" aria-hidden="true">or</div>'
    return f'<div class="paths">{divider.join(primary)}</div>{"".join(additional)}'


def inspection_key(hypotheses, inspection):
    selected = set(inspection["distinguishes_hypothesis_ids"]) if inspection else set()
    rows = []
    for hypothesis in hypotheses:
        if hypothesis["id"] not in selected:
            continue
        for label, key in (("Supports", "confirm_test"), ("Weighs against", "rule_out_test")):
            rows.append(f'<div class="key-row"><span class="if">{text(hypothesis[key])}</span>'
                        '<svg viewBox="0 0 30 12" aria-hidden="true"><path d="M0 6h28M23 1l5 5-5 5"/></svg>'
                        f'<span class="then"><small>{label}</small>{text(hypothesis["id"])}</span></div>')
    return f'<div class="key reveal"><h3>What the findings would mean</h3>{"".join(rows)}</div>' if rows else ""


def drawer(letter, title, content, count_label=""):
    return (f'<details class="drawer"><summary><span class="n">{letter}</span><h3>{title}</h3>'
            f'<span class="count">{count_label}</span><span class="pm" aria-hidden="true"></span></summary>'
            f'<div class="drawer-body">{content}</div></details>')


def engineering_review(notes):
    """Present recorded verdicts without assigning a verdict to ambiguous review text."""
    headings = list(REVIEW_HEADING.finditer(notes))
    criteria = {name.casefold(): name for name in REVIEW_CRITERIA}
    rows, run_details, supported = [], [], 0
    preface = notes[:headings[0].start()].strip() if headings else notes.strip()
    if preface:
        run_details.append(f"<p>{text(preface)}</p>")
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(notes)
        body = notes[heading.end():end].strip()
        key = heading[1].casefold()
        if key not in criteria:
            run_details.append(f"<p><b>{text(heading[1])}</b> {text(body)}</p>")
            continue
        verdict = REVIEW_STATUS.match(body)
        status = verdict[1].capitalize() if verdict else "Status unclear"
        description = body[verdict.end():] if verdict else body
        supported += status == "Supported"
        # The reference design gives only supported rows a green check mark.
        tone = "" if status == "Supported" else " na"
        rows.append(f'<div class="check"><b>{text(criteria[key])}</b>'
                    f'<span class="verdict{tone}">{text(status)}</span>'
                    f'<span>{text(description)}</span></div>')

    count_label = (f"{supported} of {len(rows)} supported" if rows else "See notes")
    details = '<div class="checks">' + "".join(rows) + "</div>" if rows else ""
    if run_details:
        details += ('<details class="ev"><summary>Run details</summary>'
                    f'<div class="ev-body">{"".join(run_details)}</div></details>')
    return drawer("C", "View engineering review", details, count_label)


def unavailable(result, default):
    return f"<p>{text((result or {}).get('reason') or default)}</p>"


def remaining_life_calculator(beta, eta, gamma, samples):
    """Embed an offline calculator using the same hazard increment as the Python fit."""
    return (
        f'<details class="ev" id="weibull-window" data-beta="{beta}" data-eta="{eta}" data-gamma="{gamma}" '
        f'data-samples="{escape(json.dumps(samples, allow_nan=False), quote=True)}">'
        '<summary>Estimate risk before the next intervention</summary><div class="ev-body">'
        '<div class="comparison-controls">'
        '<label>Current operating age (h)<input type="number" min="0" step="any" data-age></label>'
        '<label>Operating hours until intervention<input type="number" min="0" step="any" data-window></label>'
        '</div><p aria-live="polite">Enter the current age and the hours until intervention.</p></div></details>'
        """
        <script>
        (() => {
            const panel = document.getElementById("weibull-window");
            const age = panel.querySelector("[data-age]");
            const windowHours = panel.querySelector("[data-window]");
            const output = panel.querySelector("[aria-live]");
            const beta = Number(panel.dataset.beta);
            const eta = Number(panel.dataset.eta);
            const gamma = Number(panel.dataset.gamma);
            const samples = JSON.parse(panel.dataset.samples);
            const percent = risk => risk > 0 && risk < 0.001 ? "<0.1%" : (risk * 100).toFixed(1) + "%";
            // Interpolate the ordered samples as Python's inclusive quantiles do.
            function percentile(sorted, p) {
                const index = (sorted.length - 1) * p;
                const low = Math.floor(index);
                return sorted[low] + (sorted[Math.ceil(index)] - sorted[low]) * (index - low);
            }
            function failureRisk(shape, scale, start, end) {
                const shiftedStart = Math.max(0, start - gamma);
                const shiftedEnd = end - gamma;
                if (shiftedEnd <= 0) return 0;
                // The change in cumulative hazard conditions on survival to the current age.
                const fraction = shiftedStart
                    ? -Math.expm1(-shape * Math.log1p((end - start) / shiftedStart))
                    : 1;
                if (fraction <= 0) return 0;
                const increment = Math.exp(
                    shape * (Math.log(shiftedEnd) - Math.log(scale)) + Math.log(fraction));
                return -Math.expm1(-increment);
            }
            panel.addEventListener("input", () => {
                const start = age.valueAsNumber;
                const duration = windowHours.valueAsNumber;
                const end = start + duration;
                if (!Number.isFinite(end) || start < 0 || duration <= 0 || end <= start) {
                    output.textContent = "Enter a non-negative age and a positive operating-hour window.";
                    return;
                }
                let message = percent(failureRisk(beta, eta, start, end))
                    + " fitted probability of failure before intervention,"
                    + " given survival to the current age.";
                if (samples.length) {
                    const risks = samples.map(([shape, scale]) => failureRisk(shape, scale, start, end))
                        .sort((a, b) => a - b);
                    message += " Approximate 95% interval: " + percent(percentile(risks, 0.025))
                        + " to " + percent(percentile(risks, 0.975)) + ".";
                }
                output.textContent = message;
            });
        })();
        </script>
        """
    )


def reliability(fit, strategy=None):
    if not fit or fit["status"] != "completed":
        return unavailable(fit, "Weibull results were unavailable for this report.")
    beta, eta, gamma = (fit[key] for key in ("beta", "eta_operating_hours", "gamma_operating_hours"))
    observed = fit.get("empirical_failure_curve") or []
    strategy = strategy or {}
    baseline = strategy.get("baseline", strategy)
    replacement_axis = strategy.get("axes", {}).get("replacement_interval", {})
    labels_by_age = {point["value"]: [] for point in replacement_axis.get("points", [])}
    # A sensitivity point may also be a baseline policy. Plot that age once and
    # retain each configured policy label if multiple policies share the age.
    for name, policy in baseline.get("strategies", {}).items():
        age = policy.get("replace_at_operating_hours")
        if policy.get("status") == "completed" and age is not None:
            labels_by_age.setdefault(age, []).append(POLICY_NAMES.get(name, name))
    ages = sorted(labels_by_age)
    last_observed = observed[-1]["age_operating_hours"] if observed else 0
    end = max(eta, gamma + 1.5 * eta, last_observed, *ages)

    def xy(age, risk):
        return f"{60 + 520 * age / end:.2f},{205 - 175 * risk:.2f}"

    def risk_at(age):
        return failure_probability(beta, eta, gamma, 0, age)

    # Include policy ages exactly rather than estimating their risks from SVG samples.
    plot_ages = sorted({end * i / 150 for i in range(151)} | set(ages))
    fitted = " ".join(xy(age, risk_at(age)) for age in plot_ages)
    bootstrap = fit.get("risk_uncertainty") or {}
    samples = [(sample["beta"], sample["eta_operating_hours"])
               for sample in bootstrap.get("parameter_samples", [])] if bootstrap.get("status") == "available" else []
    band = ""
    if len(samples) >= 2:
        lower, upper = [], []
        # Form the band from pointwise risk percentiles of the paired parameter fits.
        for age in plot_ages:
            risks = [failure_probability(shape, scale, gamma, 0, age) for shape, scale in samples]
            cuts = quantiles(risks, n=40, method="inclusive")
            lower.append(xy(age, cuts[0]))
            upper.append(xy(age, cuts[-1]))
        band = f'<polygon fill="#80ddd3" opacity=".2" points="{" ".join(lower + upper[::-1])}"/>'
    empirical = ""
    if observed:
        # Draw a step at each observed age and stop at the end of observed follow-up.
        steps = [xy(0, 0)]
        previous = 0
        for point in observed:
            age, risk = point["age_operating_hours"], point["failure_probability"]
            steps.extend((xy(age, previous), xy(age, risk)))
            previous = risk
        empirical = (f'<polyline fill="none" stroke="currentColor" stroke-width="2" '
                     f'stroke-dasharray="5 4" points="{" ".join(steps)}"/>')
    grid = "".join(
        f'<path d="M60 {205 - 175 * value}H580" stroke="currentColor" opacity=".2"/>'
        f'<text x="52" y="{209 - 175 * value}" text-anchor="end">{value:.0%}</text>'
        for value in (0, .25, .5, .75, 1)
    )
    ticks = "".join(
        f'<text x="{60 + 520 * i / 4}" y="226" text-anchor="middle">{end * i / 4:,.0f}</text>'
        for i in range(5)
    )
    policy_rows = []
    markers = []
    for age in ages:
        risk = risk_at(age)
        x, y = xy(age, risk).split(",")
        label = " / ".join(labels_by_age[age])
        prefix = f"{text(label)} &middot; " if label else ""
        description = f"{prefix}{age:,.0f} h &middot; {risk:.1%} fitted risk"
        policy_rows.append(f"<li>{description}</li>")
        markers.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#80ddd3">'
                       f'<title>{description}</title></circle>')
    policies = ("<p>Failure risk by replacement age</p><ul>" + "".join(policy_rows) + "</ul>"
                if policy_rows else "")
    interval = fit.get("beta_profile_likelihood_95_interval")
    uncertainty = (f"<p>Approximate 95% profile likelihood interval for &beta; "
                   f"{interval[0]:.3f}&ndash;{interval[1]:.3f}.</p>" if interval else "")
    cohort = (f'<p>{text(fit["failures"])} failures and {text(fit["right_censored"])} '
              'right-censored lives. The observed estimate accounts for these partial lives.</p>'
              if observed else '<p>No observed cohort curve was supplied with this fit.</p>')
    legend = 'Solid teal: fitted Weibull. Dashed: observed Kaplan&ndash;Meier estimate.' if observed else 'Solid teal: fitted Weibull.'
    if band:
        legend += " Shaded: approximate 95% pointwise interval."
        uncertainty += ("<p>The band estimates uncertainty in fitted failure risk at each age "
                        "using resampled bearing records. It does not include changes in future duty "
                        "or uncertainty in the strategy costs.</p>")
    elif bootstrap.get("status") == "unavailable":
        uncertainty += "<p>Too many resampled fits were unstable to show a risk interval.</p>"
    return (
        '<svg role="img" aria-label="Cumulative failure probability by operating age" '
        'viewBox="0 0 640 260" xmlns="http://www.w3.org/2000/svg">'
        f'<g fill="currentColor" font-size="17">{grid}{ticks}'
        '<text x="320" y="252" text-anchor="middle">Operating age (h)</text></g>'
        f'{band}{empirical}<polyline fill="none" stroke="#80ddd3" stroke-width="3" points="{fitted}"/>'
        f'{"".join(markers)}</svg><p>{legend}</p>{policies}'
        f'{remaining_life_calculator(beta, eta, gamma, samples if band else [])}'
        '<details class="ev"><summary>View model details</summary><div class="ev-body">'
        f'{cohort}<p>Shape &beta; {beta:.4g} &middot; Scale &eta; {eta:,.1f} h &middot; '
        f'Location &gamma; {gamma:,.1f} h</p>{uncertainty}</div></details>'
    )


def strategy_table(baseline):
    if not baseline or baseline["status"] != "completed":
        return unavailable(baseline, "No strategy simulation result was supplied.")
    rows = []
    for name, policy in baseline["strategies"].items():
        label = text(POLICY_NAMES.get(name, name))
        if policy["status"] != "completed":
            rows.append(f'<tr><th scope="row">{label}</th><td colspan="3">'
                        f'{text(policy.get("reason") or policy["status"])}</td></tr>')
            continue
        metrics = policy["fleet_metrics"]
        cells = "".join(f"<td>{metrics[key]['mean']:,.1f}</td>" for key in
                        ("discounted_total_cost", "failures", "downtime_operating_hours"))
        rows.append(f'<tr><th scope="row">{label}</th>{cells}</tr>')
    return (f'<table><caption>Baseline assumptions · {text(baseline["horizon_years"])} years · '
            f'{text(baseline["fleet_size"])} bearings</caption><thead><tr><th scope="col">Strategy</th>'
            f'<th scope="col">Mean discounted cost ({text(baseline["currency"])})</th>'
            f'<th scope="col">Mean failures</th><th scope="col">Mean downtime (h)</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def render(findings, fit=None, strategy=None, review=None, *, synthetic=False,
           title=None, incident_label=None, summary=None):
    baseline = (strategy or {}).get("baseline", strategy)
    demo = synthetic or any(result and result.get("synthetic") is True
                            for result in (findings, fit, baseline))
    inspection = findings["next_inspection"]
    limitations = findings["limitations"]
    hypotheses = sorted(findings["hypotheses"], key=lambda hypothesis: hypothesis["rank"])
    asset = findings["asset_id"]
    incident = incident_label or findings["event_id"]
    title = title or f"Asset {asset} investigation"
    scope = " · ".join(findings[key] for key in ("site", "asset_id", "event_id"))
    action = inspection["action"] if inspection else "No supported inspection recorded."
    lead = [hypothesis for hypothesis in hypotheses if hypothesis["rank"] == hypotheses[0]["rank"]]
    finding = ("The leading hypotheses are tied and require field verification." if len(lead) > 1
               else "The leading hypothesis requires field verification." if lead
               else "The evidence did not support a ranked hypothesis.")
    facts = "".join(f"<div><dt>{label}</dt><dd>{text(value)}</dd></div>" for label, value in
                    (("Incident", incident), ("Asset · Site", f"{asset} · {findings['site']}")))
    evidence = drawer("B", "What the records leave open",
                      items(limitations) if limitations else "<p>No limitations were recorded.</p>",
                      f"{len(limitations)} limitations")
    if review:
        evidence += engineering_review(review)
    # Escaping the less-than sign prevents data from closing the JSON script element.
    embedded = json.dumps(strategy, allow_nan=False).replace("<", "\\u003c")
    return Template(TEMPLATE_PATH.read_text(encoding="utf-8")).substitute(
        report_title=text(title),
        report_label=text(f"{title} · Root cause analysis"),
        incident_scope=text(scope),
        synthetic_notice_html='<span class="label stamp">Synthetic demonstration</span>' if demo else "",
        summary_html=text(summary or finding),
        facts_html=facts,
        incident_label=text(incident),
        paths_html=cause_paths(hypotheses),
        uncertainty_html=f'<div class="why-tie reveal"><p class="label">Finding status</p><p>{text(finding)}</p></div>',
        inspection_context=text(inspection["rationale"] if inspection else ""),
        inspection_steps_html=f"<li><p>{text(action)}</p></li>",
        inspection_key_html=inspection_key(hypotheses, inspection),
        evidence_drawers_html=evidence,
        strategy_status="Results available" if any(result and result["status"] == "completed"
                                                   for result in (fit, baseline)) else "Not available",
        weibull_html=reliability(fit, strategy),
        strategy_comparison_html=strategy_table(baseline),
        footer_text=text(f"{'Synthetic demonstration · ' if demo else ''}{scope}. "
                         "Field verification and closure remain with the site engineer."),
        strategy_results_json=embedded,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("findings", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fit", type=Path)
    parser.add_argument("--strategy", type=Path)
    parser.add_argument("--review", type=Path, help="Plain-text review notes")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--title", help="Short, factual investigation title")
    parser.add_argument("--incident-label", help="Brief observed incident description")
    parser.add_argument("--summary", help="Brief reviewed finding and first action")
    args = parser.parse_args()
    try:
        findings, fit, strategy = [
            json.loads(path.read_text(encoding="utf-8-sig")) if path else None
            for path in (args.findings, args.fit, args.strategy)
        ]
        review = args.review.read_text(encoding="utf-8-sig") if args.review else None
        html = render(findings, fit, strategy, review, synthetic=args.synthetic,
                      title=args.title, incident_label=args.incident_label, summary=args.summary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(html)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
        parser.exit(2, f"Report unavailable: {error}\n")
    print(args.output)


if __name__ == "__main__":
    main()
