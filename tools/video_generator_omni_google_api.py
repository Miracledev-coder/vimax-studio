# Gemini Omni Flash video generation (replaces the shut-down veo-3.1-*-preview models).
# Docs: https://ai.google.dev/gemini-api/docs/omni-flash  (Interactions API, google-genai >= 2.19)
import asyncio
import base64
import logging
import time
from typing import List, Optional

from google import genai
from google.genai import types

from interfaces.video_output import VideoOutput


def _mime(path: str) -> str:
    p = path.lower()
    if p.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if p.endswith(".webp"):
        return "image/webp"
    return "image/png"


class VideoGeneratorOmniGoogleAPI:
    """gemini-omni-1.1-flash: text-to-video, first-frame and first+last-frame.

    Pricing hint: ~$0.10 per second of output (a 4s 720p clip is ~$0.40).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-omni-1.1-flash",
        resolution: str = "720p",
        aspect_ratio: str = "16:9",
        duration: int = 4,
        rate_limiter=None,
        timeout_s: int = 600,
        **_ignored,
    ):
        # Omni calls are synchronous (typically 1-5 min); cap each HTTP request at timeout_s.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s) * 1000))
        self.model = model
        self.resolution = resolution
        self.aspect_ratio = aspect_ratio
        self.duration = duration
        self.rate_limiter = rate_limiter

    def _upload(self, path: str):
        f = self.client.files.upload(file=path, config={"mime_type": _mime(path)})
        deadline = time.time() + 120
        while getattr(f.state, "name", str(f.state)) == "PROCESSING" and time.time() < deadline:
            time.sleep(2)
            f = self.client.files.get(name=f.name)
        return {"type": "image", "uri": f.uri, "mime_type": f.mime_type or _mime(path)}

    def _generate_sync(self, prompt, reference_image_paths, resolution, aspect_ratio, duration) -> bytes:
        refs = list(reference_image_paths or [])
        if len(refs) > 2:
            raise ValueError("The number of reference images must be no more than 2")
        parts = [self._upload(p) for p in refs]
        if len(refs) == 2:
            prompt = f"<FIRST_FRAME> <LAST_FRAME> {prompt}"
        elif len(refs) == 1:
            prompt = f"<FIRST_FRAME> {prompt}"
        parts.append({"type": "text", "text": prompt})
        duration = max(3, min(10, int(duration)))
        interaction = self.client.interactions.create(
            model=self.model,
            input=parts,
            response_format={
                "type": "video",
                "delivery": "uri",
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "duration": f"{duration}s",
            },
        )
        out = getattr(interaction, "output_video", None)
        if out is None:
            raise RuntimeError(f"Omni Flash returned no video (status={getattr(interaction, 'status', '?')})")
        if getattr(out, "data", None):
            data = out.data
            return base64.b64decode(data) if isinstance(data, str) else data
        if getattr(out, "uri", None):
            return self.client.files.download(file=out.uri)
        raise RuntimeError("Omni Flash response had neither video data nor uri")

    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        duration: Optional[int] = None,
        **kwargs,
    ) -> VideoOutput:
        logging.info(f"Calling {self.model} to generate video...")
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        last_err = None
        for attempt in range(3):
            try:
                data = await asyncio.to_thread(
                    self._generate_sync, prompt, reference_image_paths,
                    resolution or self.resolution, aspect_ratio or self.aspect_ratio,
                    duration or self.duration,
                )
                return VideoOutput(fmt="bytes", ext="mp4", data=data)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and "limit: 0" not in str(e) and attempt < 2:
                    await asyncio.sleep(5 * 2 ** attempt)
                    continue
                raise
        raise last_err
