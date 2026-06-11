from openai import AsyncOpenAI
from logger import get_logger

log = get_logger(__name__)


def generate_function_calling(tool_schema: dict):
    return {
        "type": "function",
        "function": tool_schema,
    }


class LLM:
    def __init__(self, api_key: str, system_prompt: str = "You are a helpful assistant.",
                 tools: dict = {}, base_url: str = "https://api.deepseek.com/v1",
                 model: str = "deepseek-v4-flash"):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model

    async def generate_response(self, prompt: str, temperature: float = 0.7):
        log.debug("LLM request (model=%s, temperature=%s)", self.model, temperature)
        response = await self.client.chat.completions.create(
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
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                *messages,
            ],
            tools=[generate_function_calling(self.tools[t].tool_schema) for t in self.tools],
            temperature=temperature,
            stream=True,
        )
        async for chunk in response:
            yield chunk

    async def stream_response(self, prompt: str, temperature: float = 0.7):
        log.debug("LLM stream request (model=%s, temperature=%s)", self.model, temperature)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            tools=[generate_function_calling(self.tools[t].tool_schema) for t in self.tools],
            temperature=temperature,
            stream=True,
        )
        async for chunk in response:
            yield chunk
