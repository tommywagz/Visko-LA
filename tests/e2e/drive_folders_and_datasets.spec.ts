import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const SAMPLE_CLIP_FIXTURE = path.resolve(
  __dirname,
  '../fixtures/sample_clip.mp4'
);
const API_BASE = 'http://127.0.0.1:8000';

test.describe('Journey 2 — Google Drive Folder Organization, Adding Datasets to Folders & Direct Download', () => {
  test('browses captured 5s clip, creates folder, uploads clip, inspects BQ metadata, downloads .mp4, and routes to /studio', async ({
    page,
    request,
  }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];

    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const locUrl = msg.location()?.url || '';
        const text = msg.text();
        if (!text.includes('favicon.ico') && !locUrl.endsWith('/favicon.ico')) {
          consoleErrors.push(locUrl ? `${text} [${locUrl}]` : text);
        }
      }
    });

    // Self-seeding safeguard if drive_folders_and_datasets.spec.ts is ever run standalone (--no-deps)
    const initialCheck = await request.get(
      `${API_BASE}/api/v1/projects/default-uav-project/datasets?folder_id=all`
    );
    expect(initialCheck.ok()).toBeTruthy();
    const initialBody = (await initialCheck.json()) as {
      datasets: Array<{ duration_seconds: number }>;
    };
    if (!initialBody.datasets.some((d) => d.duration_seconds === 5)) {
      const sessRes = await request.post(`${API_BASE}/api/v1/sessions`, {
        data: {
          project_id: 'default-uav-project',
          folder_id: 'root',
          ecosystem_type: 'alpine',
        },
      });
      const sessJson = (await sessRes.json()) as { session_id: string };
      const recRes = await request.post(
        `${API_BASE}/api/v1/sessions/${sessJson.session_id}/record`,
        {
          data: { duration_seconds: 5, title: 'Standalone Seeded 5s Clip' },
        }
      );
      expect(recRes.status()).toBe(201);
    }

    // 1. Navigate to /drive and verify captured 5s clip appears in the dataset browser
    await page.goto('/drive');

    const sidebar = page.getByTestId('drive-sidebar');
    await expect(sidebar).toBeVisible();
    await expect(page.locator('main')).toContainText('0:05');

    // 2. Click New Folder, create "UAV-Crosswind-Eval", navigate into it, and verify breadcrumbs
    const newFolderBtn = page.getByTestId('new-folder-button');
    await expect(newFolderBtn).toBeVisible();
    await newFolderBtn.click();

    await page.getByTestId('new-folder-name-input').fill('UAV-Crosswind-Eval');
    await page.getByTestId('new-folder-submit-button').click();

    // Click into the newly created folder and check breadcrumbs
    await sidebar.getByText('UAV-Crosswind-Eval', { exact: true }).click();
    const breadcrumbs = page.getByTestId('drive-breadcrumbs');
    await expect(breadcrumbs).toContainText('UAV-Crosswind-Eval');

    // 3. Upload sample_clip.mp4 into "UAV-Crosswind-Eval" via upload-dataset-button
    const uploadBtn = page.getByTestId('upload-dataset-button');
    await expect(uploadBtn).toBeVisible();
    await uploadBtn.click();

    await page
      .getByTestId('upload-dataset-file-input')
      .setInputFiles(SAMPLE_CLIP_FIXTURE);
    await page.getByTestId('upload-dataset-submit-button').click();

    // Verify uploaded clip appears in folder view and test search + Grid/List view toggle
    await expect(page.getByText('sample_clip').first()).toBeVisible();

    const searchInput = page.getByTestId('drive-search-input');
    await searchInput.fill('sample_clip');
    await expect(page.getByText('sample_clip').first()).toBeVisible();

    const viewToggle = page.getByTestId('view-mode-toggle');
    await viewToggle.click(); // Switch Grid -> List
    await expect(page.locator('table')).toBeVisible();
    await viewToggle.click(); // Switch List -> Grid
    await searchInput.fill('');

    // 4. Open dataset-inspector-drawer and verify BigQuery metadata fields + inline <video>
    await page.getByText('sample_clip').first().click();
    const drawer = page.getByTestId('dataset-inspector-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText('0:05 (5s)');
    await expect(drawer).toContainText(/Alpine Pass|alpine/i);
    await expect(drawer).toContainText(/\d+\.\d+\s*m\/s/);
    await expect(drawer).toContainText(/\d+\.\d+\s*hPa/);
    await expect(drawer).toContainText(/\d+\.\d+\s*EDR/);
    await expect(drawer).toContainText('gs://');

    const inlineVideo = drawer.locator('video');
    await expect(inlineVideo).toBeVisible();
    await expect(inlineVideo).toHaveAttribute('src', /\/api\/v1\/datasets\/.*\/file/);

    // 5. Trigger Playwright download on direct-download-button and verify non-empty ISO BMFF .mp4
    const downloadPromise = page.waitForEvent('download');
    await page.getByTestId('direct-download-button').click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/\.mp4$/i);
    const savedMp4Path = path.join(
      os.tmpdir(),
      `visko-e2e-dl-${Date.now()}-${download.suggestedFilename()}`
    );
    await download.saveAs(savedMp4Path);
    const stat = fs.statSync(savedMp4Path);
    expect(stat.size).toBeGreaterThan(0);
    const headerBuf = fs.readFileSync(savedMp4Path).subarray(0, 12);
    expect(headerBuf.subarray(4, 8).toString('ascii')).toBe('ftyp');
    fs.unlinkSync(savedMp4Path);

    // 6. Verify Generate Aerial Dataset in Folder routes to /studio pre-targeted to "UAV-Crosswind-Eval"
    const generateInFolderBtn = page.getByTestId('generate-in-folder-button');
    await expect(generateInFolderBtn).toBeVisible();
    await generateInFolderBtn.click();

    await expect(page).toHaveURL(/\/studio\?.*folderId=uav-crosswind-eval/i);
    await expect(page.getByTestId('studio-target-folder-badge')).toContainText(
      'UAV-Crosswind-Eval'
    );

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
