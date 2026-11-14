# Getting Started with Visko-LA

This guide walks ML perception engineers, autonomous-flight researchers, and simulation operators from a clean checkout through launching **Visko-LA**, seeding real-world aerial terrain, steering live Drone-POV video and atmospheric physics, capturing fixed-interval `.mp4` training clips to **Google Cloud Storage** and **BigQuery**, and running the **93-test automated verification suite**.

---

## 1. Platform Overview

Training autonomous UAV, quadcopter, and eVTOL perception models requires diverse forward-and-downward optical footage paired with ground-truth atmospheric and flight-attitude state—especially in edge-case wind shear, mountain rotor turbulence, fog, and coastal crosswinds where real flights are hazardous or expensive.

**Visko-LA** unifies four subsystems into an end-to-end synthetic dataset workbench:

1. **Live Aerial World Generation (`reactor/visko-orbis-stable`):** Connects to the **Reactor Platform API** (`https://api.reactor.inc`) using short-lived, session-scoped JWTs (`POST /api/v1/auth/reactor-token`) to stream 18 fps `main_video` WebRTC video (`33-frame` / `~1.833s` chunks). The backend's **`AerialSystemPromptCompiler`** enforces UAV gimbal framing (`forward_downward_oblique` `-35°`, `nadir_downward` `-90°`, `forward_fpv` `-15°`) with `passthrough=True` so Reactor's generic story preprocessor preserves optical sensor geometry.
2. **Coupled ISA & Dryden Atmospheric Physics (`WS /ws/orbis/stream/{session_id}`):** Because `reactor/visko-orbis-stable` emits video/audio tracks and chunk events rather than meteorological packets, a deterministic **Session Telemetry Engine** (`8 Hz` WebSocket ticks) computes International Standard Atmosphere (ISA) barometric pressure (`hPa`), air density (`kg/m³`), and ambient temperature (`°C`) from ecosystem elevation + UAV AGL altitude, modulated by Dryden/Perlin wind gusts (`m/s`), Eddy Dissipation Rate (`turbulence_edr`), and live chat weather directives.
3. **Fixed-Interval MP4 Capture (`5s`, `10s`, `15s`) & Cloud Archival:** Captures strictly validated `5`, `10`, or `15` second intervals, losslessly remuxes Reactor MPEG-TS (`.ts`) clips into web-playable `+faststart` H.264 `.mp4` files via `ffmpeg`, uploads blobs to **Google Cloud Storage** (`gs://${GCS_BUCKET_NAME}/datasets/...`), and inserts a **27-column** record with windowed telemetry aggregates into **Google BigQuery** (`aerial_datasets`).
4. **Dual-Mode Execution (Live Cloud vs. Zero-Credential Simulator):** Each adapter layer (`ReactorOrbisAdapter`, `StorageBucketAdapter`, `MetadataCatalogAdapter`) automatically selects **Live Cloud Mode** when valid credentials are configured, or falls back cleanly to **Deterministic Local Simulator Mode** (`ORBIS_MOCK_MODE=true`, `GCP_MOCK_MODE=true`) backed by an interactive HTML5 `<canvas>` drone-POV simulator, local GCS filesystem mirror (`./backend/.local_storage/gcs/`), and embedded SQLite BigQuery mirror (`./backend/.local_storage/bq_catalog.db`).

---

## 2. Prerequisites

| Tool / Credential | Version / Format | Purpose & Installation |
| :--- | :--- | :--- |
| **Node.js & npm** | `>= 20.x` | Runs the Next.js 14 web app (`frontend/`), Vitest unit suite, and Playwright E2E runner (`brew install node`). |
| **Python via `uv`** | **Python `3.11` or `3.13`** | Runs the FastAPI backend (`backend/`) and Pytest suites. Install `uv` (`brew install uv`), then create `.venv` explicitly with `--python 3.11` or `--python 3.13` *(avoid macOS Homebrew Python 3.15, which lacks prebuilt wheels for C/Rust extensions)*. |
| **`ffmpeg`** | `>= 6.x` | Lossless MPEG-TS (`.ts`) to `+faststart` `.mp4` remuxing, mock H.264 `.mp4` synthesis, and `.mp4`/`.webm` video seed keyframe extraction (`brew install ffmpeg` on macOS or `sudo apt-get install -y ffmpeg` on Ubuntu/Debian). |
| **Google Cloud SDK** | `gcloud` + `bq` CLIs | *Required for Mode B (Cloud) only.* Authenticates ADC, provisions the GCS bucket, and runs BigQuery DDL (`brew install --cask google-cloud-sdk`). |
| **Reactor API Key** | `rk_...` | *Required for Mode B (Cloud) only.* Create a server-side key at `https://reactor.inc/dashboard`. Never expose `REACTOR_API_KEY` in browser `NEXT_PUBLIC_*` variables. |

Verify your local toolchain from the repository root:

```bash
node --version
uv --version
ffmpeg -version | head -n 1
```

---

## 3. Quickstart Mode A — Zero-Credential Local Simulator (2 Minutes)

Mode A requires **zero API keys and zero cloud accounts**. You can explore `/studio` and `/drive`, upload or pick Dubai `256x256` starter seeds, steer weather physics over live WebSockets, record playable H.264 `.mp4` clips, organize folders, and download datasets locally.

### 3.1 Configure `.env` for Simulator Mode

```bash
cp .env.example .env
```

Update `ORBIS_MOCK_MODE` and `GCP_MOCK_MODE` in `.env` (or pass them inline on startup):

```bash
# Enable deterministic offline Orbis flight simulator + local GCS/SQLite mirrors
sed -i.bak 's/^ORBIS_MOCK_MODE=.*/ORBIS_MOCK_MODE=true/' .env
sed -i.bak 's/^GCP_MOCK_MODE=.*/GCP_MOCK_MODE=true/' .env
rm -f .env.bak
```

### 3.2 Install & Launch the FastAPI Backend (Terminal 1)

```bash
# Provision Python 3.11 virtualenv via uv and install backend dependencies
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt

# Load .env and start FastAPI on http://localhost:8000
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --app-dir backend --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT:-8000}" --reload
```

Verify backend readiness in another shell:

```bash
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

Expected response:

```json
{
  "status": "ok",
  "service": "visko-la-backend",
  "mode": "mock",
  "orbis_mode": "mock",
  "gcp_mode": "mock",
  "model_id": "reactor/visko-orbis-stable",
  "gcp_project_id": "visko-local-dev",
  "gcs_bucket_name": "visko-orbis-aerial-datasets",
  "gcs_bucket": "visko-orbis-aerial-datasets",
  "bq_dataset_id": "visko_aerial_telemetry"
}
```

### 3.3 Install & Launch the Next.js Frontend (Terminal 2)

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open your browser to:
- **Live Aerial Studio:** `http://localhost:3000/studio` (`http://localhost:3000/` redirects automatically to `/studio`)
- **Dataset Drive Explorer:** `http://localhost:3000/drive`

---

## 4. Quickstart Mode B — Full Production Cloud Setup (Reactor + GCS + BigQuery)

Mode B connects the platform to live **Reactor Platform** GPU sessions (`reactor/visko-orbis-stable`), a real **Google Cloud Storage** bucket (`gs://$GCS_BUCKET_NAME`), and **Google BigQuery** tables (`aerial_folders` and `aerial_datasets`).

### 4.1 Authenticate with Google Cloud & Configure IAM Roles

```bash
export GCP_PROJECT_ID="your-gcp-project-id"
export GCP_REGION="us-central1"
export GCS_BUCKET_NAME="visko-orbis-aerial-datasets"
export BQ_DATASET_ID="visko_aerial_telemetry"
export SA_NAME="visko-la-backend-sa"
export SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

gcloud auth login
gcloud config set project "${GCP_PROJECT_ID}"
gcloud auth application-default login

# Enable Cloud Storage, BigQuery, and IAM Credentials APIs
gcloud services enable storage.googleapis.com bigquery.googleapis.com iamcredentials.googleapis.com
```

Create a dedicated backend Service Account (recommended so `GCSStorageAdapter` can sign V4 download URLs directly) and grant the **4 mandatory IAM roles**:

- `roles/storage.objectAdmin` — Read/write seed media (`seeds/`) and `.mp4` dataset clips (`datasets/`) in GCS.
- `roles/iam.serviceAccountTokenCreator` — Mint GCS **V4 Signed URLs** (`GET /api/v1/datasets/{video_id}/download`).
- `roles/bigquery.dataEditor` — Insert/update rows in `aerial_folders` and `aerial_datasets`.
- `roles/bigquery.jobUser` — Execute parameterized BigQuery SQL queries and catalog bootstrap DDL.

```bash
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Visko-LA Synthetic Aerial Platform Backend"

for ROLE in \
  roles/storage.objectAdmin \
  roles/iam.serviceAccountTokenCreator \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}"
done

mkdir -p ~/.gcp
gcloud iam service-accounts keys create ~/.gcp/visko-la-sa.json \
  --iam-account="${SA_EMAIL}"
```

### 4.2 Create the GCS Bucket & BigQuery Dataset + Tables

```bash
# 1. Create the Cloud Storage bucket
gcloud storage buckets create "gs://${GCS_BUCKET_NAME}" \
  --project="${GCP_PROJECT_ID}" \
  --location="${GCP_REGION}" \
  --uniform-bucket-level-access

# 2. Create the BigQuery dataset
bq --location="${GCP_REGION}" mk --dataset \
  --description="Visko-LA UAV Synthetic Aerial Dataset & Telemetry Catalog" \
  "${GCP_PROJECT_ID}:${BQ_DATASET_ID}"
```

Provision the canonical **7-column `aerial_folders`** and **27-column `aerial_datasets`** tables via `bq query --use_legacy_sql=false`:

```bash
bq query --project_id="${GCP_PROJECT_ID}" --location="${GCP_REGION}" --use_legacy_sql=false <<SQL
CREATE TABLE IF NOT EXISTS \`${GCP_PROJECT_ID}.${BQ_DATASET_ID}.aerial_folders\` (
  folder_id STRING NOT NULL OPTIONS(description="Primary folder identifier"),
  project_id STRING NOT NULL OPTIONS(description="Owning project identifier"),
  parent_folder_id STRING OPTIONS(description="Parent folder_id; NULL for root/top-level folders"),
  name STRING NOT NULL OPTIONS(description="Human-readable folder name"),
  folder_path STRING NOT NULL OPTIONS(description="Normalized slash-prefixed path"),
  ecosystem_default STRING OPTIONS(description="Optional default ecosystem_type slug"),
  created_at TIMESTAMP NOT NULL OPTIONS(description="UTC creation timestamp (ISO-8601)")
)
CLUSTER BY project_id, parent_folder_id;

CREATE TABLE IF NOT EXISTS \`${GCP_PROJECT_ID}.${BQ_DATASET_ID}.aerial_datasets\` (
  video_id STRING NOT NULL OPTIONS(description="Primary dataset clip UUID/slug"),
  project_id STRING NOT NULL OPTIONS(description="Owning project identifier"),
  folder_id STRING NOT NULL OPTIONS(description="Target folder_id within the project"),
  folder_path STRING NOT NULL OPTIONS(description="Normalized target folder_path"),
  title STRING NOT NULL OPTIONS(description="Human-readable dataset clip title"),
  session_id STRING NOT NULL OPTIONS(description="Originating studio session_id"),
  model_id STRING NOT NULL OPTIONS(description="Canonical Reactor world model slug ('reactor/visko-orbis-stable')"),
  ecosystem_type STRING NOT NULL OPTIONS(description="Canonical snake_case ecosystem slug"),
  duration_seconds INT64 NOT NULL OPTIONS(description="Fixed clip duration in seconds (strictly 5, 10, or 15)"),
  resolution STRING NOT NULL OPTIONS(description="Output video resolution"),
  fps INT64 NOT NULL OPTIONS(description="Frames per second (18 for native Visko Orbis Stable)"),
  gcs_video_uri STRING NOT NULL OPTIONS(description="Canonical GCS MP4 URI"),
  seed_media_gcs_uri STRING OPTIONS(description="Optional GCS URI of conditioning seed image/video"),
  initial_prompt STRING NOT NULL OPTIONS(description="Opening UAV Drone-POV prompt or upload description"),
  prompt_history_json STRING NOT NULL OPTIONS(description="JSON array string of PromptEntry records"),
  avg_wind_speed_mps FLOAT64 NOT NULL OPTIONS(description="Mean sustained wind speed over capture window (m/s)"),
  max_wind_gust_mps FLOAT64 NOT NULL OPTIONS(description="Peak wind gust speed over capture window (m/s)"),
  wind_direction_deg FLOAT64 NOT NULL OPTIONS(description="Mean circular wind direction [0.0, 360.0) degrees"),
  avg_air_pressure_hpa FLOAT64 NOT NULL OPTIONS(description="Mean ISA barometric air pressure (hPa)"),
  avg_air_density_kgm3 FLOAT64 NOT NULL OPTIONS(description="Mean ISA air density (kg/m^3)"),
  ambient_temp_c FLOAT64 NOT NULL OPTIONS(description="Mean ambient air temperature (deg C)"),
  avg_turbulence_edr FLOAT64 NOT NULL OPTIONS(description="Mean Eddy Dissipation Rate (m^(2/3) s^(-1))"),
  max_turbulence_edr FLOAT64 NOT NULL OPTIONS(description="Peak Eddy Dissipation Rate (m^(2/3) s^(-1))"),
  drone_altitude_agl_m FLOAT64 NOT NULL OPTIONS(description="Mean UAV altitude Above Ground Level (m AGL)"),
  telemetry_summary_json STRING OPTIONS(description="JSON summary of window telemetry & attitude stats"),
  file_size_bytes INT64 NOT NULL OPTIONS(description="Exact byte size of archived .mp4 file (> 0)"),
  created_at TIMESTAMP NOT NULL OPTIONS(description="UTC clip creation timestamp (ISO-8601)")
)
PARTITION BY DATE(created_at)
CLUSTER BY project_id, folder_id, ecosystem_type;
SQL
```

### 4.3 Populate Production `.env` & Launch

Obtain a `rk_...` API key from `https://reactor.inc/dashboard` and update `.env`:

```dotenv
REACTOR_API_KEY=rk_live_your_actual_key
ORBIS_MODEL_SLUG=reactor/visko-orbis-stable
ORBIS_MOCK_MODE=false

GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/Users/your-user/.gcp/visko-la-sa.json
GCS_BUCKET_NAME=visko-orbis-aerial-datasets
BQ_DATASET_ID=visko_aerial_telemetry
GCP_MOCK_MODE=false
```

Start the backend and frontend:

```bash
# Terminal 1 — FastAPI Backend
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# Terminal 2 — Production Next.js Build & Server
npm --prefix frontend run build
npm --prefix frontend run start
```

Check `curl -s http://localhost:8000/api/v1/health`: `"mode"`, `"orbis_mode"`, and `"gcp_mode"` will all report `"live"`, and the top navigation bar in `/studio` will display **`LIVE WEBRTC`**.

---

## 5. Interactive Feature Walkthrough

### Step 1 — Seeding a Real-World Ecosystem in `/studio`

1. Navigate to **`http://localhost:3000/studio`**. On mount, `/studio` automatically initializes a session (`POST /api/v1/sessions`) under **`Visko UAV Perception Datasets`** (`default-uav-project`) and connects to `WS /ws/orbis/stream/{session_id}`.
2. In the **Left Conditioning Panel**:
   - **Project & Target Folder:** Choose where captured clips will be stored (e.g., `My Aerial Datasets` (`root`), `Alpine Trials`, `Coastal Crosswinds`, `Urban Canyon`, or click **`+ Quick New Folder`** to create a dedicated trial folder on the fly).
   - **UAV Gimbal Perspective:** Select one of the three stabilized camera rigs:
     - **Forward + Downward `-35°` Oblique (`forward_downward_oblique`, default):** Captures the forward flight corridor in the upper third and ground-plane topography in the lower two-thirds.
     - **Nadir `-90°` Downward (`nadir_downward`):** Belly-mounted straight-down overhead mapping camera.
     - **Forward FPV `-15°` (`forward_fpv`):** Low-altitude obstacle corridor navigation camera.
   - **Ecosystem & Altitude (`AGL m`):** Pick an ecosystem (`alpine`, `coastal`, `urban_canyon`, `temperate_forest`, `arid_desert`, `wetlands`, `custom`) and adjust the UAV altitude slider (`1–500 m` UI range; up to `5000 m` via API). Watch barometric pressure (`hPa`) and air density (`kg/m³`) respond immediately according to the ISA model.
   - **Seed Terrain Conditioning:**
     - **Option A — Built-in Dubai `256x256` Starter Gallery:** Click any tile from the curated Hugging Face **`ayoubkirouane/Dubai_dataset-Aerial_Imagery_256x256`** gallery (such as *Dubai Marina Coastal Breakwater*, *Al Qudra Desert Arterial Highway*, or *Downtown Boulevard Urban Grid*). The backend center-crops `256x256 -> 256x144` (`16:9`), Lanczos-upscales and lightly sharpens to **`832x480`**, archives to `gs://$GCS_BUCKET_NAME/seeds/...`, and re-anchors the live session.
     - **Option B — Custom Seed Upload Dropzone:** Drag and drop (or select) any `.png`, `.jpg`, `.jpeg`, `.webp`, `.mp4`, or `.webm` file (`<= 100 MB`) into the **Seed Media Dropzone**. Video seeds automatically have a keyframe extracted via `ffmpeg`, center-cropped to `16:9` (`832x480`), archived to GCS, and applied sequentially (`reset -> upload_file -> set_image -> set_prompt -> start`) so Chunk 1 never flickers unconditioned.

### Step 2 — Launching & Steering the Live Forward/Downward Drone-POV World

1. **Understanding `AerialSystemPromptCompiler` & Chunk Boundaries:**
   - Expand the **System Prompt Inspector** in the left panel (`GET /api/v1/sessions/system-prompt`) to view the compiled world-stake caption (`<= 95` words, `passthrough=True`).
   - In Live WebRTC mode, **Chunk 0** (`~1.833s` / 33 frames at 18 fps) is a warm-up priming chunk that emits `0` optical frames—`/studio` displays **`Priming Orbis World Stream (Chunk 0)...`** and transitions automatically to live optical video at Chunk `1+`.
2. **Steering Weather & Terrain via Real-Time Chat (Right Panel):**
   - Type incremental physical changes into the **Steering Chat** input (or click a tactical weather preset chip) and press **Send**:
     - Good incremental prompt: `"Heavy storm front rolls in with 24 m/s crosswind gusts and dense valley fog"`
   - **Best-Practice Steering Rules:**
     - **Describe only what changes:** `AerialSystemPromptCompiler.compile_steering_prompt` automatically prepends `"Maintaining continuous forward-and-downward UAV aerial flight along the same trajectory,"` and calls `set_prompt(..., passthrough=True)` **without** calling `reset` or `start`, morphing smoothly at the next `1.833s` chunk boundary.
     - **Avoid negations:** Diffusion world models attend to negated nouns (`"no trees"` can spawn trees). Even if you type negations (`"no people"`, `"no clouds"`, `"no drone props"`), the compiler automatically rewrites them into positive physical descriptions (`"empty open roadways"`, `"clear sunlit sky"`, `"unobstructed wide-angle lens view"`).
3. **Reading the Live 8 Hz Flight Telemetry HUD:**
   - Toggle the HUD overlay on the viewport to monitor real-time tabular-num gauges synchronized with your steering prompts:
     - **Wind & Gusts:** `wind_speed_mps` (`m/s`), `wind_gust_mps` (`m/s`), and `wind_direction_deg` (`0–360°` compass bearing).
     - **Atmosphere (ISA):** `air_pressure_hpa` (`hPa` — e.g., `~1012 hPa` coastal sea level vs. `< 880 hPa` alpine), `air_density_kgm3` (`kg/m³`), and `ambient_temp_c` (`°C`).
     - **Turbulence Severity:** `turbulence_edr` ($m^{2/3}s^{-1}$) classified into `LIGHT` (`< 0.20`), `MODERATE` (`0.20–0.449`), `SEVERE` (`0.45–0.699`), or `EXTREME` (`>= 0.70`).
     - **UAV Kinematics:** `drone_altitude_agl_m` (`m`), `drone_airspeed_mps` (`m/s`), `drone_pitch_deg`, `drone_roll_deg`, and `drone_yaw_deg`.

### Step 3 — Recording `5s`, `10s`, and `15s` Synthetic Clips

1. In the **Bottom Interval Recording Dock**, select one of the three fixed intervals: **`5s`**, **`10s`**, or **`15s`** *(any other duration is strictly rejected with HTTP `422`)*.
2. Optionally enter a descriptive clip title (e.g., `Alpine Crosswind Rotor Trial`) and click **Record Clip**.
3. The backend captures the clip (`request_clip` + FFmpeg `-c copy -movflags +faststart` in live mode, or `libx264` `yuv420p` `+faststart` synthesis in simulator mode), uploads the `.mp4` to `gs://$GCS_BUCKET_NAME/datasets/<project_id>/<folder_path>/<video_id>.mp4`, aggregates the exact telemetry window (`avg_wind_speed_mps`, `max_wind_gust_mps`, `avg_air_pressure_hpa`, `avg_air_density_kgm3`, `max_turbulence_edr`, etc.), and inserts the 27-column row into `aerial_datasets`.
4. When recording completes, use the confirmation toast to **Download `.mp4`** immediately or click **`View in Dataset Drive ->`**.

### Step 4 — Organizing, Adding & Downloading Datasets in `/drive`

1. Navigate to **`http://localhost:3000/drive`**.
2. **Create & Navigate Folders:** Click **New Folder** in the left sidebar (`POST /api/v1/projects/{project_id}/folders`) to create root or nested folders (e.g., `/coastal-crosswinds/storm-gusts`). Navigate via the expandable sidebar tree, clickable subfolder cards, or interactive top breadcrumbs.
3. **Add More Datasets to Any Folder:**
   - **Generate Live in Folder:** Select a folder and click **Generate Aerial Dataset in Folder** to jump straight into `/studio?projectId=...&folderId=...` pre-targeted to that folder and default ecosystem.
   - **Upload External `.mp4` Clip:** Click **Upload Dataset Clip**, attach a `.mp4` file, confirm or customize its folder/ecosystem/duration (`5s`, `10s`, `15s`), and submit (`POST /api/v1/projects/{project_id}/datasets/upload`).
4. **Search, Filter, Move, Inspect & Download:**
   - Filter clips by **Search text** (`title`, `video_id`, `initial_prompt`, `folder_path`), **Duration** (`5s`/`10s`/`15s`), **Ecosystem**, or **Turbulence EDR**, and toggle between **Grid View** and sortable **List View**.
   - Click any dataset card/row to open the **BigQuery Metadata Inspector Drawer**:
     - Play the `.mp4` inline with HTTP byte-range scrubbing (`206 Partial Content`).
     - Inspect all **27 BigQuery schema columns** and the full **Prompt Steering History** timeline (`prompt_history_json`).
     - **Move to Folder** (`PATCH /api/v1/datasets/{video_id}`) to reorganize clips across folders (automatically recomputing `folder_path`).
     - Click **Download MP4** for a direct attachment download (`Content-Disposition: attachment`), or click **Use as Seed in Studio** to condition a new generation run on that clip.

---

## 6. Running the Automated Verification Suite & Troubleshooting

### 6.1 Executing All 4 Verification Layers (`93/93` Tests)

First, ensure test dependencies are installed in `.venv` and `frontend/` / `tests/e2e/`:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt pytest pytest-asyncio
npm --prefix frontend install
npm --prefix tests/e2e install
```

Run the exact verified test commands from the repository root:

```bash
# 1. Backend Unit (67 tests) + Cross-Service Integration (8 tests) = 75 Python tests
PYTHONPATH=backend .venv/bin/pytest tests/unit/backend tests/integration -v

#    (Optional: run Backend Unit or Integration independently)
PYTHONPATH=backend .venv/bin/pytest tests/unit/backend -v
PYTHONPATH=backend .venv/bin/pytest tests/integration -v

# 2. Frontend Unit Suite via Vitest (16 tests across src/ & ../tests/unit/frontend/)
npm --prefix frontend run test

#    (Optional: run TypeScript strict check & Next.js SSR production build check)
npx --prefix frontend tsc --noEmit
npm --prefix frontend run build

# 3. Playwright End-to-End Browser Suite (2 full journeys: /studio -> /drive)
npx --prefix tests/e2e playwright test -c tests/e2e/playwright.config.ts
```

> **Note on Playwright E2E:** `tests/e2e/playwright.config.ts` automatically boots isolated FastAPI (`port 8000`, `ORBIS_MOCK_MODE=true`, `GCP_MOCK_MODE=true`, temporary `LOCAL_STORAGE_DIR`) and Next.js (`port 3000`) servers and tears them down cleanly on exit. Stop any manually running servers on ports `3000` or `8000` before launching Playwright. If neither `/Applications/Google Chrome.app` nor Playwright's bundled Chromium is installed yet, run `npx --prefix tests/e2e playwright install chromium` once beforehand.

### 6.2 Troubleshooting Common Issues

| Symptom / Error | Root Cause | Resolution |
| :--- | :--- | :--- |
| **`403 Forbidden` during live WebRTC seed upload or clip capture** | Minting an unbound Reactor JWT on every SDK callback creates a token that does not own the already-open Reactor session. | Ensure client code uses `frontend/src/lib/jwt-cache.ts` (`createMemoizedJwtResolver`), which caches the JWT until `expires_at * 1000 - 60_000` and refreshes via `POST /api/v1/auth/reactor-token` with `{"session_id": "<reactor_session_id>"}` (`resources.sessions.bind: [session_id]`). |
| **`422 Unprocessable Entity` on `POST /api/v1/auth/reactor-token` or `/api/v1/sessions`** | Passing bare `"visko-orbis-stable"` without the `"reactor/"` owner prefix, or passing an unsupported `camera_mode`. | Always pass `"model_id": "reactor/visko-orbis-stable"` and `camera_mode` in `{"forward_downward_oblique", "nadir_downward", "forward_fpv"}`. |
| **`ffmpeg binary is required` when uploading `.mp4`/`.webm` video seeds or remuxing live `.ts` clips** | `ffmpeg` is not on `PATH` (nor at `/opt/homebrew/bin/ffmpeg` or `/usr/local/bin/ffmpeg`). | Install FFmpeg (`brew install ffmpeg` on macOS or `sudo apt-get install -y ffmpeg` on Linux) and verify `which ffmpeg`. *(In mock clip recording, `clip_recorder.py` also includes a pure-Python ISO BMFF `.mp4` fallback).* |
| **GCS V4 Signed URL falls back to `/api/v1/datasets/{id}/file` or raises signing error** | Standard `gcloud auth application-default login` user credentials lack a local private RSA key needed for offline V4 URL signing. | Set `GOOGLE_APPLICATION_CREDENTIALS` to a Service Account JSON key with `roles/iam.serviceAccountTokenCreator` + `roles/storage.objectAdmin`. Note that Visko-LA automatically falls back to `/api/v1/datasets/{video_id}/file` byte-range streaming so downloads never break! |
| **Square `256x256` or vertical `9:16` seed images look stretched in custom integrations** | `reactor/visko-orbis-stable` resizes raw `set_image` inputs directly to `832x480` (`16:9`) without cropping. | Always upload seeds through `POST /api/v1/media/seed` or `POST /api/v1/media/seed/from-preset`, which center-crops to `16:9` (`256x256 -> 256x144`) and Lanczos-upscales to `832x480` prior to `upload_file` + `set_image`. |
| **`pip install` fails compiling `pydantic-core` or `grpcio` on macOS** | System `python3` resolves to bleeding-edge Python `3.15`, which predates prebuilt binary wheels. | Recreate `.venv` explicitly targeting Python `3.11` or `3.13`: `uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r backend/requirements.txt`. |
