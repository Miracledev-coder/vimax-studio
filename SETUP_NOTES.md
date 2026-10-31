
## Render deployment (free tier)
- URL: https://vimax-studio.onrender.com  (Gradio login; users from APP_USERS)
- Service id: srv-dbipbj2jnfac73b8m6qg, owner tea-dbip9bjbc2fs73ausneg (team "Calm craze"), region frankfurt, plan free, docker runtime
- Repo: https://github.com/Miracledev-coder/vimax-studio (public, branch main, auto-deploy on push). USERS_PRIVATE.txt is NOT committed.
- Idle memory ~206 MB of 512 MB. Free instances sleep after ~15 min idle (first request ~1 min cold start). Heavy generation may OOM.
- Change users: edit USERS_PRIVATE.txt, rebuild APP_USERS (user:pass,user:pass) and set via dashboard Environment tab or
  `PUT https://api.render.com/v1/services/srv-dbipbj2jnfac73b8m6qg/env-vars/APP_USERS` body {"value":"..."}; then POST /services/{id}/deploys.
- Add generation keys the same way (env-vars/<KEY_NAME>), then redeploy.

## Providers (Oct 2026 update)
- **Seedance (BytePlus ModelArk)** preset: needs `ARK_API_KEY` (+ `GEMINI_API_KEY` or `OPENROUTER_API_KEY` for the LLM). Images: `dola-seedream-5-0-flash-260915` (override `VIMAX_ARK_IMAGE_MODEL`). Video dropdown: seedance-1-0-pro-fast (default, `seedance-1-0-pro-fast-251015`, first-frame only), dreamina-seedance-2-0-fast / 2-0 / 2-5. 720p. Default preset when `ARK_API_KEY` is set.
- **Google** preset: LLM `gemini-3.5-flash-lite`, image `gemini-3.1-flash-lite-image`, video `gemini-omni-1.1-flash` (Veo 3.1 previews shut down 2026-10-22). 4s 720p clips. Needs a **paid** Gemini tier (free tier has 0 image/video quota).
- Cost hints: Seedance 1.0 Pro Fast ~$0.10/5s@720p; Omni Flash ~$0.10/s; Seedance 2.0 ~$0.76/5s@720p; Seedance 2.5 ~$2.84/5s@1080p.
- google-genai>=2.19 requires pydantic>=2.12.5, so Gradio was bumped to 6.x.
