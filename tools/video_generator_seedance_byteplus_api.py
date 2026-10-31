# BytePlus ModelArk Seedance video generation (adapted from the Yunwu Doubao/Seedance generator).
# Docs: https://docs.byteplus.com/en/docs/ModelArk/1520757
import asyncio
import logging
from typing import List, Optional

import aiohttp

from interfaces.video_output import VideoOutput
from utils.image import image_path_to_b64

ARK_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"

# UI name -> exact ModelArk model ID
SEEDANCE_MODELS = {
    "seedance-1-0-pro-fast": "seedance-1-0-pro-fast-251015",
    "dreamina-seedance-2-0-fast": "dreamina-seedance-2-0-fast-260128",
    "dreamina-seedance-2-0": "dreamina-seedance-2-0-260128",
    "dreamina-seedance-2-5": "dreamina-seedance-2-5-260628",
}
# models that accept a last_frame image
_FLF_OK = {"dreamina-seedance-2-0-fast-260128", "dreamina-seedance-2-0-260128", "dreamina-seedance-2-5-260628"}


class VideoGeneratorSeedanceBytePlusAPI:
    def __init__(
        self,
        api_key: str,
        model: str = "seedance-1-0-pro-fast",
        resolution: str = "720p",
        ratio: str = "16:9",
        duration: int = 5,
        base_url: str = ARK_BASE_URL,
        max_create_attempts: int = 3,
        poll_interval: int = 5,
        max_poll_attempts: int = 240,
        rate_limiter=None,
        **_ignored,
    ):
        self.api_key = api_key
        self.model = SEEDANCE_MODELS.get(model, model)
        self.resolution = resolution
        self.ratio = ratio
        self.duration = duration
        self.base_url = base_url.rstrip("/")
        self.max_create_attempts = max_create_attempts
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts
        self.rate_limiter = rate_limiter

    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        resolution: Optional[str] = None,
        duration: Optional[int] = None,
        **kwargs,
    ) -> VideoOutput:
        refs = list(reference_image_paths or [])
        if len(refs) > 2:
            raise ValueError("The number of reference images must be no more than 2")
        if len(refs) == 2 and self.model not in _FLF_OK:
            logging.warning(f"{self.model} has no last-frame support; using first frame only.")
            refs = refs[:1]

        content = [{"type": "text", "text": prompt}]
        roles = ["first_frame", "last_frame"]
        for i, p in enumerate(refs):
            content.append({"type": "image_url", "image_url": {"url": image_path_to_b64(p, mime=True)}, "role": roles[i]})

        ratio = self.ratio
        if refs and "seedance-2-5" in self.model:
            ratio = "adaptive"  # 2.5 requires adaptive ratio for image-to-video
        payload = {
            "model": self.model,
            "content": content,
            "resolution": resolution or self.resolution,
            "ratio": ratio,
            "duration": int(duration or self.duration),
            "watermark": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/contents/generations/tasks"
        logging.info(f"Calling {self.model} to generate video...")
        if self.rate_limiter:
            await self.rate_limiter.acquire()

        async with aiohttp.ClientSession() as session:
            task_id = None
            for attempt in range(self.max_create_attempts):
                async with session.post(url, json=payload, headers=headers) as r:
                    body = await r.json(content_type=None)
                    if r.status < 400 and body.get("id"):
                        task_id = body["id"]
                        break
                    logging.warning(f"Seedance create failed HTTP {r.status}: {body}")
                    if r.status in (400, 401, 403, 404) or attempt == self.max_create_attempts - 1:
                        raise RuntimeError(f"Seedance task creation failed HTTP {r.status}: {body}")
                await asyncio.sleep(2 ** attempt)

            for _ in range(self.max_poll_attempts):
                await asyncio.sleep(self.poll_interval)
                async with session.get(f"{url}/{task_id}", headers=headers) as r:
                    body = await r.json(content_type=None)
                status = body.get("status")
                if status == "succeeded":
                    return VideoOutput(fmt="url", ext="mp4", data=body["content"]["video_url"])
                if status in ("failed", "cancelled", "expired"):
                    raise RuntimeError(f"Seedance task {task_id} {status}: {body.get('error')}")
            raise TimeoutError(f"Seedance task {task_id} did not finish in time")
