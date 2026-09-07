import { defineConfig, devices } from '@playwright/test'

const testDatabase = `/tmp/agentgate-playwright-${process.pid}.db`
const redisPort = 16379
const redisUrl = `redis://127.0.0.1:${redisPort}/0`
const redisServer = process.env.AGENTGATE_REDIS_SERVER ?? 'redis-server'
const backendEnvironment = {
  ...process.env,
  AGENTGATE_DB: testDatabase,
  AGENTGATE_REDIS_URL: redisUrl,
  PYTHONPATH: '../src',
}

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: false,
  webServer: [
    {
      command: `${redisServer} --port ${redisPort} --save "" --appendonly no --dir /tmp`,
      port: redisPort,
      reuseExistingServer: false,
    },
    {
      command: `bash -c 'python3 -m celery -A agentgate.integrations.job_dispatchers.celery:celery_app worker --loglevel=WARNING --concurrency=1 --pool=solo & worker_pid=$!; trap "kill $worker_pid" EXIT INT TERM; python3 -m uvicorn agentgate.server.app:app --host 127.0.0.1 --port 18000'`,
      port: 18000,
      reuseExistingServer: false,
      env: backendEnvironment,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 15173',
      port: 15173,
      reuseExistingServer: false,
      env: { ...process.env, AGENTGATE_API_TARGET: 'http://127.0.0.1:18000' },
    },
  ],
  use: { baseURL: 'http://127.0.0.1:15173', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
})
