import asyncio
import logging

import aiohttp

log = logging.getLogger("cypher.slm")

_MAX_RETRIES = 3
_RATE_LIMIT_DEFAULT = 60.0   # fallback wait if Retry-After header is missing
_MODEL_LOAD_CAP = 120.0      # max seconds to wait on a cold-start 503


class HFInferenceClient:
    def __init__(self, api_token: str, model_id: str):
        self.model_id = model_id
        self.url = f"https://api-inference.huggingface.co/models/{model_id}"
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def generate(self, prompt: str, max_new_tokens: int = 512) -> str:
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_new_tokens,
                "temperature": 0.2,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False,
            },
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, headers=self._headers, json=payload) as resp:

                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            return data[0].get("generated_text", "").strip()
                        return str(data).strip()

                    elif resp.status == 429:
                        wait = float(resp.headers.get("Retry-After", _RATE_LIMIT_DEFAULT))
                        log.warning(
                            f"HF rate limited — waiting {wait:.0f}s "
                            f"(attempt {attempt}/{_MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait)

                    elif resp.status == 503:
                        body = await resp.json()
                        wait = min(
                            float(body.get("estimated_time", 20.0)),
                            _MODEL_LOAD_CAP,
                        )
                        log.info(
                            f"HF model loading — waiting {wait:.0f}s "
                            f"(attempt {attempt}/{_MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait)

                    else:
                        text = await resp.text()
                        raise RuntimeError(f"HF API {resp.status}: {text}")

        raise RuntimeError(f"HF API did not respond after {_MAX_RETRIES} attempts")


def load_engine(api_token: str, model_id: str) -> "HFInferenceClient | None":
    if not api_token:
        log.warning("HF_API_TOKEN not set — inference disabled")
        return None
    if not model_id:
        log.warning("HF_MODEL_ID not set — inference disabled")
        return None
    log.info(f"HF Inference client ready: {model_id}")
    return HFInferenceClient(api_token, model_id)
