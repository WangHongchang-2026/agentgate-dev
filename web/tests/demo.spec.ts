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

test('adds a completed Run Case to a regression Dataset and runs it normally', async ({ page }, testInfo) => {
  const regressionName = `贷款回归集-${testInfo.project.name}-${Date.now()}`
  await page.goto('/')
  await page.getByTestId('agent-select').click()
  await page.getByRole('option', { name: /风险版本/ }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()

  const addButton = page.getByRole('button', { name: '加入回归集' })
  await expect(addButton).toHaveCount(1)
  await addButton.click()
  await page.getByTestId('regression-mode').getByText('新建回归集').click()
  await page.getByTestId('regression-name').fill(regressionName)
  await page.getByTestId('regression-reason').fill('防止高风险贷款直接审批')
  await page.getByTestId('submit-regression').click()
  await expect(page.getByRole('dialog', { name: '加入回归集' })).toBeHidden({ timeout: 15_000 })
  await expect(page.getByText('发布门槛未通过')).toBeVisible()

  await page.getByTestId('nav-datasets').click()
  const regressionItem = page.locator('.dataset-list-item').filter({ hasText: regressionName })
  await expect(regressionItem).toContainText('回归集')
  await regressionItem.click()
  await expect(page.getByTestId('case-provenance')).toContainText('防止高风险贷款直接审批')
  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1')).toBeVisible()
  await page.getByTestId('nav-evaluate').click()
  await page.getByTestId('dataset-select').click()
  await page.getByRole('option', { name: new RegExp(`回归集 · ${regressionName} · v1`) }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()
  await expect(
    page.locator('#result-report').getByText(new RegExp(`${regressionName} v1`)).first(),
  ).toBeVisible()
})
