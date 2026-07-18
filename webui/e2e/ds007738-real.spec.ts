import { expect, test } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const packagePath = process.env.FNIRS_REAL_PACKAGE || path.join(
  repoRoot,
  'outputs/ds007738_golden_path/export/ds007738_golden_path_package.fnirsflow.zip',
);
const dataRoot = process.env.FNIRS_REAL_DATA_ROOT || path.join(repoRoot, 'Sample/ds007738-download');

test.describe('ds007738 real-data package', () => {
  test.skip(process.env.FNIRS_REAL_E2E !== '1', 'Set FNIRS_REAL_E2E=1 with the API running on port 8000.');

  test('imports, relinks, browses results, exports, and cancels a job', async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto('/projects');
    await page.getByRole('button', { name: '+ New Project' }).click();
    await page.getByRole('textbox', { name: 'Project name (required)' })
      .fill(`ds007738 browser ${Date.now()}`);
    await page.getByRole('button', { name: 'Create', exact: true }).click();

    await page.getByRole('button', { name: 'Import', exact: true }).click();
    await page.getByRole('textbox', { name: 'Package Path' }).fill(packagePath);
    await page.locator('.import-form').filter({ has: page.getByRole('textbox', { name: 'Package Path' }) })
      .getByRole('button', { name: 'Import', exact: true }).click();
    await expect(page.getByText('Read-Only Package')).toBeVisible();

    await page.getByRole('textbox', { name: 'Data Root' }).fill(dataRoot);
    await page.getByRole('button', { name: 'Relink', exact: true }).click();
    await expect(page.getByText(`Linked to ${dataRoot}`)).toBeVisible();

    await page.getByRole('button', { name: 'Navigate to Results', exact: true }).click();
    await expect(page.getByText('Imported package results are available in the result tabs below.')).toBeVisible();
    await page.getByRole('button', { name: 'Group', exact: true }).click();
    await expect(page.getByText('2 files · 1135 rows · showing 100 representative rows')).toBeVisible();
    await expect(page.getByText('technical_smoke_roi_channels_000_015', { exact: true })).toBeVisible();
    await expect(page.getByText('Covert_Left_minus_Covert_Right', { exact: true }).first()).toBeVisible();

    await page.getByRole('button', { name: 'Navigate to Export', exact: true }).click();
    await page.getByRole('button', { name: 'Export Package', exact: true }).click();
    await expect(page.getByText('Package exported successfully!')).toBeVisible();

    await page.getByRole('button', { name: 'Navigate to Runs', exact: true }).click();
    await page.getByRole('button', { name: 'Execute', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByText(/Attempt .* · cancelled/)).toBeVisible();
    await expect(page.getByText('Execution cancelled', { exact: true })).toBeVisible();
    await expect(page.getByText('Execution failed', { exact: true })).toHaveCount(0);
  });
});
