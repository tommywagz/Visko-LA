import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { defineConfig } from '@playwright/test';

const REPO_ROOT = path.resolve(__dirname, '../..');
const BACKEND_DIR = path.join(REPO_ROOT, 'backend');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');

const VENV_PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const PYTHON_BIN = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';

const E2E_STORAGE_DIR =
  process.env.VISKO_E2E_STORAGE_DIR ||
  path.join(os.tmpdir(), `visko-la-e2e-storage-${process.pid}`);

const PW_OUTPUT_DIR = path.join(os.tmpdir(), `visko-la-pw-output-${process.pid}`);

const HAS_MAC_CHROME = fs.existsSync('/Applications/Google Chrome.app');

export default defineConfig({
  testDir: __dirname,
  outputDir: PW_OUTPUT_DIR,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    channel: HAS_MAC_CHROME ? 'chrome' : undefined,
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },
  projects: [
    {
      name: 'studio',
      testMatch: /studio_live_generation\.spec\.ts/,
    },
    {
      name: 'drive',
      testMatch: /drive_folders_and_datasets\.spec\.ts/,
      dependencies: ['studio'],
    },
  ],
  webServer: [
    {
      command: `"${PYTHON_BIN}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: BACKEND_DIR,
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        ORBIS_MOCK_MODE: 'true',
        GCP_MOCK_MODE: 'true',
        LOCAL_STORAGE_DIR: E2E_STORAGE_DIR,
        BACKEND_PORT: '8000',
        ALLOWED_ORIGINS: 'http://localhost:3000,http://127.0.0.1:3000',
      },
    },
    {
      command: 'npm run build && npm run start',
      cwd: FRONTEND_DIR,
      url: 'http://localhost:3000/studio',
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE_URL: 'http://localhost:8000',
        NEXT_PUBLIC_WS_BASE_URL: 'ws://localhost:8000',
      },
    },
  ],
});
