# Visko-LA — Synthetic Aerial World & Telemetry Platform

![Model: reactor/visko-orbis-stable](https://img.shields.io/badge/World_Model-reactor%2Fvisko--orbis--stable-0284C7)
![Backend: FastAPI + Python 3.11+](https://img.shields.io/badge/Backend-FastAPI_%7C_Python_3.11%2B-0F172A)
![Frontend: Next.js 14 + TypeScript](https://img.shields.io/badge/Frontend-Next.js_14_%7C_TypeScript-1A73E8)
![Cloud: GCS + BigQuery](https://img.shields.io/badge/Cloud-GCS_%2B_BigQuery-10B981)
![Tests: 93/93 Passing](https://img.shields.io/badge/Tests-93%2F93_Passing-10B981)

**Visko-LA** is a synthetic aerial video and flight-telemetry generation platform built for autonomous UAV, drone, and eVTOL perception engineers. It couples **Reactor's real-time WebRTC API** and **Visko's Orbis Stable live world model (`reactor/visko-orbis-stable`)** with an International Standard Atmosphere (ISA) + Dryden turbulence physics engine, archiving fixed-interval (`5s`, `10s`, `15s`) H.264 `.mp4` perception clips to **Google Cloud Storage (GCS)** and indexing 27-column flight & atmospheric metadata records in **Google BigQuery**.

Out of the box, Visko-LA supports **dual-mode execution**: run in **Full Production Cloud Mode** against live Reactor GPUs, GCS, and BigQuery, or launch in **Zero-Credential Simulator Mode** (`ORBIS_MOCK_MODE=true`, `GCP_MOCK_MODE=true`) using a deterministic HTML5 `<canvas>` drone-POV simulator, local GCS filesystem mirror, and embedded SQLite catalog.

---

## Key Capabilities

- **Live Drone-POV Aerial Studio (`/studio`):** Stream 18 fps forward-and-downward UAV perception video over WebRTC (`33-frame` / `1.833s` chunks with Chunk 0 priming) or deterministic mock flight simulation, paired with a toggleable **8 Hz Flight Telemetry HUD** (`m/s` wind & gusts, `hPa` ISA barometric pressure, `kg/m³` air density, `°C` temperature, `EDR` turbulence severity, and UAV attitude).
- **UAV Gimbal & Prompt Discipline (`AerialSystemPromptCompiler`):** Enforces three stabilized UAV camera rigs (`forward_downward_oblique` `-35°`, `nadir_downward` `-90°`, `forward_fpv` `-15°`) with `passthrough=True`, automatic negation-to-positive physical rewrites, and mid-stream chunk-boundary chat steering without resetting the world.
- **16:9 (`832x480`) Seed Media & Dubai Aerial Presets:** Seed worlds from curated **Hugging Face Dubai Aerial Imagery (`ayoubkirouane/Dubai_dataset-Aerial_Imagery_256x256`)** tiles (`256x256 -> 256x144` center-crop + Lanczos `832x480` upscale) or upload custom `.png`, `.jpg`, `.webp`, `.mp4`, and `.webm` terrain media with strict sequential Orbis conditioning (`reset -> upload_file -> set_image -> set_prompt -> start`).
- **Fixed-Interval MP4 Capture (`5s`, `10s`, `15s`):** Strictly validated interval recording with lossless FFmpeg MPEG-TS to `+faststart` H.264 `.mp4` remuxing, immediate GCS archival, and windowed telemetry aggregation into 27 BigQuery columns.
- **Google Drive-Style Dataset Explorer (`/drive`):** Organize perception clips across projects and nested folders, filter by duration/ecosystem/turbulence EDR, inspect BigQuery metadata and prompt timelines, move clips across folders, upload external `.mp4` clips, download `.mp4` files with HTTP byte-range support, or recycle clips back into `/studio` as seeds.

---

## 60-Second Quickstart (Zero-Credential Local Simulator)

> **Prerequisites:** Node.js 20+, [`uv`](https://docs.astral.sh/uv/) (provisioning Python 3.11 or 3.13), and `ffmpeg`.

```bash
# 1. Configure local simulator environment
cp .env.example .env

# 2. Create Python 3.11 virtualenv & install FastAPI backend dependencies
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt

# 3. Start the FastAPI backend on http://localhost:8000 (Terminal 1)
ORBIS_MOCK_MODE=true GCP_MOCK_MODE=true \
  .venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload

# 4. Install & start the Next.js 14 web app on http://localhost:3000 (Terminal 2)
npm --prefix frontend install
npm --prefix frontend run dev
```

Open **`http://localhost:3000/studio`** to fly and record synthetic UAV clips, and **`http://localhost:3000/drive`** to browse, inspect, organize, and download datasets.

---

## Documentation Hub

| Document | Audience | Contents |
| :--- | :--- | :--- |
| **[`GETTING_STARTED.md`](./GETTING_STARTED.md)** | ML Engineers & Operators | Prerequisites, Mode A (2-minute local simulator), Mode B (production Reactor + GCS + BigQuery setup & IAM), 4-step `/studio` & `/drive` feature walkthrough, test runner guide, and troubleshooting. |
| **[`SYSTEM_ARCHITECTURE.md`](./SYSTEM_ARCHITECTURE.md)** | Developers & AI Agents | End-to-end Mermaid topology & sequence diagrams, annotated repository map, all 23 REST operations & WebSocket protocol schemas, GCS URI templates, 7-column & 27-column BigQuery SQL DDL, `reactor-docs` MCP & `jetski.json` multi-agent architecture, and extension playbooks. |
| **[`.env.example`](./.env.example)** | Operators & DevOps | Commented configuration template covering Reactor/Orbis, GCP/GCS/BigQuery, and backend/frontend networking variables. |

---

## Technology Stack

| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Live World Model** | **Reactor Platform** (`https://api.reactor.inc`) + **Visko Orbis Stable** (`reactor/visko-orbis-stable`) | Session-scoped JWT auth (`POST /tokens`), 18 fps WebRTC streaming (`@reactor-team/js-sdk`, `reactor-sdk`), `set_image` I2V conditioning, live `set_prompt` steering, and clip capture. |
| **Backend & Physics** | **FastAPI**, **Pydantic v2**, **Pillow**, **FFmpeg** (`backend/`) | `AerialSystemPromptCompiler`, 8 Hz ISA barometric + Dryden gust telemetry over `WS /ws/orbis/stream/{session_id}`, `832x480` seed normalizer, and dual-mode storage/catalog adapters. |
| **Cloud Data Layer** | **Google Cloud Storage** & **Google BigQuery** (with local FS + **SQLite** mirror) | Canonical `gs://${GCS_BUCKET_NAME}/{seeds,datasets}/...` object archival, V4 Signed URLs + HTTP `206` byte-range streaming, `aerial_folders` (7 cols), and partitioned `aerial_datasets` (27 cols). |
| **Frontend UI** | **Next.js 14** (App Router), **React 18**, **TypeScript**, **Tailwind CSS** (`frontend/`) | SSR-safe `/studio` live perception cockpit (WebRTC + HTML5 `<canvas>` simulator, HUD, chat, recording dock) and `/drive` hierarchical dataset explorer. |
| **Verification Suite** | **Pytest**, **Vitest**, **Playwright** (`tests/`) | **93/93 automated checks** across backend unit (`67`), frontend unit (`16`), ASGI/WS integration (`8`), and real browser E2E (`2`) journeys. |

---

## Running the Automated Verification Suite (`93/93` Passing)

```bash
# Backend Unit (67) + Cross-Service Integration (8)
PYTHONPATH=backend .venv/bin/pytest tests/unit/backend tests/integration -v

# Frontend Pure Unit Suite via Vitest (16)
npm --prefix frontend run test

# End-to-End Browser Journeys via Playwright (2: /studio + /drive)
npx --prefix tests/e2e playwright test -c tests/e2e/playwright.config.ts
```

---

## License

Released under the [Apache 2.0 License](./LICENSE).
