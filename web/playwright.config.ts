import { defineConfig, devices } from '@playwright/test'
import os from 'os'
import path from 'path'

// E2E 隔离：临时 DB + 独立端口（18000 后端 / 15173 前端），不撞开发后端
const testDatabase = path.join(os.tmpdir(), `agentgate-playwright-${process.pid}.db`)

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: false,
  webServer: [
    {
      command: 'python3 -m uvicorn e2e_generation_server:app --host 127.0.0.1 --port 18000',
      port: 18000,
      reuseExistingServer: false,
      env: { ...process.env, AGENTGATE_DB: testDatabase, PYTHONPATH: '../src:tests' },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 15173',
      port: 15173,
      reuseExistingServer: false,
      env: { ...process.env, AGENTGATE_API_TARGET: 'http://127.0.0.1:18000' },
    },
  ],
  use: {
    baseURL: 'http://127.0.0.1:15173',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
  ],
})
