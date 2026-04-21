import asyncio
import logging

import aiohttp

log = logging.getLogger("cypher.ai")

_MAX_RETRIES = 4
_RATE_LIMIT_DEFAULT = 60.0
_RATE_LIMIT_MIN = 30.0

class RateLimitError(RuntimeError):
    def __str__(self):
        return "Gemini is rate limited right now — try again in a minute."


_SYSTEM_PROMPT = (
    "You are Cypher, a helpful and friendly AI assistant living inside a Discord server. "
    "Respond conversationally and concisely."
)


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self._api_key = api_key
        self.url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f":generateContent?key={api_key}"
        )

    async def generate(self, prompt: str, max_new_tokens: int = 512) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": max_new_tokens,
                "topP": 0.9,
            },
        }
        headers = {"Content-Type": "application/json"}

        for attempt in range(1, _MAX_RETRIES + 1):
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, headers=headers, json=payload) as resp:

                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        except (KeyError, IndexError):
                            return str(data)

                    elif resp.status == 429:
                        wait = _RATE_LIMIT_DEFAULT
                        try:
                            body = await resp.json()
                            for detail in body.get("error", {}).get("details", []):
                                delay = detail.get("retryDelay", "")
                                if delay:
                                    wait = max(float(delay.rstrip("s")), _RATE_LIMIT_MIN)
                                    break
                        except Exception:
                            pass
                        log.warning(f"Gemini rate limited — waiting {wait:.0f}s (attempt {attempt}/{_MAX_RETRIES})")
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(wait)
                        else:
                            raise RateLimitError()

                    else:
                        text = await resp.text()
                        raise RuntimeError(f"Gemini API {resp.status}: {text}")

        raise RateLimitError()

    # Keep attribute name consistent with what ai_chat.py displays in the footer
    @property
    def model_id(self) -> str:
        return self.model


def load_engine(api_key: str, model: str) -> "GeminiClient | None":
    if not api_key:
        log.warning("GEMINI_API_KEY not set — AI inference disabled")
        return None
    if not model:
        log.warning("GEMINI_MODEL not set — AI inference disabled")
        return None
    log.info(f"Gemini client ready: {model}")
    return GeminiClient(api_key, model)
