# BytePlus ModelArk Seedream image generation (adapted from the Yunwu Seedream generator).
# Docs: https://docs.byteplus.com/en/docs/ModelArk/1541523
import asyncio
import logging
from typing import List, Optional

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from interfaces.image_output import ImageOutput
from utils.image import image_path_to_b64
from utils.retry import after_func

ARK_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"


class ImageGeneratorSeedreamBytePlusAPI:
    def __init__(self, api_key: str, model: str = "dola-seedream-5-0-flash-260915",
                 size: str = "1K", base_url: str = ARK_BASE_URL, rate_limiter=None, **_ignored):
        self.api_key = api_key
        self.model = model
        self.size = size
        self.url = base_url.rstrip("/") + "/images/generations"
        self.rate_limiter = rate_limiter

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30),
           retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
           reraise=True, after=after_func)
    async def generate_single_image(self, prompt: str, reference_image_paths: List[str] = [],
                                    size: Optional[str] = None, aspect_ratio: Optional[str] = "16:9",
                                    **kwargs) -> ImageOutput:
        logging.info(f"Calling {self.model} to generate image...")
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        if aspect_ratio and aspect_ratio not in prompt:
            prompt = f"{prompt}\nAspect ratio {aspect_ratio}."
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": size if (size and ("K" in size)) else self.size,
            "response_format": "url",
            "watermark": False,
        }
        if reference_image_paths:
            payload["image"] = [image_path_to_b64(p, mime=True) for p in reference_image_paths]
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as s:
            async with s.post(self.url, json=payload, headers=headers) as r:
                body = await r.json(content_type=None)
                if r.status >= 400:
                    raise RuntimeError(f"Seedream image generation failed HTTP {r.status}: {body}")
        return ImageOutput(fmt="url", ext="png", data=body["data"][0]["url"])
