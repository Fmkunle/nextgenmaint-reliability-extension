"""Independent numerical checks for the maintenance simulator."""

import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/reliability-extension/shared/scripts"))
from simulate_maintenance import run_bearing, simulate


class MaintenanceValidation(unittest.TestCase):
    def test_exponential_renewal_benchmark(self):
        """With beta=1 and zero downtime, failures form a Poisson process."""
        fixture = ROOT / "tests/fixtures/p101/simulation-inputs.json"
        scenario = json.loads(fixture.read_text(encoding="utf-8"))
        scenario["fleet"]["starting_age_groups"] = [
            {"age_operating_hours": 0, "bearing_count": 20}
        ]
        scenario["simulation"].update(replications=1000, real_discount_rate_per_year=0)
        scenario["strategies"] = {
            "run_to_failure": {},
            "scheduled_replacement": {"replace_at_operating_hours": 4000},
        }
        costs = scenario["consequences"]
        for kind in ("failure_replacement", "scheduled_replacement"):
            costs[kind]["downtime_operating_hours"] = 0
        fit = dict(status="completed", model="weibull_2p", synthetic=True,
                   part_number=scenario["fleet"]["part_number"],
                   duty_group=scenario["fleet"]["duty_group"], beta=1,
                   eta_operating_hours=6000, gamma_operating_hours=0)
        policies = simulate(fit, scenario)["strategies"]
        for name, policy in policies.items():
            with self.subTest(policy=name):
                metrics = policy["fleet_metrics"]
                self.assertAlmostEqual(metrics["failures"]["mean"], 200, delta=3)
                self.assertEqual(metrics["downtime_operating_hours"]["mean"], 0)
                self.assertEqual(metrics["discounted_production_loss"]["mean"], 0)
                if name == "run_to_failure":
                    self.assertEqual(metrics["scheduled_replacements"]["mean"], 0)
                    expected_cost = 200 * costs["failure_replacement"]["direct_cost_per_event"]
                    self.assertAlmostEqual(metrics["discounted_total_cost"]["mean"],
                                           expected_cost, delta=expected_cost * .015)
                else:
                    # Long-run renewal rate is S(T) / E[min(life, T)].
                    # Allow for incomplete cycles at the finite horizon and sampling error.
                    survival = math.exp(-4000 / 6000)
                    expected_planned = 20 * 60000 * survival / (6000 * (1 - survival))
                    planned = metrics["scheduled_replacements"]["mean"]
                    self.assertAlmostEqual(planned, expected_planned, delta=20)
                    expected_cost = (
                        200 * costs["failure_replacement"]["direct_cost_per_event"]
                        + expected_planned * costs["scheduled_replacement"]["direct_cost_per_event"]
                    )
                    self.assertAlmostEqual(metrics["discounted_total_cost"]["mean"],
                                           expected_cost, delta=expected_cost * .04)

    def test_inspection_averts_failure_only_with_detection_and_time_to_act(self):
        # With beta=eta=1, the first supplied exponential draw sets failure at
        # hour 8. A second, distant failure keeps the rest of the run uneventful.
        for probability, lead, triggered in ((0, 1, False), (1, 1, True), (1, 2, False)):
            with self.subTest(probability=probability, lead=lead):
                rng = Mock()
                rng.expovariate.side_effect = [8, 100]
                detection = Mock()
                detection.random.return_value = 0.5
                metrics = dict(failures=0, scheduled_replacements=0, inspections=0,
                               inspection_triggered_replacements=0,
                               downtime_operating_hours=0, discounted_direct_cost=0,
                               discounted_production_loss=0)
                run_bearing(
                    0, math.inf, 1, 1, 100, 9.5, 0, 10,
                    {"inspection": (5, 0), "failure_replacement": (100, 1),
                     "inspection_triggered_replacement": (40, 1)},
                    rng, metrics, gamma=0, inspection=(5, 3, probability, lead),
                    detection_rng=detection,
                )
                self.assertEqual(metrics["inspections"], 1)
                self.assertEqual(metrics["failures"], int(not triggered))
                self.assertEqual(metrics["inspection_triggered_replacements"], int(triggered))
                self.assertEqual(metrics["downtime_operating_hours"], 1)
                self.assertEqual(metrics["discounted_direct_cost"], 45 if triggered else 105)
                self.assertEqual(metrics["discounted_production_loss"], 10)


if __name__ == "__main__":
    unittest.main()
