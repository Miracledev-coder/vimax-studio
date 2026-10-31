# Deploying ViMax Studio as a PRIVATE Hugging Face Space (free CPU)

## Secrets (Space → Settings → Variables and secrets → "New secret")
| Name | Needed for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Preset "Google" and "Mixed": LLM (Gemini via OpenAI-compatible endpoint), image (Nano Banana `gemini-2.5-flash-image`), video (Veo `veo-3.1-generate-preview`) | https://aistudio.google.com/apikey — **billing must be enabled** for Veo / image generation |
| `OPENROUTER_API_KEY` | Preset "OpenRouter" and "Mixed": LLM, image (`openai/gpt-image-2`), video (`google/veo-3.1-lite`) | https://openrouter.ai/keys (prepaid credits) |
| `APP_PASSWORD` (optional, recommended) | Login gate for the web app (username `miracle`, override with `APP_USERNAME`) | choose yourself |

Optional variables: `VIMAX_OR_IMAGE_MODEL`, `VIMAX_OR_VIDEO_MODEL`, `VIMAX_OPENROUTER_VIDEO_RESOLUTION` (default 720p).
You need only ONE of the two API keys, matching the preset you pick in the UI.

## Rough cost per video (NOT documented by ViMax — estimate from vendor list prices, verify before use)
- LLM planning: cents (Gemini Flash).
- Images: ~$0.04 each (Nano Banana); a run makes character portraits + 1–2 keyframes per shot × candidates.
- Video: the big cost. Veo 3.1 is billed per second (roughly $0.15–$0.40/s depending on fast/standard; Lite cheaper). A shot ≈ 4–8 s.
- Example: 1 scene × 4 shots × 8 s on Veo 3.1 standard ≈ $5–13; with Lite/fast ≈ $1–5. Keep "Requirements" small and candidates = 1.

## Deploy steps
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login                      # token with write scope from https://huggingface.co/settings/tokens
huggingface-cli repo create vimax-studio --repo-type space --space_sdk gradio --private
huggingface-cli upload <HF_USERNAME>/vimax-studio /workspace/automation/hf-spaces/vimax . --repo-type space
```
Or with git:
```bash
git clone https://huggingface.co/spaces/<HF_USERNAME>/vimax-studio && cd vimax-studio
cp -r /workspace/automation/hf-spaces/vimax/* . && git add . && git commit -m "ViMax Studio" && git push
```
Then add the secrets above and the Space restarts. Hardware: "CPU basic" (free) is enough.

## Notes / limits on free CPU
- No GPU needed: all generation is via remote APIs; CPU only runs ffmpeg/moviepy concatenation.
- Free Spaces sleep after ~48 h idle and disk is ephemeral: download the assets .zip after each run.
- Keep the browser tab open during a run (multi-minute; Veo polling). One run at a time (concurrency_limit=1).
- Credits: ViMax by HKUDS, MIT License (LICENSE kept).
