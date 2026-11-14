import path from 'node:path';
import { expect, test } from '@playwright/test';

const ALPINE_SEED_FIXTURE = path.resolve(
  __dirname,
  '../fixtures/sample_alpine_seed.png'
);

test.describe('Journey 1 — Live Drone-POV Aerial Studio, Seed Conditioning, Chat Steering & Clip Capture', () => {
  test('conditions 16:9 seed media, streams live HUD telemetry, steers weather via chat, and records 5s clip', async ({
    page,
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

    // 1. Navigate to /studio and verify live viewport + telemetry HUD numerical readouts
    await page.goto('/studio');

    const hud = page.getByTestId('telemetry-hud');
    await expect(hud).toBeVisible();
    await expect(hud).toContainText(/\d+\.\d+\s*m\/s/);
    await expect(hud).toContainText(/\d+\.\d+\s*hPa/);
    await expect(hud).toContainText(/\d+\.\d+\s*EDR/);
    await expect(hud).toContainText(/\d+\.\d+\s*m AGL/);

    // Wait for auto-started Orbis session to enable recording CTA
    const recordBtn = page.getByTestId('record-clip-button');
    await expect(recordBtn).toBeEnabled();

    // 2. Upload sample_alpine_seed.png in Seed Media Dropzone & verify 832x480 preview + conditioning status
    const dropzone = page.getByTestId('seed-upload-dropzone');
    await expect(dropzone).toBeVisible();
    const fileInput = dropzone.locator('input[type="file"]');
    await fileInput.setInputFiles(ALPINE_SEED_FIXTURE);

    await expect(dropzone).toContainText('832×480 (16:9)');
    await expect(dropzone).toContainText('gs://');
    await expect(dropzone.locator('img')).toBeVisible();

    // 3. Type a live steering prompt in chat-prompt-input, click chat-send-button, verify history + HUD update
    const steeringPrompt =
      'Increase crosswind gusts to 20 m/s with dense mountain mist';
    const chatInput = page.getByTestId('chat-prompt-input');
    const chatSend = page.getByTestId('chat-send-button');
    const chatPanel = page.getByTestId('scene-chat-panel');

    await chatInput.fill(steeringPrompt);
    await expect(chatSend).toBeEnabled();
    await chatSend.click();

    await expect(chatPanel).toContainText(steeringPrompt);
    await expect(chatPanel).toContainText(/Applied|Morphing/);
    await expect(hud).toContainText(/\d+\.\d+\s*m\/s/);

    // 4. Select 5s interval, click Capture Synthetic Clip, and assert completion confirmation
    const btn5s = page.getByTestId('interval-5s');
    const btn10s = page.getByTestId('interval-10s');
    const btn15s = page.getByTestId('interval-15s');

    await btn5s.click();
    await expect(btn5s).toHaveAttribute('aria-pressed', 'true');
    await expect(btn5s).toHaveAttribute('data-active', 'true');

    await recordBtn.click();

    const completionBanner = page.getByRole('status');
    await expect(completionBanner).toContainText('Clip Captured & Indexed');
    await expect(completionBanner).toContainText('0:05');
    await expect(completionBanner).toContainText('gs://');
    await expect(
      completionBanner.getByRole('link', { name: /View in Dataset Drive/i })
    ).toBeVisible();

    // 5. Verify 10s and 15s interval selector toggles cleanly update active recording duration state
    await btn10s.click();
    await expect(btn10s).toHaveAttribute('aria-pressed', 'true');
    await expect(btn10s).toHaveAttribute('data-active', 'true');
    await expect(btn5s).toHaveAttribute('aria-pressed', 'false');
    await expect(recordBtn).toContainText('10s');

    await btn15s.click();
    await expect(btn15s).toHaveAttribute('aria-pressed', 'true');
    await expect(btn15s).toHaveAttribute('data-active', 'true');
    await expect(btn10s).toHaveAttribute('aria-pressed', 'false');
    await expect(recordBtn).toContainText('15s');

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
