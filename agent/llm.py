import asyncio
from collections.abc import AsyncIterator
from typing import Any

from openai import APIError, AsyncOpenAI
from logger import get_logger

log = get_logger(__name__)

MAX_API_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)


def generate_function_calling(tool_schema: dict):
    return {
        "type": "function",
        "function": tool_schema,
    }


class LLM:
    def __init__(self, api_key: str, system_prompt: str = "You are a helpful assistant.",
                 tools: dict = {}, base_url: str = "https://api.deepseek.com/v1",
                 model: str = "deepseek-v4-flash", provider: str = "deepseek"):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model
        self.provider = provider

    @staticmethod
    def _error_code(error: APIError) -> Any:
        code = getattr(error, "code", None)
        if code:
            return code
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            nested_error = body.get("error")
            if isinstance(nested_error, dict):
                return nested_error.get("code") or nested_error.get("type")
            return body.get("code") or body.get("type")
        return None

    def _log_retry(self, error: APIError, attempt: int) -> None:
        log.warning(
            "LLM API attempt %s/%s failed; retrying "
            "(provider=%s, model=%s, error=%s, status=%s, code=%s)",
            attempt,
            MAX_API_ATTEMPTS,
            self.provider,
            self.model,
            type(error).__name__,
            getattr(error, "status_code", None),
            self._error_code(error),
        )

    async def _create_with_retry(self, **kwargs: Any) -> Any:
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return await self.client.chat.completions.create(**kwargs)
            except APIError as error:
                if attempt >= MAX_API_ATTEMPTS:
                    raise
                self._log_retry(error, attempt)
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt - 1])
        raise RuntimeError("unreachable LLM retry state")

    async def _stream_with_retry(self, **kwargs: Any) -> AsyncIterator[Any]:
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            yielded_chunk = False
            try:
                response = await self.client.chat.completions.create(**kwargs)
                async for chunk in response:
                    yielded_chunk = True
                    yield chunk
                return
            except APIError as error:
                if yielded_chunk or attempt >= MAX_API_ATTEMPTS:
                    raise
                self._log_retry(error, attempt)
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt - 1])

    async def generate_response(self, prompt: str, temperature: float = 0.7):
        log.debug("LLM request (model=%s, temperature=%s)", self.model, temperature)
        response = await self._create_with_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=[generate_function_calling(self.tools[t].tool_schema) for t in self.tools],
            temperature=temperature,
        )
        usage = getattr(response, "usage", None)
        if usage:
            log.info(
                "LLM response (model=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
                self.model, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            )
        return response

    async def stream_response_messages(self, messages: list, temperature: float = 0.7):
        log.debug("LLM stream request (model=%s, temperature=%s)", self.model, temperature)
        async for chunk in self._stream_with_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                *messages,
            ],
            tools=[generate_function_calling(self.tools[t].tool_schema) for t in self.tools],
            temperature=temperature,
            stream=True,
        ):
            yield chunk

    async def stream_response(self, prompt: str, temperature: float = 0.7):
        log.debug("LLM stream request (model=%s, temperature=%s)", self.model, temperature)
        async for chunk in self._stream_with_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=[generate_function_calling(self.tools[t].tool_schema) for t in self.tools],
            temperature=temperature,
            stream=True,
        ):
            yield chunk
