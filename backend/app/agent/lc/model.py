"""Our AI providers as a LangChain chat model.

The person brings their own model, through whichever provider they
connected. `ProviderChatModel` lets LangChain and LangGraph talk to it
without a second set of vendor adapters: each call is translated into
our `Message` shape, sent through the provider we already have (with
its fallback and error handling), and the reply translated back.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

from app.agent.providers.base import LLMProvider, Message, Role, ToolCall, ToolSchema


def to_ours(messages: Sequence[BaseMessage]) -> list[Message]:
    out: list[Message] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append(Message(role=Role.SYSTEM, content=_text(m)))
        elif isinstance(m, HumanMessage):
            out.append(Message(role=Role.USER, content=_text(m)))
        elif isinstance(m, AIMessage):
            calls = [
                ToolCall(id=c["id"] or ToolCall.new_id(), name=c["name"], arguments=c["args"])
                for c in m.tool_calls
            ]
            out.append(Message(role=Role.ASSISTANT, content=_text(m) or None, tool_calls=calls))
        elif isinstance(m, ToolMessage):
            out.append(
                Message(
                    role=Role.TOOL,
                    content=_text(m),
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                )
            )
        else:  # pragma: no cover - LangChain has no other message kinds we use
            raise TypeError(f"Cannot send a {type(m).__name__} to the provider")
    return out


def to_langchain(message: Message) -> AIMessage:
    return AIMessage(
        content=message.content or "",
        tool_calls=[
            {"id": c.id, "name": c.name, "args": c.arguments, "type": "tool_call"}
            for c in message.tool_calls
        ],
    )


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part if isinstance(part, str) else str(part.get("text", "")) for part in content)


def _schema_of(tool: BaseTool) -> dict[str, Any]:
    args = tool.args_schema
    if args is not None and hasattr(args, "model_json_schema"):
        schema = args.model_json_schema()
        schema.pop("title", None)
        return schema
    return {"type": "object", "properties": {}}


class ProviderChatModel(BaseChatModel):
    """`provider.complete`, as a LangChain chat model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # An LLMProvider; typed loosely so pydantic does not try to validate it.
    provider: Any
    model: str
    temperature: float = 0.2
    tool_schemas: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "provider-chat-model"

    def bind_tools(  # type: ignore[override]
        self, tools: Sequence[BaseTool | dict[str, Any]], **kwargs: Any
    ) -> Runnable[Any, AIMessage]:
        schemas: list[ToolSchema] = []
        for tool in tools:
            if isinstance(tool, BaseTool):
                schemas.append(ToolSchema(tool.name, tool.description, _schema_of(tool)))
            elif isinstance(tool, dict):
                schemas.append(
                    ToolSchema(
                        tool["name"], tool.get("description", ""), tool.get("parameters", {})
                    )
                )
            else:
                raise TypeError(f"Cannot bind {tool!r}; pass a LangChain tool")
        return self.model_copy(update={"tool_schemas": schemas})

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        provider: LLMProvider = self.provider
        reply = await provider.complete(
            messages=to_ours(messages),
            model=self.model,
            tools=self.tool_schemas or None,
            temperature=self.temperature,
        )
        message = to_langchain(reply.message)
        message.usage_metadata = {
            "input_tokens": reply.usage.prompt_tokens,
            "output_tokens": reply.usage.output_tokens,
            "total_tokens": reply.usage.total,
        }
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("This model is async only; use ainvoke.")
