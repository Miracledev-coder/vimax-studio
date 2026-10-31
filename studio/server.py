"""ViMax Studio: Calm Craze Creatives front end for HKUDS/ViMax (MIT).
Same shell/theme as MoneyPrinter Studio. Keys come from env only; one job at a time."""
import asyncio, glob, hashlib, hmac, json, logging, os, secrets, shutil, sys, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GEMINI_LLM = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
OUT_DIR = Path(os.environ.get("VIMAX_RUNS_DIR", "/tmp/vimax_runs")); OUT_DIR.mkdir(parents=True, exist_ok=True)
KEEP = 8


def _k(n):
    return os.environ.get(n, "").strip()


# Friendly model catalogue. "paid" models need billing; Gemini free tier allows 0 video requests,
# so Omni stays "not available yet" until VIMAX_GEMINI_VIDEO=1 is set after enabling billing.
MODELS = {
    "seedance-fast": dict(label="Seedance 1.0 Fast", note="BytePlus · ~$0.10 / 5s clip", kind="seedance",
                          model="seedance-1-0-pro-fast", res=["480p", "720p", "1080p"], dur=[5, 10]),
    "seedance-2-fast": dict(label="Seedance 2.0 Fast", note="BytePlus · cheaper 2.0", kind="seedance",
                            model="dreamina-seedance-2-0-fast", res=["480p", "720p"], dur=[5, 10]),
    "seedance-2": dict(label="Seedance 2.0", note="BytePlus · ~$0.76 / 5s clip", kind="seedance",
                       model="dreamina-seedance-2-0", res=["480p", "720p", "1080p"], dur=[5, 10]),
    "seedance-2-5": dict(label="Seedance 2.5", note="BytePlus · ~$2.84 / 5s clip", kind="seedance",
                         model="dreamina-seedance-2-5", res=["720p", "1080p"], dur=[5, 10]),
    "omni-flash": dict(label="Omni Flash", note="Google Gemini · ~$0.10 / second", kind="google",
                       model="gemini-omni-1.1-flash", res=["720p", "1080p"], dur=[4, 6, 8]),
    "veo-lite": dict(label="Veo 3.1 Lite", note="via OpenRouter", kind="openrouter",
                     model=os.environ.get("VIMAX_OR_VIDEO_MODEL", "google/veo-3.1-lite"), res=["720p"], dur=[4, 8]),
}


def availability(kind):
    """Return None if usable, else a friendly reason. Never reveals key values."""
    llm = _k("GEMINI_API_KEY") or _k("OPENROUTER_API_KEY")
    if kind == "seedance":
        if not _k("ARK_API_KEY"):
            return "Not available yet — the BytePlus ModelArk key (ARK_API_KEY) hasn't been added."
        if not llm:
            return "Not available yet — needs a Gemini or OpenRouter key for story planning."
    elif kind == "google":
        if not _k("GEMINI_API_KEY"):
            return "Not available yet — the Gemini key hasn't been added."
        if _k("VIMAX_GEMINI_VIDEO") != "1":
            return "Not available yet — Gemini's free tier doesn't include video. Enable billing, then set VIMAX_GEMINI_VIDEO=1."
    elif kind == "openrouter" and not _k("OPENROUTER_API_KEY"):
        return "Not available yet — the OpenRouter key hasn't been added."
    return None


def build(mid, aspect, res, dur, workdir, candidates):
    m = MODELS[mid]; g, o, a = _k("GEMINI_API_KEY"), _k("OPENROUTER_API_KEY"), _k("ARK_API_KEY")
    chat = (dict(model=GEMINI_LLM, model_provider="openai", api_key=g, base_url=GEMINI_OPENAI_URL) if g else
            dict(model="google/gemini-2.5-flash", model_provider="openai", api_key=o, base_url=OPENROUTER_URL))
    if m["kind"] == "seedance":
        img = {"class_path": "tools.ImageGeneratorSeedreamBytePlusAPI",
               "init_args": {"api_key": a, "model": _k("VIMAX_ARK_IMAGE_MODEL") or "dola-seedream-5-0-flash-260915"}}
        vid = {"class_path": "tools.VideoGeneratorSeedanceBytePlusAPI",
               "init_args": {"api_key": a, "model": m["model"], "resolution": res, "ratio": aspect, "duration": dur}}
    elif m["kind"] == "google":
        img = {"class_path": "tools.ImageGeneratorNanobananaGoogleAPI", "init_args": {"api_key": g}}
        vid = {"class_path": "tools.VideoGeneratorOmniGoogleAPI",
               "init_args": {"api_key": g, "model": m["model"], "resolution": res, "aspect_ratio": aspect, "duration": dur}}
    else:
        img = {"class_path": "tools.ImageGeneratorOpenRouterAPI",
               "init_args": {"api_key": o, "model": _k("VIMAX_OR_IMAGE_MODEL") or "openai/gpt-image-2"}}
        vid = {"class_path": "tools.VideoGeneratorOpenRouterAPI", "init_args": {"api_key": o, "model": m["model"]}}
    img.update(max_requests_per_minute=10, max_requests_per_day=500)
    vid.update(max_requests_per_minute=2, max_requests_per_day=50)
    return chat, {"image_generator": img, "video_generator": vid,
                  "image_selection": {"num_candidates": int(candidates)}, "working_dir": workdir}


def load_users():
    users = {}
    for item in os.environ.get("APP_USERS", "").replace("\n", ",").split(","):
        item = item.strip()
        if item and not item.startswith("#") and ":" in item:
            u, p = item.split(":", 1)
            if u.strip() and p and " " not in u.strip():
                users[u.strip()] = p
    if not users and _k("APP_PASSWORD"):
        users[os.environ.get("APP_USERNAME", "miracle")] = _k("APP_PASSWORD")
    return dict(list(users.items())[:5])


USERS = load_users()
SECRET = (os.environ.get("SESSION_SECRET") or secrets.token_hex(32)).encode()
jobs, lock = {}, threading.Lock()
HIST = OUT_DIR / "history.json"
META = ("status", "user", "title", "aspect", "model", "created", "elapsed", "error", "video", "zip", "stage")
try:
    for k, v in json.loads(HIST.read_text()).items():
        if v.get("status") == "error" or Path(v.get("video") or "").exists():
            jobs[k] = v
except Exception:
    pass


def save_history():
    HIST.write_text(json.dumps({k: {m: v.get(m) for m in META} for k, v in jobs.items()
                                if v.get("status") in ("done", "error")}))


def sign(u):
    return u + "|" + hmac.new(SECRET, u.encode(), hashlib.sha256).hexdigest()


def current_user(req):
    c = req.cookies.get("vms", ""); u = c.split("|", 1)[0]
    return u if u in USERS and hmac.compare_digest(c, sign(u)) else None


def run_job(jid):
    j = jobs[jid]; j.update(status="running", started=time.time(), stage="Planning the story")
    workdir = str(OUT_DIR / jid)
    try:
        from langchain.chat_models import init_chat_model
        from pipelines.idea2video_pipeline import Idea2VideoPipeline
        from pipelines.script2video_pipeline import Script2VideoPipeline
        from tools.render_backend import RenderBackend
        p = j.pop("params")
        chat_args, cfg = build(p["model"], p["aspect"], p["res"], p["dur"], workdir, p["candidates"])
        backend = RenderBackend.from_config(cfg)
        common = dict(chat_model=init_chat_model(**chat_args), image_generator=backend.image_generator,
                      video_generator=backend.video_generator, working_dir=workdir,
                      num_image_candidates=int(p["candidates"]))

        def progress(stage, message, data=None):
            j["stage"] = str(message)[:120]
        if p["mode"] == "script":
            task = Script2VideoPipeline(**common)(script=p["text"], user_requirement=p["req"], style=p["style"], progress=progress)
        else:
            task = Idea2VideoPipeline(**common)(idea=p["text"], user_requirement=p["req"], style=p["style"], progress=progress)
        video = asyncio.run(task)
        j.update(status="done", video=str(video))
    except Exception as e:  # noqa: BLE001
        logging.exception("pipeline failed")
        j.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
    finally:
        j["elapsed"] = round(time.time() - j["started"])
        if os.path.isdir(workdir):
            j["zip"] = shutil.make_archive(workdir, "zip", workdir)
        done = sorted((k for k, v in jobs.items() if v.get("status") in ("done", "error")), key=lambda k: jobs[k]["created"])
        for k in done[:-KEEP]:
            shutil.rmtree(OUT_DIR / k, ignore_errors=True); Path(str(OUT_DIR / k) + ".zip").unlink(missing_ok=True)
            jobs.pop(k, None)
        save_history()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
HERE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
PAGE = ((HERE / "index.html").read_text()
        .replace("{{SHELL}}", (HERE / "static/cc-shell.html").read_text())
        .replace("{{HEADER}}", (HERE / "static/cc-header.html").read_text())
        .replace("{{APP}}", "ViMax Studio"))
LOGIN = (HERE / "login.html").read_text()
LOCKED = ("<link rel=stylesheet href='/static/cc-theme.css'><div class=cc-login style='text-align:center'>"
          "<img src='/static/logo-white.svg'><h1>🔒 ViMax Studio is locked</h1><p style='color:#8a84a3'>"
          "The owner must set APP_USERS.</p></div>")


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    if not USERS:
        return HTMLResponse(LOCKED, 503)
    u = current_user(req)
    if not u:
        return HTMLResponse(LOGIN.replace("{{ERR}}", ""))
    return HTMLResponse(PAGE.replace("{{USER}}", u))


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    p = USERS.get(username.strip())
    if not p or not hmac.compare_digest(p, password):
        time.sleep(1)
        return HTMLResponse(LOGIN.replace("{{ERR}}", "Wrong username or password."), 401)
    r = RedirectResponse("/", 303)
    r.set_cookie("vms", sign(username.strip()), httponly=True, samesite="lax", max_age=7 * 86400,
                 secure=os.environ.get("RENDER") is not None)
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/", 303); r.delete_cookie("vms"); return r


@app.get("/api/models")
def models(req: Request):
    if not current_user(req):
        return JSONResponse({"error": "not logged in"}, 401)
    return [dict(id=k, label=m["label"], note=m["note"], res=m["res"], dur=m["dur"],
                 unavailable=availability(m["kind"])) for k, m in MODELS.items()]


@app.post("/api/generate")
async def generate(req: Request):
    user = current_user(req)
    if not user:
        return JSONResponse({"error": "Please sign in again."}, 401)
    b = await req.json()
    text = (b.get("text") or "").strip()[:6000]
    if not text:
        return JSONResponse({"error": "Describe your idea or paste a script first."}, 400)
    mid = b.get("model")
    if mid not in MODELS:
        return JSONResponse({"error": "Pick a model."}, 400)
    m = MODELS[mid]
    why = availability(m["kind"])
    if why:
        return JSONResponse({"error": f"{m['label']} is {why[0].lower()}{why[1:]}", "unavailable": True}, 409)
    aspect = b.get("aspect") if b.get("aspect") in ("16:9", "9:16", "1:1") else "16:9"
    res = b.get("res") if b.get("res") in m["res"] else m["res"][0]
    dur = int(b.get("dur")) if str(b.get("dur")).isdigit() and int(b.get("dur")) in m["dur"] else m["dur"][0]
    shots = max(1, min(int(b.get("shots") or 4), 8))
    if any(j["status"] in ("queued", "running") for j in jobs.values()):
        return JSONResponse({"error": "A video is already being made. Please wait for it to finish."}, 429)
    req_txt = (b.get("requirement") or "").strip()[:500] or f"No more than 1 scene and {shots} shots."
    jid = uuid.uuid4().hex[:12]
    jobs[jid] = dict(status="queued", user=user, created=time.time(), title=text[:90], aspect=aspect,
                     model=f"{m['label']} · {res} · {dur}s", stage="Queued",
                     params=dict(mode="script" if b.get("mode") == "script" else "idea", text=text, req=req_txt,
                                 style=(b.get("style") or "Realistic, warm feel")[:200], model=mid, aspect=aspect,
                                 res=res, dur=dur, candidates=max(1, min(int(b.get("candidates") or 1), 4))))
    threading.Thread(target=run_job, args=(jid,), daemon=True).start()
    return {"id": jid}


@app.get("/api/history")
def history(req: Request):
    u = current_user(req)
    if not u:
        return JSONResponse({"error": "not logged in"}, 401)
    out = []
    for k, j in sorted(jobs.items(), key=lambda kv: -kv[1]["created"]):
        if j.get("user") == u:
            d = {m: j.get(m) for m in ("status", "title", "aspect", "model", "elapsed", "error", "stage")}
            d.update(id=k, has_zip=bool(j.get("zip")))
            if j["status"] == "running":
                d["elapsed"] = round(time.time() - j["started"])
            out.append(d)
    return out[:30]


@app.get("/video/{jid}")
def video(jid: str, req: Request, dl: int = 0):
    j = jobs.get(jid)
    if not j or current_user(req) != j.get("user") or not Path(j.get("video") or "").exists():
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(j["video"], media_type="video/mp4", filename=f"vimax-{jid[:8]}.mp4" if dl else None)


@app.get("/assets/{jid}")
def assets(jid: str, req: Request):
    j = jobs.get(jid)
    if not j or current_user(req) != j.get("user") or not Path(j.get("zip") or "").exists():
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(j["zip"], media_type="application/zip", filename=f"vimax-assets-{jid[:8]}.zip")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)), log_level="info")
