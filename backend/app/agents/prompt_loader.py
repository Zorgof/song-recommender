"""Versioned prompt files: `prompts/<name>.v<N>.md`.

A file holds a system and a user message, each introduced by a marker line:

    <!-- system -->
    ...
    <!-- user -->
    ... {{placeholder}} ...

Placeholders are `{{name}}`; rendering fails if one is left without a value or a value is
given that the template does not use. By default the highest version of a prompt is loaded; the
version is recorded on every trace (FR-42).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_NAMES = ("router", "need_analyst", "curator")

_FILE_RE = re.compile(r"^(?P<name>[a-z_]+)\.v(?P<version>\d+)\.md$")
_SECTION_RE = re.compile(r"^<!--\s*(system|user)\s*-->\s*$", re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user: str

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(_PLACEHOLDER_RE.findall(self.system + self.user))

    def render(self, **values: str) -> list[BaseMessage]:
        missing = self.placeholders - values.keys()
        unused = values.keys() - self.placeholders
        if missing or unused:
            raise ValueError(
                f"Prompt {self.name}.{self.version}: missing {sorted(missing)}, "
                f"unused {sorted(unused)}"
            )

        def fill(text: str) -> str:
            return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], text)

        return [SystemMessage(fill(self.system)), HumanMessage(fill(self.user))]


def parse_prompt(name: str, version: str, text: str) -> PromptTemplate:
    parts = _SECTION_RE.split(text)
    # [preamble, "system", body, "user", body]
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    if list(sections) != ["system", "user"]:
        raise ValueError(f"Prompt {name}.{version} needs a system and then a user section")
    return PromptTemplate(name, version, sections["system"].strip(), sections["user"].strip())


def load_prompt(
    name: str, version: int | None = None, directory: Path = PROMPTS_DIR
) -> PromptTemplate:
    versions = {
        int(m["version"]): path
        for path in directory.glob(f"{name}.v*.md")
        if (m := _FILE_RE.match(path.name)) and m["name"] == name
    }
    if not versions:
        raise FileNotFoundError(f"No prompt file {name}.v<N>.md in {directory}")
    chosen = max(versions) if version is None else version
    if chosen not in versions:
        raise FileNotFoundError(f"No prompt file {name}.v{chosen}.md in {directory}")
    return parse_prompt(name, f"v{chosen}", versions[chosen].read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PromptLibrary:
    router: PromptTemplate
    need_analyst: PromptTemplate
    curator: PromptTemplate

    @classmethod
    def load(cls, directory: Path = PROMPTS_DIR) -> PromptLibrary:
        return cls(*(load_prompt(name, directory=directory) for name in PROMPT_NAMES))

    @property
    def versions(self) -> dict[str, str]:
        """Recorded in the trace metadata, e.g. {"router": "v1", ...}."""
        return {p.name: p.version for p in (self.router, self.need_analyst, self.curator)}
