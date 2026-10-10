from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompt_loader import PROMPT_NAMES, PromptLibrary, load_prompt

EXPECTED_PLACEHOLDERS = {
    "router": {"user_input", "heuristic_reasons"},
    "need_analyst": {"locale_name", "input_mode_note", "user_input", "clarification"},
    "curator": {
        "candidate_count",
        "locale_name",
        "need_profile",
        "excluded_tracks",
        "rejected_candidates",
    },
}


def write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_shipped_prompts_parse_and_use_the_expected_placeholders(name: str) -> None:
    prompt = load_prompt(name)

    assert prompt.version == "v1"
    assert prompt.system and prompt.user
    assert prompt.placeholders == EXPECTED_PLACEHOLDERS[name]


def test_library_reports_versions() -> None:
    assert PromptLibrary.load().versions == {"router": "v1", "need_analyst": "v1", "curator": "v1"}


def test_render_fills_placeholders_into_system_and_user_messages(tmp_path: Path) -> None:
    write(
        tmp_path, "demo.v1.md", "<!-- system -->\nSpeak {{lang}}.\n<!-- user -->\n{{text}} {{lang}}"
    )

    messages = load_prompt("demo", directory=tmp_path).render(lang="Polish", text="Hi {{x}}")

    assert messages == [SystemMessage("Speak Polish."), HumanMessage("Hi {{x}} Polish")]


def test_render_rejects_missing_and_unused_values(tmp_path: Path) -> None:
    write(tmp_path, "demo.v1.md", "<!-- system -->\n{{a}}\n<!-- user -->\n{{b}}")
    prompt = load_prompt("demo", directory=tmp_path)

    with pytest.raises(ValueError, match=r"missing \['b'\], unused \['c'\]"):
        prompt.render(a="1", c="3")


def test_highest_version_wins_unless_pinned(tmp_path: Path) -> None:
    for version in (1, 2, 10):
        write(tmp_path, f"demo.v{version}.md", f"<!-- system -->\nv{version}\n<!-- user -->\nu")
    write(tmp_path, "demo_other.v99.md", "<!-- system -->\nx\n<!-- user -->\ny")

    assert load_prompt("demo", directory=tmp_path).version == "v10"
    assert load_prompt("demo", version=2, directory=tmp_path).system == "v2"


@pytest.mark.parametrize(
    "text",
    ["no markers", "<!-- user -->\nu\n<!-- system -->\ns", "<!-- system -->\nonly system"],
)
def test_malformed_prompt_files_are_rejected(tmp_path: Path, text: str) -> None:
    write(tmp_path, "demo.v1.md", text)

    with pytest.raises(ValueError, match="system and then a user section"):
        load_prompt("demo", directory=tmp_path)


def test_missing_prompt_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("demo", directory=tmp_path)
    write(tmp_path, "demo.v1.md", "<!-- system -->\ns\n<!-- user -->\nu")
    with pytest.raises(FileNotFoundError):
        load_prompt("demo", version=3, directory=tmp_path)
