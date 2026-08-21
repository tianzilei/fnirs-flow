import { expect, test } from '@playwright/test';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const packagePath = process.env.FNIRS_REAL_PACKAGE || path.join(
  repoRoot,
  'outputs/public_v121_ds007738/export/public_v121_ds007738_package.fnirsflow.zip',
);
const dataRoot = process.env.FNIRS_REAL_DATA_ROOT || path.join(repoRoot, 'Sample/ds007738-download');

test.describe('ds007738 real-data package', () => {
  test.skip(process.env.FNIRS_REAL_E2E !== '1', 'Set FNIRS_REAL_E2E=1 to run the Sample-data scenario.');

  test('imports, relinks, browses results, exports, and cancels a job', async ({ page }) => {
    test.setTimeout(120_000);
    if (!existsSync(packagePath)) {
      throw new Error(`Real E2E package not found: ${packagePath}. Set FNIRS_REAL_PACKAGE.`);
    }
    if (!existsSync(dataRoot)) {
      throw new Error(`Real E2E Sample data not found: ${dataRoot}. Set FNIRS_REAL_DATA_ROOT.`);
    }

    await page.goto('/projects');
    await page.getByRole('button', { name: '+ New Project' }).click();
    await page.getByRole('textbox', { name: 'Project name' })
      .fill(`ds007738 browser ${Date.now()}`);
    await page.getByLabel('Data folder path').fill(dataRoot);
    await page.getByRole('button', { name: 'Create', exact: true }).click();

    await page.getByRole('button', { name: 'Open more navigation' }).click();
    await page.getByRole('menuitem', { name: 'Import', exact: true }).click();
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
    await expect(page.getByText(/\d+ files \u00b7 \d+ rows \u00b7 showing 100 representative rows/)).toBeVisible();
    await expect(page.getByText('derivatives/group/group_summary.json', { exact: true })).toBeVisible();
    await expect(page.getByText('Covert_Left_minus_Covert_Right', { exact: true }).first()).toBeVisible();

    await page.getByRole('button', { name: 'Navigate to Export', exact: true }).click();
    await page.getByRole('button', { name: 'Export Package', exact: true }).click();
    await expect(page.getByText('Package exported successfully!')).toBeVisible();

    await page.getByRole('button', { name: 'Navigate to Runs', exact: true }).click();
    await page.getByRole('button', { name: 'Execute project', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page.getByText(/Attempt .* \u00b7 cancelled/)).toBeVisible();
    await expect(page.getByText('Execution cancelled', { exact: true })).toBeVisible();
    await expect(page.getByText('Execution failed', { exact: true })).toHaveCount(0);
  });
});
