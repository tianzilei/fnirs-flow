import { defineConfig, devices } from '@playwright/test';
const chromiumExecutable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: './e2e',
  testIgnore: '**/._*',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  outputDir: './test-results',
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: chromiumExecutable
      ? { executablePath: chromiumExecutable }
      : undefined,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      testIgnore: '**/*-real.spec.ts',
      use: {
        ...devices['Desktop Firefox'],
        launchOptions: {
          firefoxUserPrefs: {
            'gfx.webrender.all': false,
            'gfx.webrender.software': false,
            'layers.acceleration.disabled': true,
          },
        },
      },
    },
    {
      name: 'webkit',
      testIgnore: '**/*-real.spec.ts',
      use: { ...devices['Desktop Safari'] },
    },
  ],
});
