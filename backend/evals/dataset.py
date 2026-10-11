"""The evaluation dataset: `dataset.jsonl` in the repository, mirrored to a LangSmith dataset.

The JSONL file is the source of truth. Each example has a stable `id`; its LangSmith example id
is derived from it, so syncing creates new examples, updates changed ones and deletes removed
ones instead of duplicating the dataset on every run. LangSmith versions the dataset on every
change, and each experiment records the version it ran on.
"""

import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import Locale

DATASET_PATH = Path(__file__).with_name("dataset.jsonl")
DEFAULT_DATASET_NAME = "song-recommender-evals"
DATASET_DESCRIPTION = (
    "Mood/day descriptions for the song recommender: PL/EN/other input languages, both UI "
    "locales, short, long, ambiguous, contradictory, genre hints, voice transcripts. "
    "Source: backend/evals/dataset.jsonl."
)
_EXAMPLE_NAMESPACE = uuid.UUID("9a3c1f0e-2b7d-4e8a-9c51-7d2e6b4f3a10")

Category = Literal[
    "short",
    "long",
    "ambiguous",
    "contradictory",
    "genre-hint",
    "emotional",
    "cross-language",
    "voice",
    "adversarial",
]


class EvalExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    # The description, as a user would type or say it (FR-6 limits).
    text: str = Field(min_length=3, max_length=2000)
    # UI locale: the language of the explanation and of a clarifying question.
    locale: Locale
    input_mode: Literal["text", "voice"] = "text"
    category: Category
    # Sent if the agents ask a clarifying question; otherwise a generic answer is used.
    clarification_answer: str | None = None
    # For people reading the dataset; not used by the evaluators.
    notes: str | None = None

    @property
    def example_id(self) -> uuid.UUID:
        return uuid.uuid5(_EXAMPLE_NAMESPACE, self.id)

    @property
    def inputs(self) -> dict[str, Any]:
        inputs: dict[str, Any] = {
            "text": self.text,
            "locale": self.locale,
            "input_mode": self.input_mode,
        }
        if self.clarification_answer is not None:
            inputs["clarification_answer"] = self.clarification_answer
        return inputs

    @property
    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {"source_id": self.id, "category": self.category}
        if self.notes:
            metadata["notes"] = self.notes
        return metadata


def load_examples(path: Path = DATASET_PATH) -> list[EvalExample]:
    examples: list[EvalExample] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            examples.append(EvalExample.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(f"{path.name}, line {number}: {exc}") from exc
    ids = [example.id for example in examples]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{path.name}: duplicate ids {duplicates}")
    return examples


# --- Sync with LangSmith ---


@dataclass(frozen=True)
class RemoteExample:
    id: uuid.UUID
    inputs: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class SyncPlan:
    create: list[EvalExample] = field(default_factory=list)
    update: list[EvalExample] = field(default_factory=list)
    delete: list[uuid.UUID] = field(default_factory=list)
    unchanged: int = 0


def plan_sync(local: Sequence[EvalExample], remote: Iterable[RemoteExample]) -> SyncPlan:
    plan = SyncPlan()
    remote_by_id = {example.id: example for example in remote}
    for example in local:
        current = remote_by_id.pop(example.example_id, None)
        if current is None:
            plan.create.append(example)
        elif current.inputs != example.inputs or not _metadata_matches(current, example):
            plan.update.append(example)
        else:
            plan.unchanged += 1
    plan.delete = list(remote_by_id)
    return plan


# Metadata keys this module writes; LangSmith adds its own (e.g. dataset_split).
_OWN_METADATA_KEYS = ("source_id", "category", "notes")


def _metadata_matches(remote: RemoteExample, example: EvalExample) -> bool:
    return all(remote.metadata.get(k) == example.metadata.get(k) for k in _OWN_METADATA_KEYS)


class DatasetClient(Protocol):
    """The part of langsmith.Client used here."""

    def has_dataset(self, *, dataset_name: str) -> bool: ...
    def create_dataset(self, dataset_name: str, *, description: str) -> Any: ...
    def read_dataset(self, *, dataset_name: str) -> Any: ...
    def list_examples(self, dataset_id: uuid.UUID) -> Iterable[Any]: ...
    def create_examples(
        self, *, dataset_id: uuid.UUID, examples: Sequence[dict[str, Any]]
    ) -> Any: ...
    def update_examples(
        self, *, dataset_id: uuid.UUID, updates: Sequence[dict[str, Any]]
    ) -> Any: ...
    def delete_examples(self, example_ids: Sequence[uuid.UUID]) -> Any: ...


def sync_dataset(
    client: DatasetClient, name: str, examples: Sequence[EvalExample]
) -> tuple[Any, SyncPlan]:
    """Create the dataset if needed and make its examples match `examples`."""
    if client.has_dataset(dataset_name=name):
        dataset = client.read_dataset(dataset_name=name)
    else:
        dataset = client.create_dataset(name, description=DATASET_DESCRIPTION)
    remote = [
        RemoteExample(uuid.UUID(str(e.id)), dict(e.inputs or {}), dict(e.metadata or {}))
        for e in client.list_examples(dataset_id=dataset.id)
    ]
    plan = plan_sync(examples, remote)
    if plan.create:
        client.create_examples(
            dataset_id=dataset.id,
            examples=[
                {"id": e.example_id, "inputs": e.inputs, "metadata": e.metadata}
                for e in plan.create
            ],
        )
    if plan.update:
        client.update_examples(
            dataset_id=dataset.id,
            updates=[
                {"id": e.example_id, "inputs": e.inputs, "metadata": e.metadata}
                for e in plan.update
            ],
        )
    if plan.delete:
        client.delete_examples(example_ids=plan.delete)
    return dataset, plan
