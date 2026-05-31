from openai import OpenAI
from logger import get_logger

log = get_logger(__name__)

def generate_function_calling(tool_schema:dict):
    function_calling = {
      "type":"function",
      "function":tool_schema
    }
    return function_calling

class LLM:
    def __init__(self, api_key: str, system_prompt: str = "You are a helpful assistant.", tools: dict = {},
                 base_url: str = "https://api.deepseek.com/v1", model: str = "deepseek-v4-flash"):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model

    def generate_response(self, prompt: str, temperature: float = 0.7):
        log.debug("LLM request (model=%s, temperature=%s)", self.model, temperature)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            tools=[generate_function_calling(self.tools[tool_name].tool_schema) for tool_name in self.tools],
            temperature=temperature
        )
        usage = getattr(response, "usage", None)
        if usage:
            log.info(
                "LLM response (model=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
                self.model, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            )
        return response

    def stream_response_messages(self, messages: list, temperature: float = 0.7):
        """Stream a response from the LLM using OpenAI-format messages list."""
        log.debug("LLM stream request (model=%s, temperature=%s)", self.model, temperature)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                *messages,
            ],
            tools=[generate_function_calling(self.tools[tool_name].tool_schema) for tool_name in self.tools],
            temperature=temperature,
            stream=True,
        )
        yield from response

    def stream_response(self, prompt: str, temperature: float = 0.7):
        """Stream a response from the LLM, yielding raw chunks."""
        log.debug("LLM stream request (model=%s, temperature=%s)", self.model, temperature)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            tools=[generate_function_calling(self.tools[tool_name].tool_schema) for tool_name in self.tools],
            temperature=temperature,
            stream=True,
        )
        yield from response

if __name__ == "__main__":
    with open("api_key.txt", "r", encoding="utf-8") as f:
        api_key = f.read().strip()
    llm = LLM(api_key)
    prompt = "Where is China located?"
    response = llm.generate_response(prompt)
    
    print(response.choices[0].message.content)