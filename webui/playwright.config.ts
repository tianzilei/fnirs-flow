import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const realE2E = process.env.FNIRS_REAL_E2E === '1';
const venvPython = process.platform === 'win32'
  ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(repoRoot, '.venv', 'bin', 'python');
const pythonExecutable = process.env.PLAYWRIGHT_PYTHON
  || (existsSync(venvPython) ? venvPython : 'python');
const backendCommand = `"${pythonExecutable}" "${path.join(repoRoot, 'cli.py')}" webui --host 127.0.0.1 --port 8000`;

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
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER ? undefined : realE2E
    ? [
      {
        command: 'node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173',
        url: 'http://127.0.0.1:4173',
        reuseExistingServer: !process.env.CI,
      },
      {
        command: backendCommand,
        url: 'http://127.0.0.1:8000/api/projects',
        reuseExistingServer: false,
        timeout: 120_000,
        env: {
          FNIRS_ALLOWED_PATH_ROOTS: repoRoot,
          FNIRS_PROJECT_STORE_DIR: path.join(repoRoot, 'webui', 'test-results', 'real-api-projects'),
        },
      },
    ]
    : {
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
