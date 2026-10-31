
## Render deployment (free tier)
- URL: https://vimax-studio.onrender.com  (Gradio login; users from APP_USERS)
- Service id: srv-dbipbj2jnfac73b8m6qg, owner tea-dbip9bjbc2fs73ausneg (team "Calm craze"), region frankfurt, plan free, docker runtime
- Repo: https://github.com/Miracledev-coder/vimax-studio (public, branch main, auto-deploy on push). USERS_PRIVATE.txt is NOT committed.
- Idle memory ~206 MB of 512 MB. Free instances sleep after ~15 min idle (first request ~1 min cold start). Heavy generation may OOM.
- Change users: edit USERS_PRIVATE.txt, rebuild APP_USERS (user:pass,user:pass) and set via dashboard Environment tab or
  `PUT https://api.render.com/v1/services/srv-dbipbj2jnfac73b8m6qg/env-vars/APP_USERS` body {"value":"..."}; then POST /services/{id}/deploys.
- Add generation keys the same way (env-vars/<KEY_NAME>), then redeploy.
