"""Sync the evaluation dataset to LangSmith and run one experiment.

    cd backend
    uv run python -m evals.run_evals                 # all examples
    uv run python -m evals.run_evals --limit 3       # a quick smoke run
    uv run python -m evals.run_evals --sync-only     # only update the LangSmith dataset

Configuration comes from the repository `.env`, like the app. LangSmith must be enabled
(LANGSMITH_TRACING=true and LANGSMITH_API_KEY). The experiment is named after the prompt
versions, and its metadata records the prompt versions, models, judge, candidate count and app
version, so experiments can be filtered and compared in LangSmith (Datasets → the dataset →
Experiments → compare).
"""

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from typing import Any

import langsmith
from langsmith import aevaluate

from app import __version__
from app.agents.prompt_loader import PromptLibrary
from app.agents.state import CANDIDATE_COUNT
from app.config import Settings, get_settings
from app.errors import ConfigurationError
from app.llm.models import TIERS, ModelRegistry, Tier
from app.observability.tracing import build_client
from evals.dataset import DEFAULT_DATASET_NAME, load_examples, sync_dataset
from evals.evaluators import (
    diversity,
    explanation_language,
    load_judge_prompt,
    make_fit_judge,
    outcome,
)
from evals.target import open_eval_target

logger = logging.getLogger("evals")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", default=DEFAULT_DATASET_NAME, help="LangSmith dataset name")
    parser.add_argument("--limit", type=int, help="run only the first N examples of the file")
    parser.add_argument("--concurrency", type=int, default=4, help="examples run in parallel")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="run every example N times (results vary between runs; use 2-3 to compare versions)",
    )
    parser.add_argument(
        "--with-youtube", action="store_true", help="also look up YouTube (uses the daily quota)"
    )
    parser.add_argument(
        "--judge-model",
        help="provider:model for the fit judge (default: the configured LLM_HEAVY)",
    )
    parser.add_argument("--prefix", help="experiment name prefix (default: the prompt versions)")
    parser.add_argument("--description", help="experiment description, e.g. what changed")
    parser.add_argument("--sync-only", action="store_true", help="sync the dataset and stop")
    return parser.parse_args(argv)


def judge_registry(settings: Settings, judge_model: str | None) -> tuple[ModelRegistry, Tier, str]:
    """The judge runs on the heavy tier, or on a separately configured model."""
    if judge_model is None:
        registry = ModelRegistry(settings)
        return registry, "heavy", str(registry.tier_config("heavy").primary)
    judge_settings = settings.model_copy(
        update={
            "llm_light": judge_model,
            "llm_heavy": judge_model,
            "llm_light_fallback": None,
            "llm_heavy_fallback": None,
        }
    )
    return ModelRegistry(judge_settings), "heavy", judge_model


def experiment_prefix(prompt_versions: dict[str, str]) -> str:
    """E.g. "curator-v1.need_analyst-v1.router-v1"."""
    return ".".join(f"{name}-{version}" for name, version in sorted(prompt_versions.items()))


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    client = build_client(settings)
    if client is None:
        print("LangSmith is not enabled: set LANGSMITH_TRACING=true and LANGSMITH_API_KEY.")
        return 2

    examples = load_examples()
    dataset, plan = await asyncio.to_thread(sync_dataset, client, args.dataset, examples)
    print(
        f"Dataset '{args.dataset}': {len(examples)} examples "
        f"({len(plan.create)} created, {len(plan.update)} updated, "
        f"{len(plan.delete)} deleted, {plan.unchanged} unchanged)\n  {dataset.url}"
    )
    if args.sync_only:
        return 0

    selected = examples[: args.limit] if args.limit else examples
    data = list(
        await asyncio.to_thread(
            lambda: list(
                client.list_examples(
                    dataset_id=dataset.id, example_ids=[e.example_id for e in selected]
                )
            )
        )
    )

    registry = ModelRegistry(settings)
    prompts = PromptLibrary.load()
    judge, judge_tier, judge_name = judge_registry(settings, args.judge_model)
    judge_prompt = load_judge_prompt()
    metadata: dict[str, Any] = {
        "app_version": __version__,
        "prompt_versions": prompts.versions,
        "models": {tier: str(registry.tier_config(tier).primary) for tier in TIERS},
        "candidate_count": CANDIDATE_COUNT,
        "judge_model": judge_name,
        "judge_prompt": judge_prompt.version,
        "youtube": args.with_youtube,
        # The SDK adds num_repetitions, dataset_version and the git commit itself.
        "examples": len(data),
    }

    # The SDK accepts evaluators taking (inputs, outputs) and summary evaluators taking
    # (outputs) at runtime, but its type hints only describe the (run, example) forms.
    evaluators: list[Any] = [
        outcome,
        explanation_language,
        make_fit_judge(judge, judge_tier, judge_prompt),
    ]
    summary_evaluators: list[Any] = [diversity]

    async with open_eval_target(settings, with_youtube=args.with_youtube) as target:

        async def recommend_song(inputs: dict[str, Any]) -> dict[str, Any]:
            # Named like the app's root run, so experiment traces read the same.
            return await target.run(inputs)

        # The app's models read their keys from Settings, not os.environ; the same goes for
        # LangSmith: every run of the experiment goes through this client.
        with langsmith.tracing_context(enabled=True, client=client):
            results = await aevaluate(
                recommend_song,
                data=data,
                evaluators=evaluators,
                summary_evaluators=summary_evaluators,
                experiment_prefix=args.prefix or experiment_prefix(prompts.versions),
                description=args.description,
                metadata=metadata,
                max_concurrency=args.concurrency,
                num_repetitions=args.repetitions,
                client=client,
            )
            rows = [row async for row in results]

    print_summary(rows)
    print(f"\nExperiment: {results.experiment_name}\n  {results.url}")
    comparison = await results.get_comparison_url()
    if comparison:
        print(f"Compare experiments:\n  {comparison}")
    return 0


def print_summary(rows: list[Any]) -> None:
    scores: dict[str, list[float]] = defaultdict(list)
    outputs = []
    for row in rows:
        outputs.append(row["run"].outputs or {})
        for result in row["evaluation_results"]["results"]:
            # Booleans count as 0/1; results without a score (None) are left out.
            if isinstance(result.score, int | float):
                scores[result.key].append(float(result.score))
    print(f"\n{'metric':<22}{'mean':>8}{'n':>5}")
    for key in sorted(scores):
        values = scores[key]
        print(f"{key:<22}{sum(values) / len(values):>8.2f}{len(values):>5}")
    for result in diversity(outputs)["results"]:
        score = "-" if result["score"] is None else f"{result['score']:.2f}"
        print(f"{result['key']:<22}{score:>8}{len(rows):>5}  {result.get('comment') or ''}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        sys.exit(asyncio.run(run(parse_args(sys.argv[1:]))))
    except ConfigurationError as exc:
        print(exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
