"""Fixed-seed, offline Nepal sensitivity demonstration; never calls agents."""

from pathlib import Path

from ark_api.routes.simulations import run_response_simulation
from ark_api.simulation.models import RobustnessConfig, SimulationRequest

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
)


def main() -> int:
    request = SimulationRequest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    request.robustness = RobustnessConfig(
        enabled=True,
        seed=42,
        trial_count=20,
        responder_unavailability_count=1,
        additional_request_count=1,
    )
    response = run_response_simulation(request)
    robustness = response.robustness
    summaries = {s.plan_id: s for s in robustness.summaries}
    print(
        "Rank | Plan | Baseline score | Viable | Trials | Rate | Median | Worst | First"
    )
    for rank, baseline in enumerate(response.results, 1):
        summary = summaries[baseline.plan_id]
        print(
            f"{rank} | {baseline.plan_id} | {baseline.score:.2f} | "
            f"{summary.viable_trial_count} | {summary.completed_trial_count} | "
            f"{summary.viability_rate:.2f} | {summary.median_score:.2f} | "
            f"{summary.minimum_score:.2f} | {summary.first_place_trial_count}"
        )
    print(f"Baseline recommendation: {response.recommended_plan_id}")
    print(f"Sensitivity ranking: {', '.join(robustness.robustness_order)}")
    print(
        f"Recommendation stability rate: {robustness.recommendation_stability_rate:.2f}"
    )
    print(
        f"Seed: {robustness.seed}; "
        f"matched trials: {robustness.completed_matched_trials}"
    )
    print(robustness.disclaimer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
