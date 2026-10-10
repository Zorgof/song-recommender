"""A scripted chat model for testing the LLM layer offline.

It supports tool binding, so LangChain's real `with_structured_output` (function-calling path),
output parsing and `with_fallbacks` all run against it unchanged.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr


class ScriptedChatModel(BaseChatModel):
    """Answers each call with the next script item: a dict is returned as the arguments of a
    call to the bound tool (i.e. the structured output); an exception is raised instead.
    The last item repeats when the script runs out."""

    model_name: str = "scripted-model"
    script: list[Any]
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        item = self.script[min(len(self._calls), len(self.script) - 1)]
        self._calls.append(list(messages))
        if isinstance(item, BaseException):
            raise item
        tool_name = kwargs["tools"][0]["function"]["name"]
        message = AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": item, "id": f"call_{len(self._calls)}"}],
            response_metadata={"model_name": self.model_name},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class SchemaRoutedChatModel(BaseChatModel):
    """Answers by the structured-output schema that is bound (the tool name, e.g.
    "NeedProfile"): each schema has its own queue of answers (dicts or exceptions). The last
    answer of a queue repeats. Every call is recorded with its schema and messages."""

    model_name: str = "routed-model"
    responses: dict[str, list[Any]]
    _calls: list[tuple[str, list[BaseMessage]]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "schema-routed"

    @property
    def calls(self) -> list[tuple[str, list[BaseMessage]]]:
        return list(self._calls)

    def calls_for(self, schema: str) -> list[list[BaseMessage]]:
        return [messages for name, messages in self._calls if name == schema]

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        schema = kwargs["tools"][0]["function"]["name"]
        answered = sum(1 for name, _ in self._calls if name == schema)
        self._calls.append((schema, list(messages)))
        queue = self.responses.get(schema)
        if not queue:
            raise AssertionError(f"{self.model_name}: no scripted answer for {schema}")
        item = queue[min(answered, len(queue) - 1)]
        if isinstance(item, BaseException):
            raise item
        message = AIMessage(
            content="",
            tool_calls=[{"name": schema, "args": item, "id": f"call_{len(self._calls)}"}],
            response_metadata={"model_name": self.model_name},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
