---
title: ViMax Studio
emoji: 🎬
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 5.49.1
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: Idea or script to multi-shot AI video (ViMax)
---

# ViMax Studio

Browser front-end (Gradio) for **[HKUDS/ViMax](https://github.com/HKUDS/ViMax)** — agentic video generation
(Idea2Video and Script2Video). All heavy work happens in cloud APIs (LLM, image, video), so it runs on the free CPU tier.

Credit: ViMax by HKUDS (Data Intelligence Lab, University of Hong Kong), MIT License — see `LICENSE`.
This Space only adds `app.py` as a wrapper. API keys come from Space secrets; see `DEPLOY.md`.
