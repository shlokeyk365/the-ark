"""Replay the synthetic Nakkhu demo locally, without a server or network calls."""

import argparse
import sys
from pathlib import Path

from ark_api.routes.simulations import run_response_simulation
from ark_api.simulation.models import SimulationRequest

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data/scenarios/kantipur-river/nepal_nakkhu_demo_v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--output", type=Path, help="Write full response JSON to this path."
    )
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() == args.fixture.resolve():
            raise ValueError("Output must not overwrite the input fixture.")
        request = SimulationRequest.model_validate_json(
            args.fixture.read_text(encoding="utf-8")
        )
        response = run_response_simulation(request)
        if args.output:
            args.output.write_text(
                response.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        print(
            "Synthetic operational reconstruction; "
            "all counts and outcomes are assumptions."
        )
        print(
            "Rank | Plan ID | Viable | Score | Rescued | Evacuated | Isolated | "
            "Critical unanswered | Stranded"
        )
        for rank, result in enumerate(response.results, 1):
            metrics = result.metrics
            print(
                f"{rank} | {result.plan_id} | {str(result.viable).lower()} | "
                f"{result.score:.2f} | {metrics.people_rescued} | "
                f"{metrics.people_evacuated} | {metrics.people_isolated} | "
                f"{metrics.critical_calls_unanswered} | {metrics.responders_stranded}"
            )
        print(f"Recommended plan ID: {response.recommended_plan_id or 'none'}")
        return 0
    except Exception as error:
        # CLI boundary: a failed replay must never look like a successful demo.
        print(f"Demo failed ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
