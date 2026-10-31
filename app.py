"""ViMax Studio — Gradio wrapper around HKUDS/ViMax (MIT). Keys come from env / Space secrets only."""
import asyncio, glob, logging, os, shutil, tempfile, time, uuid

import gradio as gr
from langchain.chat_models import init_chat_model

from pipelines.idea2video_pipeline import Idea2VideoPipeline
from pipelines.script2video_pipeline import Script2VideoPipeline
from tools.render_backend import RenderBackend

logging.basicConfig(level=logging.INFO)
RUNS_DIR = os.environ.get("VIMAX_RUNS_DIR", os.path.join(tempfile.gettempdir(), "vimax_runs"))
GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_URL = "https://openrouter.ai/api/v1"

PRESETS = {
    "Seedance (BytePlus ModelArk: Seedream image + Seedance video) — needs ARK_API_KEY": "seedance",
    "Google (Gemini LLM + Nano Banana image + Omni Flash video) — needs GEMINI_API_KEY": "google",
    "OpenRouter (Gemini Flash LLM + GPT Image 2 + Veo 3.1 Lite) — needs OPENROUTER_API_KEY": "openrouter",
    "Mixed (OpenRouter LLM + Google image/Omni video) — needs both keys": "mixed",
}
DEFAULT_PRESET = list(PRESETS)[0] if os.environ.get("ARK_API_KEY", "").strip() else list(PRESETS)[1]

SEEDANCE_MODEL_CHOICES = ["seedance-1-0-pro-fast", "dreamina-seedance-2-0-fast",
                          "dreamina-seedance-2-0", "dreamina-seedance-2-5"]
GEMINI_LLM = "gemini-3.5-flash-lite"   # gemini-2.5-* is restricted to legacy users
COST_HINTS = """**Approximate video cost per clip** (each shot = 1 clip; images/LLM extra, small):
- Seedance 1.0 Pro Fast — ~$0.10 per 5s clip @720p (default, cheapest)
- Seedance 2.0 — ~$0.76 per 5s @720p (2.0 Fast is cheaper, 480p/720p only)
- Seedance 2.5 — ~$2.84 per 5s @1080p
- Gemini Omni Flash — ~$0.10 per second (4s clip ≈ $0.40)

A 4-shot video ≈ 4 clips. Seedance 2.x needs a ModelArk balance >$30 to activate and rejects real human faces in reference images."""


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise gr.Error(f"Missing secret {name}. Add it in the Space Settings → Variables and secrets.")
    return v


def build_config(preset, llm_model, num_candidates, workdir, seedance_model=None):
    if preset == "seedance":
        a = _env("ARK_API_KEY")
        g = os.environ.get("GEMINI_API_KEY", "").strip()
        o = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if g:
            chat = dict(model=llm_model or GEMINI_LLM, model_provider="openai", api_key=g, base_url=GEMINI_OPENAI_URL)
        elif o:
            chat = dict(model=llm_model or "google/gemini-2.5-flash", model_provider="openai", api_key=o, base_url=OPENROUTER_URL)
        else:
            raise gr.Error("Seedance preset still needs an LLM key: set GEMINI_API_KEY or OPENROUTER_API_KEY.")
        img = {"class_path": "tools.ImageGeneratorSeedreamBytePlusAPI",
               "init_args": {"api_key": a, "model": os.environ.get("VIMAX_ARK_IMAGE_MODEL", "dola-seedream-5-0-flash-260915")}}
        vid = {"class_path": "tools.VideoGeneratorSeedanceBytePlusAPI",
               "init_args": {"api_key": a, "model": seedance_model or "seedance-1-0-pro-fast", "resolution": "720p"}}
    elif preset == "google":
        g = _env("GEMINI_API_KEY")
        chat = dict(model=llm_model or GEMINI_LLM, model_provider="openai", api_key=g, base_url=GEMINI_OPENAI_URL)
        img = {"class_path": "tools.ImageGeneratorNanobananaGoogleAPI", "init_args": {"api_key": g}}
        vid = {"class_path": "tools.VideoGeneratorOmniGoogleAPI", "init_args": {"api_key": g, "resolution": "720p", "duration": 4}}
    elif preset == "openrouter":
        o = _env("OPENROUTER_API_KEY")
        chat = dict(model=llm_model or "google/gemini-2.5-flash", model_provider="openai", api_key=o, base_url=OPENROUTER_URL)
        img = {"class_path": "tools.ImageGeneratorOpenRouterAPI",
               "init_args": {"api_key": o, "model": os.environ.get("VIMAX_OR_IMAGE_MODEL", "openai/gpt-image-2")}}
        vid = {"class_path": "tools.VideoGeneratorOpenRouterAPI",
               "init_args": {"api_key": o, "model": os.environ.get("VIMAX_OR_VIDEO_MODEL", "google/veo-3.1-lite")}}
    else:
        o, g = _env("OPENROUTER_API_KEY"), _env("GEMINI_API_KEY")
        chat = dict(model=llm_model or "google/gemini-2.5-flash", model_provider="openai", api_key=o, base_url=OPENROUTER_URL)
        img = {"class_path": "tools.ImageGeneratorNanobananaGoogleAPI", "init_args": {"api_key": g}}
        vid = {"class_path": "tools.VideoGeneratorOmniGoogleAPI", "init_args": {"api_key": g, "resolution": "720p", "duration": 4}}
    img.update(max_requests_per_minute=10, max_requests_per_day=500)
    vid.update(max_requests_per_minute=2, max_requests_per_day=50)
    return chat, {"image_generator": img, "video_generator": vid,
                  "image_selection": {"num_candidates": int(num_candidates)}, "working_dir": workdir}


def collect(workdir):
    imgs = sorted(p for ext in ("png", "jpg", "jpeg", "webp")
                  for p in glob.glob(os.path.join(workdir, "**", f"*.{ext}"), recursive=True))
    zip_path = shutil.make_archive(workdir, "zip", workdir) if os.path.isdir(workdir) else None
    return imgs[:200], zip_path


async def run(mode, text, requirement, style, preset_label, llm_model, num_candidates, seedance_model):
    if not text or not text.strip():
        raise gr.Error("Please enter an idea or a script.")
    preset = PRESETS[preset_label]
    workdir = os.path.join(RUNS_DIR, time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    os.makedirs(workdir, exist_ok=True)
    chat_args, cfg = build_config(preset, llm_model.strip(), num_candidates, workdir, seedance_model)
    chat_model = init_chat_model(**chat_args)
    backend = RenderBackend.from_config(cfg)
    log = []

    def progress(stage, message, data=None):
        log.append(f"[{time.strftime('%H:%M:%S')}] {stage}: {message}")

    common = dict(chat_model=chat_model, image_generator=backend.image_generator,
                  video_generator=backend.video_generator, working_dir=workdir,
                  num_image_candidates=int(num_candidates))
    if mode == "Idea → Video":
        task = Idea2VideoPipeline(**common)(idea=text, user_requirement=requirement, style=style, progress=progress)
    else:
        task = Script2VideoPipeline(**common)(script=text, user_requirement=requirement, style=style, progress=progress)
    fut = asyncio.ensure_future(task)
    while not fut.done():
        await asyncio.sleep(5)
        yield None, None, None, "\n".join(log[-60:]) or "Working… (planning story/script with the LLM)"
    try:
        video = fut.result()
    except Exception as e:  # surface errors in the log box, keep partial assets
        logging.exception("pipeline failed")
        imgs, zip_path = collect(workdir)
        yield None, imgs, zip_path, "\n".join(log[-60:]) + f"\n\n❌ ERROR: {type(e).__name__}: {e}"
        return
    imgs, zip_path = collect(workdir)
    yield video, imgs, zip_path, "\n".join(log[-60:]) + f"\n\n✅ Done: {video}"


with gr.Blocks(title="ViMax Studio") as demo:
    gr.Markdown("# 🎬 ViMax Studio\nIdea or screenplay → storyboard → consistent multi-shot video. "
                "Powered by [HKUDS/ViMax](https://github.com/HKUDS/ViMax) (MIT). "
                "⚠️ Each run calls paid image/video APIs; keep scenes/shots small.")
    with gr.Row():
        with gr.Column():
            mode = gr.Radio(["Idea → Video", "Script → Video"], value="Idea → Video", label="Mode")
            text = gr.Textbox(lines=10, label="Idea or screenplay")
            requirement = gr.Textbox(lines=2, value="No more than 1 scene and 4 shots. Vertical-friendly UGC style.",
                                     label="Requirements (length, scenes, shots, audience)")
            style = gr.Textbox(value="Realistic, warm feel", label="Visual style")
            with gr.Accordion("Providers & advanced", open=False):
                preset = gr.Dropdown(list(PRESETS), value=DEFAULT_PRESET, label="Provider preset")
                seedance_model = gr.Dropdown(SEEDANCE_MODEL_CHOICES, value="seedance-1-0-pro-fast",
                                             label="Seedance video model (Seedance preset only, 720p)")
                gr.Markdown(COST_HINTS)
                llm_model = gr.Textbox(value="", label="LLM model override (blank = preset default)")
                num_candidates = gr.Slider(1, 4, value=1, step=1,
                                           label="Image candidates per keyframe (1 = cheapest, >1 uses vision LLM to pick best)")
            btn = gr.Button("Generate video", variant="primary")
        with gr.Column():
            video = gr.Video(label="Final video")
            gallery = gr.Gallery(label="Intermediate images (portraits, frames)", columns=4, height=300)
            zipf = gr.File(label="All assets (scripts, storyboard JSON, images, clips) as .zip")
            logs = gr.Textbox(lines=14, label="Progress log")
    btn.click(run, [mode, text, requirement, style, preset, llm_model, num_candidates, seedance_model],
              [video, gallery, zipf, logs], concurrency_limit=1)

def load_users():
    """Up to 5 users from APP_USERS='u1:p1,u2:p2'; fallback APP_USERNAME/APP_PASSWORD."""
    users = []
    for item in os.environ.get("APP_USERS", "").split(","):
        item = item.strip()
        if ":" in item:
            u, p = item.split(":", 1)
            if u.strip() and p:
                users.append((u.strip(), p))
    if not users:
        pw = os.environ.get("APP_PASSWORD", "").strip()
        if pw:
            users.append((os.environ.get("APP_USERNAME", "miracle"), pw))
    return users[:5]


if __name__ == "__main__":
    users = load_users()
    port = int(os.environ.get("PORT", 7860))
    if not users:
        logging.error("No APP_USERS / APP_PASSWORD set: serving locked page only.")
        with gr.Blocks(title="ViMax Studio (locked)") as locked:
            gr.Markdown("# 🔒 ViMax Studio is locked\nThe owner must set the `APP_USERS` secret "
                        "(or `APP_PASSWORD`) in the Space settings.")
        locked.launch(server_name="0.0.0.0", server_port=port)
    else:
        demo.queue().launch(server_name="0.0.0.0", server_port=port, auth=users,
                            allowed_paths=[RUNS_DIR])
