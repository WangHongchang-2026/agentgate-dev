import { expect, test } from '@playwright/test'

test('configures an evaluation and reports real persisted metrics and evidence', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '评估配置' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果报告' })).toBeVisible()
  await expect(page.getByText('Evaluators & Metrics')).toBeVisible()

  await page.getByTestId('agent-select').click()
  await page.getByRole('option', { name: /风险版本/ }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()

  await expect(page.getByText('发布门槛未通过')).toBeVisible()
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('工具准确率')
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('25%')
  await page.getByRole('button', { name: /查看Trace/ }).first().click()
  await expect(page.getByText('用例轨迹')).toBeVisible()
  await expect(page.getByText('approve_loan', { exact: true })).toBeVisible()
})

test('reruns one Case with the latest Agent and compares evaluator results', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('agent-select').click()
  await page.getByRole('option', { name: /风险版本/ }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()

  const rerun = page.getByRole('button', { name: '重新运行此Case' })
  await expect(rerun).toHaveCount(1)
  await rerun.click()
  await expect(page.getByText('Case、评估器、Metric和Gate均复用原Run配置。')).toBeVisible()
  await expect(page.getByTestId('rerun-version-select')).toContainText('loan-agent-v2-fixed')
  await page.getByTestId('submit-rerun').click()

  await expect(page.getByTestId('rerun-comparison')).toBeVisible()
  await expect(page.getByTestId('rerun-comparison')).toContainText('loan-agent-v1-risky → loan-agent-v2-fixed')
  await expect(page.getByTestId('rerun-comparison')).toContainText('改善')
})
