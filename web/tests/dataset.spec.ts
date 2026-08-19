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
  await expect(page.getByText(/期望.*pending_review.*实际.*approved/).first()).toBeVisible()

  await page.getByTestId('nav-datasets').click()
  await page.locator('.dataset-list-item').filter({ hasText: name }).click()
  await page.getByTestId('create-draft').click()
  await page.getByTestId('case-name').fill('高风险申请必须人工复核（v2）')
  await page.getByTestId('save-case').click()
  await page.getByTestId('publish-draft').click()
  await expect(page.getByTestId('version-published-1')).toBeVisible()
  await expect(page.getByTestId('version-published-2')).toBeVisible()

  await page.getByTestId('nav-evaluate').click()
  await expect(page.getByText(new RegExp(`${name} v1`))).toBeVisible()
  await expect(page.getByText(/高风险申请必须人工复核 · 最终状态/).first()).toBeVisible()
})

test('shows structured validation when an empty draft cannot be published', async ({ page }) => {
  await page.goto('/datasets')
  await createDataset(page, uniqueDatasetName('空测评集'))
  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('草稿尚不能发布')).toBeVisible()
  await expect(page.getByText('测评集至少需要一个用例', { exact: true })).toBeVisible()
})

test('imports an exported Excel dataset as a publishable draft', async ({ page }) => {
  await page.goto('/datasets')
  const workbook = await exportedWorkbook(page, uniqueDatasetName('Excel 源测评集'))
  const importedName = uniqueDatasetName('Excel 导入测评集')

  await page.getByTestId('import-excel').click()
  const dialog = page.getByRole('dialog', { name: '导入 Excel' })
  await dialog.getByTestId('excel-import-file').setInputFiles({
    name: 'source.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: workbook,
  })
  await dialog.getByTestId('submit-excel-import').click()
  await expect(page.getByText('请输入测评集名称')).toBeVisible()
  await expect(dialog).toBeVisible()

  await dialog.getByTestId('excel-import-name').fill(importedName)
  await dialog.getByTestId('submit-excel-import').click()
  await expect(page.getByText('Excel 已导入为草稿')).toBeVisible()
  await expect(page.getByText(importedName, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('当前草稿', { exact: true })).toBeVisible()
  await expect(page.getByText('Excel 保留用例', { exact: true }).first()).toBeVisible()

  await page.getByTestId('publish-draft').click()
  await expect(page.getByText('已发布 v1')).toBeVisible()
})

test('keeps the Excel import dialog open and displays structured workbook errors', async ({ page }) => {
  await page.goto('/datasets')
  const before = await page.request.get('/api/datasets')
  const datasetCount = (await before.json()).length
  await page.getByTestId('import-excel').click()
  const dialog = page.getByRole('dialog', { name: '导入 Excel' })
  await dialog.getByTestId('excel-import-name').fill('无效 Excel')
  await dialog.getByTestId('excel-import-file').setInputFiles({
    name: 'invalid.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('not an XLSX workbook'),
  })
  await dialog.getByTestId('submit-excel-import').click()

  const issue = dialog.getByTestId('excel-import-issue-0')
  await expect(dialog).toBeVisible()
  await expect(issue.getByTestId('excel-import-issue-sheet')).toHaveText('Cases')
  await expect(issue.getByTestId('excel-import-issue-row')).toHaveText('—')
  await expect(issue.getByTestId('excel-import-issue-column')).toHaveText('—')
  const after = await page.request.get('/api/datasets')
  expect((await after.json())).toHaveLength(datasetCount)
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
