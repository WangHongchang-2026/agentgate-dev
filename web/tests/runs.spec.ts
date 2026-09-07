import { expect, test } from '@playwright/test'

const run = {
  run_id: 'run-polling',
  status: 'pending',
  dataset_id: 'loan-risk-policy',
  dataset_version: 1,
  dataset_name: '高风险贷款策略评估',
  target_name: 'Loan Agent',
  target_version: 'loan-agent-v2-fixed',
  total_cases: 4,
  completed_cases: 1,
  progress: 0.25,
  created_at: '2026-09-07T10:00:00Z',
  started_at: null,
  completed_at: null,
  duration_seconds: null,
  error: null,
  queue_position: 2,
}

const emptyCounts = {
  pending: 0,
  running: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
}

test('shows queue and running progress then stops polling after completion', async ({ page }) => {
  let requests = 0
  await page.route('**/api/runs/activity?*', async (route) => {
    requests += 1
    const active = requests === 1
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(active ? {
        status_counts: { ...emptyCounts, pending: 1, running: 1 },
        queued: [run],
        running: [{
          ...run,
          run_id: 'run-running',
          status: 'running',
          completed_cases: 2,
          progress: 0.5,
          started_at: '2026-09-07T10:00:01Z',
          duration_seconds: 3,
          queue_position: null,
        }],
        recent: [],
      } : {
        status_counts: { ...emptyCounts, completed: 1 },
        queued: [],
        running: [],
        recent: [{
          ...run,
          status: 'completed',
          completed_cases: 4,
          progress: 1,
          started_at: '2026-09-07T10:00:01Z',
          completed_at: '2026-09-07T10:00:05Z',
          duration_seconds: 4,
          queue_position: null,
        }],
      }),
    })
  })

  await page.goto('/runs')
  await expect(page.getByRole('heading', { name: '运行队列' }).last()).toBeVisible()
  await expect(page.getByText('队列第 2 位')).toBeVisible()
  await page.getByTestId('runs-running').click()
  await expect(page.getByText('2 / 4 个用例')).toBeVisible()
  await expect.poll(() => requests).toBeGreaterThanOrEqual(2)

  await page.getByTestId('runs-history').click()
  await expect(page.getByText('4 / 4 个用例')).toBeVisible()
  const stoppedAt = requests
  await page.waitForTimeout(2300)
  expect(requests).toBe(stoppedAt)
})
