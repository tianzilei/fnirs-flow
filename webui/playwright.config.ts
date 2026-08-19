import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const chromiumExecutable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  || (existsSync(macChrome) ? macChrome : undefined);

export default defineConfig({
  testDir: './e2e',
  testIgnore: '**/._*',
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    launchOptions: chromiumExecutable
      ? { executablePath: chromiumExecutable }
      : undefined,
  },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER ? undefined : {
    command: 'node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
