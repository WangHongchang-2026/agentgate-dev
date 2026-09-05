import { expect, test, type Page } from '@playwright/test'

async function openNavigation(page: Page) {
  const menu = page.getByTestId('mobile-menu')
  if (await menu.isVisible()) await menu.click()
}

test('configures an evaluation and reports real persisted metrics and evidence', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '评估配置' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果报告' })).toBeVisible()
  await expect(page.getByText('Evaluators & Metrics')).toBeVisible()

  await openNavigation(page)
  await expect(page.getByTestId('nav-evaluate')).toHaveAttribute('aria-current', 'page')
  await page.getByTestId('nav-datasets').click()
  await expect(page).toHaveURL(/\/datasets$/)
  await expect(page.getByRole('heading', { name: '测评集与用例管理' })).toBeVisible()

  await openNavigation(page)
  await page.getByTestId('nav-evaluate').click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '评估配置' })).toBeVisible()

  await page.getByTestId('agent-select').click()
  await page.getByRole('option', { name: /风险版本/ }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()

  await expect(page.getByText('发布门槛未通过')).toBeVisible()
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('工具准确率')
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('25%')
  await page.getByRole('button', { name: /查看失败轨迹/ }).first().click()
  await expect(page.getByText('失败用例轨迹')).toBeVisible()
  await expect(page.getByText('approve_loan', { exact: true })).toBeVisible()
})
