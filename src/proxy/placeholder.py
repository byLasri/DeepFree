from dataclasses import dataclass
from typing import Optional, AsyncGenerator
from ..protocol.normalized_events import ProtocolRequest, ProtocolResponse


@dataclass
class OpenAIChatCompletionRequest:
    model: str
    messages: list[dict]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: Optional[list[dict]] = None
    tool_choice: Optional[str] = None


@dataclass
class OpenAIChatCompletionResponse:
    id: str
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[dict] = None
    usage: Optional[dict] = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


@dataclass
class OpenAIChatCompletionChunk:
    id: str
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[dict] = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


class DeepSeekAdapter:
    def __init__(self):
        pass

    def translate_request(self, openai_req: OpenAIChatCompletionRequest) -> ProtocolRequest:
        raise NotImplementedError("Phase 1: Adapter not yet implemented")

    def translate_response(self, deepseek_resp: ProtocolResponse) -> OpenAIChatCompletionResponse:
        raise NotImplementedError("Phase 1: Adapter not yet implemented")

    def translate_stream(self, deepseek_stream) -> AsyncGenerator[OpenAIChatCompletionChunk, None]:
        raise NotImplementedError("Phase 1: Adapter not yet implemented")


class OpenAICompatibleProxy:
    def __init__(self, adapter: DeepSeekAdapter):
        self.adapter = adapter

    async def chat_completions(self, request: OpenAIChatCompletionRequest):
        raise NotImplementedError("Phase 1: Proxy not yet implemented")

    async def chat_completions_stream(self, request: OpenAIChatCompletionRequest):
        raise NotImplementedError("Phase 1: Proxy not yet implemented")