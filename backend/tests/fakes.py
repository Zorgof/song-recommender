"""Fake credentials for tests.

Key-shaped strings are assembled at runtime, so no literal in the repository looks like a real
credential: secret scanners (GitHub secret scanning, GitGuardian) match on the shape of a key,
not on whether it is valid. Never write a literal key-shaped string (OpenAI/Anthropic `sk-`,
LangSmith `lsv2_`, Google `AIza`, JWTs, ...) into the code base; use these helpers instead.
"""


def fake_key(prefix: str, length: int = 24) -> str:
    return prefix + "x" * length


FAKE_OPENAI_KEY = fake_key("sk" + "-proj-")
FAKE_LANGSMITH_KEY = fake_key("lsv2" + "_pt_")
FAKE_GOOGLE_KEY = fake_key("AI" + "za", 35)
FAKE_BEARER_TOKEN = fake_key("tok", 20)
