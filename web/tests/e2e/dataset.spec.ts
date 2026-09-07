import { expect, test, type Page } from '@playwright/test'

async function createDataset(page: Page, name: string) {
  await page.getByTestId('create-dataset').click()
  await page.getByTestId('dataset-name').fill(name)
  await page.getByTestId('submit-dataset').click()
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('当前草稿', { exact: true })).toBeVisible()
}

async function addSelectValues(page: Page, testId: string, values: string[]) {
  const input = page.getByTestId(testId).locator('input')
  for (const value of values) {
    await input.fill(value)
    await input.press('Enter')
  }
}

async function exportedWorkbook(page: Page, name: string) {
  await createDataset(page, name)
  await page.getByTestId('add-case').click()
  await page.getByTestId('case-name').fill('Excel 保留用例')
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿')).toBeVisible()
  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1')).toBeVisible()

  const datasets = await page.request.get('/api/datasets')
  const source = (await datasets.json()).find((item: { name: string }) => item.name === name)
  expect(source).toBeTruthy()
  const exportResponse = await page.request.get(
    `/api/datasets/${source.id}/versions/1/export/excel`,
  )
  expect(exportResponse.ok()).toBeTruthy()
  return exportResponse.body()
}

function uniqueDatasetName(prefix: string) {
  return `${prefix}-${test.info().project.name}-${Date.now()}`
}

test('creates, publishes, runs, and versions a Dataset through the real UI', async ({ page }) => {
  const name = uniqueDatasetName('高风险审批集')
  await page.goto('/datasets')
  await expect(page.getByRole('heading', { name: '测评集与用例管理' })).toBeVisible()

  await createDataset(page, name)
  await page.getByTestId('add-case').click()
  await page.getByTestId('case-name').fill('高风险申请必须人工复核')
  await page.getByTestId('turn-input-0').fill(JSON.stringify({
    skill: 'loan_approval',
    application_id: 'WEB-HIGH-1',
    risk: 'high',
    amount: 80000,
  }, null, 2))
  await addSelectValues(page, 'required-tools-0', ['credit_inquiry', 'request_human_review'])
  await addSelectValues(page, 'forbidden-tools-0', ['approve_loan'])
  await addSelectValues(page, 'policy-rules-0', ['high_risk_requires_review'])

  await page.getByTestId('add-expectation').click()
  await page.getByRole('menuitem', { name: '最终状态' }).click()
  await page.getByTestId('expectation-path-0').fill('status')
  await page.getByTestId('expectation-value-0').fill('"pending_review"')
  await page.getByTestId('expectation-value-0').press('Tab')
  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿')).toBeVisible()

  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1')).toBeVisible()
  await page.reload()
  await page.locator('.dataset-list-item').filter({ hasText: name }).click()
  await expect(page.getByTestId('version-published-1')).toBeVisible()
  await expect(page.getByText('高风险申请必须人工复核', { exact: true }).first()).toBeVisible()

  await page.getByTestId('dataset-agent-select').click()
  await page.getByRole('option', { name: '风险版本' }).click()
  await page.getByTestId('run-dataset-version').click()
  await expect(page.getByText('发布门槛未通过')).toBeVisible()
  await expect(page.getByText(new RegExp(`${name} v1`))).toBeVisible()
  // CheckResultList 默认折叠用例组，展开后才能看到期望/实际对比
  await page
    .locator('.case-result-group')
    .filter({ hasText: '高风险申请必须人工复核' })
    .first()
    .locator('.case-result-title b')
    .click()
  await expect(page.getByText(/期望.*pending_review.*实际.*approved/).first()).toBeVisible()
  // 记录 v1 运行 id，末尾按 id 直达其结果页（全页加载会重置 Pinia，不能依赖内存态）
  const v1RunId = page.url().match(/\/results\/([^/?#]+)/)![1]

  await page.getByTestId('nav-datasets').click()
  await page.locator('.dataset-list-item').filter({ hasText: name }).click()
  await page.getByTestId('create-draft').click()
  await page.getByTestId('case-name').fill('高风险申请必须人工复核（v2）')
  await page.getByTestId('save-case').click()
  await page.getByTestId('publish-draft').click()
  await expect(page.getByTestId('version-published-1')).toBeVisible()
  await expect(page.getByTestId('version-published-2')).toBeVisible()

  // 结果报告为独立路由；按 id 直达 v1 运行结果页（全页加载后 results 视图按 id 重新拉取报告）
  await page.goto(`/results/${v1RunId}`)
  await expect(page.getByText(new RegExp(`${name} v1`))).toBeVisible()
  const caseGroup = page
    .locator('.case-result-group')
    .filter({ hasText: '高风险申请必须人工复核' })
    .first()
  await caseGroup.locator('.case-result-title b').click() // 展开用例组
  await expect(caseGroup.getByText('最终状态', { exact: true })).toBeVisible()
})

test('shows structured validation when an empty draft cannot be published', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, uniqueDatasetName('空测评集'))
  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('草稿尚不能发布')).toBeVisible()
  await expect(page.getByText('测评集至少需要一个用例', { exact: true })).toBeVisible()
})

test('opens AI candidate generation only from a Dataset draft', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, uniqueDatasetName('AI 生成入口'))

  await page.getByTestId('open-ai-generation').click()
  const dialog = page.getByTestId('generation-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('客户服务 Agent', { exact: true })).toBeVisible()
  await expect(dialog.getByText('2.1.0', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/经你审核后/)).toBeVisible()
  await expect(dialog.getByText('评测对象', { exact: true }).first()).toBeVisible()
  await expect(dialog.getByText('生成规模', { exact: true })).toBeVisible()
  await expect(dialog.getByTestId('configure-model-credential')).toBeVisible()
  await expect(dialog.getByText('参考测评集（可选）')).not.toBeVisible()
  await dialog.getByRole('button', { name: '参考用例（可选）' }).click()
  await expect(dialog.getByText('参考测评集', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})

test('generates, edits, validates, and accepts an AI candidate through the real UI', async ({ page }) => {
  const name = uniqueDatasetName('AI 生成闭环')
  await page.goto('/datasets')
  await createDataset(page, name)
  await page.getByTestId('open-ai-generation').click()

  const dialog = page.getByTestId('generation-dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByTestId('generate-candidates').click()
  await expect(dialog.getByTestId('generation-review')).toBeVisible()
  await expect(dialog.getByTestId('review-summary')).toContainText('6可加入')
  await expect(dialog.getByTestId('review-summary')).toContainText('0待修正')

  const generateUrl = '**/api/datasets/*/drafts/generate-candidates'
  await page.route(generateUrl, async (route) => {
    await route.fulfill({
      status: 502,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { message: '模拟重新生成失败' } }),
    })
  })
  await dialog.getByTestId('back-to-generation-settings').click()
  await dialog.getByTestId('generate-candidates').click()
  await expect(page.getByText('模拟重新生成失败')).toBeVisible()
  await expect(dialog.getByTestId('generation-settings')).toBeVisible()
  await page.unroute(generateUrl)
  await dialog.getByTestId('continue-candidate-review').click()
  await expect(dialog.getByTestId('generation-review')).toBeVisible()
  await expect(dialog.locator('.candidate')).toHaveCount(6)
  await page.setViewportSize({ width: 900, height: 900 })
  const sidebarBox = await dialog.locator('.candidate-sidebar').boundingBox()
  const detailBox = await dialog.locator('.candidate-detail').boundingBox()
  expect(sidebarBox).not.toBeNull()
  expect(detailBox).not.toBeNull()
  expect(sidebarBox!.y + sidebarBox!.height).toBeLessThanOrEqual(detailBox!.y + 1)
  await dialog.getByRole('button', { name: '全选有效' }).click()
  await expect(dialog.getByTestId('review-summary')).toContainText('6已选择')
  await dialog.getByRole('button', { name: '清空' }).click()
  await expect(dialog.getByTestId('review-summary')).toContainText('0已选择')
  await expect(dialog.getByText('初始状态（JSON）')).not.toBeVisible()

  const editedName = '人工审核后的订单查询用例'
  await dialog.getByTestId('case-name').fill(editedName)
  await dialog.getByTestId('save-case').click()
  await expect(page.getByText('候选修改已通过校验')).toBeVisible()
  await expect(dialog.getByTestId('review-summary')).toContainText('6可加入')

  await dialog.locator('.candidate').first().locator('.el-checkbox').click()
  await dialog.getByTestId('accept-candidates').click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('已将 1 个生成用例加入草稿')).toBeVisible()
  await expect(page.getByText(editedName, { exact: true }).first()).toBeVisible()
})

test('allows a reviewer to change a generated multi-turn candidate to single-turn', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, uniqueDatasetName('AI 多轮约束'))
  await page.getByTestId('open-ai-generation').click()

  const dialog = page.getByTestId('generation-dialog')
  const turnModeField = dialog.locator('.el-form-item').filter({ hasText: '对话轮次' })
  await turnModeField.locator('.el-select').click()
  await page.getByRole('option', { name: '仅多轮' }).click()
  await dialog.getByTestId('generate-candidates').click()

  await expect(dialog.getByTestId('review-summary')).toContainText('6可加入')
  await expect(dialog.locator('.candidate').filter({ hasText: '2 轮' })).toHaveCount(6)

  await dialog.getByRole('button', { name: '删除此轮' }).first().click()
  await dialog.getByTestId('save-case').click()
  await expect(page.getByText('候选修改已通过校验')).toBeVisible()
  await expect(dialog.getByTestId('review-summary')).toContainText('6可加入')
  await expect(dialog.locator('.candidate').filter({ hasText: '1 轮' })).toHaveCount(1)
})

test('surfaces backend JSON Schema preflight errors without blocking draft save', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, `Schema预检-${Date.now()}`)
  await page.getByTestId('add-case').click()
  await page.getByTestId('case-name').fill('Schema 预检用例')
  await page.getByTestId('turn-input-0').fill(JSON.stringify({ skill: 'demo' }, null, 2))

  await page.getByTestId('add-expectation').click()
  await page.getByRole('menuitem', { name: '最终状态' }).click()
  await page.getByTestId('expectation-condition-0').click()
  await page.getByRole('option', { name: 'JSON Schema 校验' }).click()

  await page.getByTestId('expectation-schema-0').fill(
    JSON.stringify({ $schema: 'http://json-schema.org/draft-04/schema#', type: 'object' }, null, 2),
  )
  await expect(page.getByTestId('expectation-schema-preflight-error-0')).toContainText(
    'unsupported JSON Schema draft',
  )

  await page.getByTestId('save-case').click()
  await expect(page.getByText('用例已保存到草稿')).toBeVisible()
})

test('only exposes Excel export for a published Dataset version', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, uniqueDatasetName('Excel 导出状态'))
  await expect(page.getByTestId('export-excel')).toHaveCount(0)

  await page.getByTestId('add-case').click()
  await page.getByTestId('case-name').fill('可导出的用例')
  await page.getByTestId('save-case').click()
  await page.getByTestId('publish-draft').click()
  await expect(page.getByTestId('export-excel')).toBeVisible()
})

test('downloads the documented Excel import template', async ({ page }) => {
  await page.goto('/datasets')

  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('download-excel-template').click()
  const download = await downloadPromise

  expect(download.suggestedFilename()).toBe('agentgate-dataset-template.xlsx')
})

test('imports an exported Excel dataset as a publishable draft', async ({ page }) => {
  await page.goto('/datasets')
  const workbook = await exportedWorkbook(page, uniqueDatasetName('Excel 源测评集'))
  const importedName = uniqueDatasetName('Excel 导入测评集')

  await page.getByTestId('import-excel').click()
  await page.getByTestId('excel-import-file').setInputFiles({
    name: `${importedName}.xlsx`,
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: workbook,
  })
  await expect(page.getByText('Excel 已导入为草稿')).toBeVisible()
  await expect(page.getByText(importedName, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('当前草稿', { exact: true })).toBeVisible()
  await expect(page.getByText('Excel 保留用例', { exact: true }).first()).toBeVisible()

  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1')).toBeVisible()
})

test('displays structured workbook errors after direct Excel selection', async ({ page }) => {
  await page.goto('/datasets')
  const before = await page.request.get('/api/datasets')
  const datasetCount = (await before.json()).length
  await page.getByTestId('import-excel').click()
  await page.getByTestId('excel-import-file').setInputFiles({
    name: 'invalid.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('not an XLSX workbook'),
  })

  const issue = page.getByTestId('excel-import-issue-0')
  await expect(issue.getByTestId('excel-import-issue-sheet')).toHaveText('Cases')
  await expect(issue.getByTestId('excel-import-issue-row')).toHaveText('—')
  await expect(issue.getByTestId('excel-import-issue-column')).toHaveText('—')
  const after = await page.request.get('/api/datasets')
  expect((await after.json())).toHaveLength(datasetCount)
})

test('displays JSON import errors at the top of the Dataset page', async ({ page }) => {
  await page.goto('/datasets')
  await page.getByTestId('import-json').click()
  await page.locator('input[accept="application/json,.json"]').setInputFiles({
    name: 'invalid.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{invalid json'),
  })

  const alert = page.getByTestId('dataset-import-errors')
  await expect(alert).toBeVisible()
  await expect(alert).toContainText('JSON')
})

test('downloads a published Dataset as Excel', async ({ page }) => {
  await page.goto('/datasets')
  const name = uniqueDatasetName('Excel-download')
  await exportedWorkbook(page, name)

  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('export-excel').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(`${name}-v1.xlsx`)
})
