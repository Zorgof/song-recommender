"""The evaluation package: dataset, LangSmith sync, evaluators, judge and target (offline)."""

import uuid
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_graph
from app.config import Settings
from evals.dataset import (
    EvalExample,
    RemoteExample,
    load_examples,
    plan_sync,
    sync_dataset,
)
from evals.evaluators import (
    detect_language,
    diversity,
    explanation_language,
    load_judge_prompt,
    make_fit_judge,
    outcome,
)
from evals.run_evals import experiment_prefix, judge_registry
from evals.target import DEFAULT_ANSWERS, EvalTarget
from tests.agent_fakes import (
    FakeCatalog,
    SessionFactory,
    clarification_profile,
    curator_output,
    make_harness,
    make_registry,
    need_profile,
    track,
)
from tests.conftest import make_app_settings
from tests.fake_llm import SchemaRoutedChatModel

POLISH = (
    "Ten utwór może delikatnie dopełnić Twój spokojny wieczór, nie zakłócając chwili z "
    "herbatą. Oszczędna gitara i cichy śpiew zostawiają dużo miejsca na własne myśli."
)
ENGLISH = (
    "Let this gentle, floating piece give your mind a little room to slow down tonight. "
    "There is no need to follow a beat or words, just settle in."
)


def example(**overrides: Any) -> EvalExample:
    values: dict[str, Any] = {
        "id": "en-tired",
        "text": "Tired after work.",
        "locale": "en",
        "category": "short",
        **overrides,
    }
    return EvalExample.model_validate(values)


def completed(**rec: Any) -> dict[str, Any]:
    recommendation = {
        "title": "Holocene",
        "artist": "Bon Iver",
        "spotify_verified": True,
        "youtube_verified": False,
        "explanation": ENGLISH,
        "need_summary": "You are tired and want to slow down tonight.",
        **rec,
    }
    return {
        "status": "completed",
        "latency_s": 9.5,
        "clarified": False,
        "recommendation": recommendation,
        "need_profile": need_profile(),
        "escalations": [],
        "curation_attempts": 1,
    }


def by_key(results: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {r["key"]: r["score"] for r in results["results"]}


# --- Dataset ---


def test_the_dataset_covers_the_planned_cases() -> None:
    examples = load_examples()

    assert 30 <= len(examples) <= 40
    assert {e.locale for e in examples} == {"en", "pl"}
    categories = Counter(e.category for e in examples)
    for required in ("short", "long", "ambiguous", "contradictory", "genre-hint"):
        assert categories[required] >= 2, required
    assert categories["cross-language"] >= 4
    assert any(e.input_mode == "voice" for e in examples)
    # Polish input with the English UI and the other way round.
    assert any(e.locale == "en" and detect_language(e.text) == "pl" for e in examples)
    assert any(e.locale == "pl" and detect_language(e.text) == "en" for e in examples)
    assert all(e.clarification_answer for e in examples if e.category == "ambiguous")


def test_example_ids_are_stable_and_inputs_are_minimal() -> None:
    first, again = example(), example()

    assert first.example_id == again.example_id
    assert first.example_id != example(id="other").example_id
    assert first.inputs == {"text": "Tired after work.", "locale": "en", "input_mode": "text"}
    assert example(clarification_answer="Calm.").inputs["clarification_answer"] == "Calm."


def test_invalid_lines_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text('{"id": "a", "text": "hi", "locale": "en", "category": "short"}\n')
    with pytest.raises(ValueError, match="line 1"):
        load_examples(path)

    line = '{"id": "a", "text": "Long day.", "locale": "en", "category": "short"}\n'
    path.write_text(line + "\n" + line)
    with pytest.raises(ValueError, match=r"duplicate ids \['a'\]"):
        load_examples(path)


def test_sync_plan_creates_updates_and_deletes() -> None:
    same, changed, new = example(id="same"), example(id="changed"), example(id="new")
    stale = uuid.uuid4()
    remote = [
        # LangSmith's own metadata keys do not count as a change.
        RemoteExample(same.example_id, same.inputs, {**same.metadata, "dataset_split": ["base"]}),
        RemoteExample(changed.example_id, {**changed.inputs, "text": "old"}, changed.metadata),
        RemoteExample(stale, {"text": "removed from the file"}, {}),
    ]

    plan = plan_sync([same, changed, new], remote)

    assert [e.id for e in plan.create] == ["new"]
    assert [e.id for e in plan.update] == ["changed"]
    assert plan.delete == [stale]
    assert plan.unchanged == 1


def test_removed_notes_are_an_update() -> None:
    plain = example()
    remote = RemoteExample(plain.example_id, plain.inputs, {**plain.metadata, "notes": "old"})

    assert [e.id for e in plan_sync([plain], [remote]).update] == ["en-tired"]


class FakeDatasetClient:
    def __init__(self, existing: list[RemoteExample] | None = None) -> None:
        self.exists = existing is not None
        self.remote = existing or []
        self.calls: list[tuple[str, Any]] = []
        self.dataset = type("Dataset", (), {"id": uuid.uuid4(), "url": "https://ls/d"})()

    def has_dataset(self, *, dataset_name: str) -> bool:
        return self.exists

    def create_dataset(self, dataset_name: str, *, description: str) -> Any:
        self.calls.append(("create_dataset", dataset_name))
        return self.dataset

    def read_dataset(self, *, dataset_name: str) -> Any:
        return self.dataset

    def list_examples(self, dataset_id: uuid.UUID) -> list[Any]:
        return [
            type("Example", (), {"id": r.id, "inputs": r.inputs, "metadata": r.metadata})()
            for r in self.remote
        ]

    def create_examples(self, *, dataset_id: uuid.UUID, examples: Sequence[dict[str, Any]]) -> None:
        self.calls.append(("create", [e["id"] for e in examples]))

    def update_examples(self, *, dataset_id: uuid.UUID, updates: Sequence[dict[str, Any]]) -> None:
        self.calls.append(("update", [e["id"] for e in updates]))

    def delete_examples(self, example_ids: Sequence[uuid.UUID]) -> None:
        self.calls.append(("delete", example_ids))


def test_sync_creates_the_dataset_and_its_examples() -> None:
    client = FakeDatasetClient()
    examples = [example(id="a"), example(id="b")]

    dataset, _ = sync_dataset(client, "evals", examples)

    assert dataset is client.dataset
    assert client.calls == [
        ("create_dataset", "evals"),
        ("create", [e.example_id for e in examples]),
    ]


def test_sync_of_an_unchanged_dataset_writes_nothing() -> None:
    a = example(id="a")
    client = FakeDatasetClient([RemoteExample(a.example_id, a.inputs, a.metadata)])

    _, plan = sync_dataset(client, "evals", [a])

    assert client.calls == []
    assert plan.unchanged == 1


# --- Deterministic evaluators ---


@pytest.mark.parametrize(
    ("text", "language"),
    [
        (POLISH, "pl"),
        ("Pozwól, by spokojne frazy fortepianu dały Ci chwilę wytchnienia.", "pl"),
        (ENGLISH, "en"),
        ("You feel underwhelmed and could use a gentle lift.", "en"),
        ("", None),
        ("Holocene", None),
    ],
)
def test_detect_language(text: str, language: str | None) -> None:
    assert detect_language(text) == language


def test_explanation_language_follows_the_ui_locale() -> None:
    english = completed()
    polish = completed(explanation=POLISH, need_summary="Chcesz się wyciszyć po dniu pracy.")

    assert explanation_language({"locale": "en"}, english)["score"] == 1
    assert explanation_language({"locale": "pl"}, polish)["score"] == 1
    wrong = explanation_language({"locale": "pl"}, english)
    assert wrong["score"] == 0
    assert wrong["comment"] == "explanation: en, need_summary: en"
    assert explanation_language({"locale": "en"}, {"status": "failed"})["score"] is None


def test_outcome_of_a_verified_recommendation() -> None:
    scores = by_key(outcome(completed()))

    assert scores == {
        "completed": 1,
        "clarified": 0,
        "latency_s": 9.5,
        "within_15s": 1,
        "spotify_verified": 1,
        "escalated": 0,
        "curation_attempts": 1,
    }
    with_youtube = outcome(completed() | {"youtube_checked": True})
    assert by_key(with_youtube)["youtube_verified"] == 0


def test_outcome_of_a_slow_escalated_run_and_of_a_failed_run() -> None:
    escalated = completed()
    escalated |= {
        "latency_s": 31.0,
        "escalations": [{"node": "music_curator", "reason": "no_verified_candidates"}],
        "curation_attempts": 2,
    }
    scores = by_key(outcome(escalated))
    assert (scores["within_15s"], scores["escalated"], scores["curation_attempts"]) == (0, 1, 2)

    failed = outcome({"status": "failed", "error_code": "llm_unavailable", "latency_s": 2.0})
    assert by_key(failed)["completed"] == 0
    assert by_key(failed)["spotify_verified"] == 0
    assert failed["results"][0]["comment"] == "llm_unavailable"


def test_diversity_counts_repeats_across_the_dataset() -> None:
    outputs = [
        completed(),
        completed(title="Holocene - Remastered 2011"),  # the same song
        completed(title="Skinny Love"),  # the same artist
        completed(title="Weightless", artist="Marconi Union"),
        {"status": "failed"},
    ]

    results = {r["key"]: r for r in diversity(outputs)["results"]}

    assert results["distinct_songs"]["score"] == 3 / 4
    assert results["distinct_songs"]["comment"] == "bon iver|holocene x2"
    assert results["distinct_artists"]["score"] == 2 / 4
    assert results["distinct_artists"]["comment"] == "bon iver x3"
    assert diversity([{"status": "failed"}])["results"][0]["score"] is None


# --- LLM-as-judge ---


def judge_with(tmp_path: Path, verdicts: list[Any]) -> tuple[Any, SchemaRoutedChatModel]:
    model = SchemaRoutedChatModel(model_name="judge-v1", responses={"FitVerdict": verdicts})
    registry = make_registry(tmp_path, model, model)
    return make_fit_judge(registry, "heavy", load_judge_prompt()), model


async def test_fit_judge_maps_the_score_and_sees_the_whole_case(tmp_path: Path) -> None:
    verdict = {
        "reasoning": "Calm, matches the goal.",
        "energy": 2,
        "goal": 2,
        "requests": 2,
        "specificity": 1,
        "weaknesses": "A common pick.",
        "profile_faithful": True,
    }
    fit, model = judge_with(tmp_path, [verdict])
    outputs = completed() | {
        "clarified": True,
        "clarification_question": "How do you feel?",
        "clarification_answer": "Tired.",
    }

    scores = await fit({"text": "meh"}, outputs)

    assert by_key(scores) == {
        "fit": 7 / 8,
        "fit_energy": 1,
        "fit_goal": 1,
        "fit_requests": 1,
        "fit_specificity": 0.5,
        "profile_faithful": 1,
    }
    assert scores["results"][0]["comment"] == (
        "7/8 (energy 2, goal 2, requests 2, specificity 1). Weaknesses: A common pick.\n"
        "Calm, matches the goal."
    )
    prompt = str(model.calls_for("FitVerdict")[0][1].content)
    for part in ("<description>\nmeh\n</description>", "Answer: Tired.", "Holocene by Bon Iver"):
        assert part in prompt
    assert '"goal": "calm"' in prompt


async def test_fit_judge_scores_a_missing_recommendation_zero(tmp_path: Path) -> None:
    fit, model = judge_with(tmp_path, [])

    assert by_key(await fit({"text": "x"}, {"status": "failed"}))["fit"] == 0
    assert model.calls == []


def test_judge_can_use_a_separate_model(tmp_path: Path) -> None:
    settings: Settings = make_app_settings(tmp_path)

    _, tier, name = judge_registry(settings, None)
    assert (tier, name) == ("heavy", "openai:test-heavy-model")

    registry, tier, name = judge_registry(settings, "openai:judge-model")
    assert name == "openai:judge-model"
    assert str(registry.tier_config("heavy").primary) == "openai:judge-model"
    assert registry.tier_config("heavy").fallback is None


def test_experiment_prefix_names_the_prompt_versions() -> None:
    versions = {"router": "v1", "need_analyst": "v2", "curator": "v1"}

    assert experiment_prefix(versions) == "curator-v1.need_analyst-v2.router-v1"


# --- Target ---

HOLOCENE = track("Holocene", "Bon Iver")


def eval_target(tmp_path: Path, session_factory: SessionFactory, **light: list[Any]) -> EvalTarget:
    harness = make_harness(
        tmp_path,
        session_factory,
        light={
            "RouterClassification": [{"complexity": "simple", "reason": "Short."}],
            "NeedProfile": [need_profile()],
            "CuratorOutput": [curator_output(("Holocene", "Bon Iver"))],
            **light,
        },
        catalog=FakeCatalog.knowing(HOLOCENE),
    )
    return EvalTarget(build_graph(InMemorySaver()), harness.deps)


async def test_target_returns_the_recommendation_and_run_details(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    target = eval_target(tmp_path, session_factory)

    outputs = await target.run({"text": "Tired after a long day at work.", "locale": "en"})

    assert outputs["status"] == "completed"
    assert outputs["recommendation"]["title"] == "Holocene"
    assert outputs["recommendation"]["spotify_verified"] is True
    assert outputs["need_profile"]["goal"] == "calm"
    assert outputs["clarified"] is False
    assert (outputs["escalated"], outputs["curation_attempts"]) == (False, 1)
    assert outputs["latency_s"] >= 0


async def test_target_answers_a_clarifying_question_itself(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    target = eval_target(
        tmp_path,
        session_factory,
        # Two examples, each: question, then the profile after the answer.
        NeedProfile=[clarification_profile("How do you feel?"), need_profile()] * 2,
    )

    scripted = await target.run({"text": "meh", "locale": "en", "clarification_answer": "Tired."})
    generic = await target.run({"text": "meh", "locale": "pl"})

    assert scripted["status"] == "completed"
    assert scripted["clarified"] is True
    assert scripted["clarification_question"] == "How do you feel?"
    assert scripted["clarification_answer"] == "Tired."
    assert generic["clarification_answer"] == DEFAULT_ANSWERS["pl"]


async def test_target_ignores_the_history(tmp_path: Path, session_factory: SessionFactory) -> None:
    target = eval_target(tmp_path, session_factory)

    first = await target.run({"text": "Tired after a long day at work.", "locale": "en"})
    second = await target.run({"text": "Tired after a long day at work.", "locale": "en"})

    # In the app the second request would exclude Holocene (FR-16); here each example is fresh.
    assert first["recommendation"]["title"] == second["recommendation"]["title"] == "Holocene"


async def test_target_reports_application_errors_as_failed(
    tmp_path: Path, session_factory: SessionFactory
) -> None:
    target = eval_target(tmp_path, session_factory, NeedProfile=[RuntimeError("provider down")])

    outputs = await target.run({"text": "Tired after a long day at work.", "locale": "en"})

    assert outputs["status"] == "failed"
    assert outputs["error_code"] == "llm_unavailable"
    assert "recommendation" not in outputs
