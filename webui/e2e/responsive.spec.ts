import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { json } from './support/apiMocks.ts';

test('compact viewport keeps the project workspace available', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, (route) => json(route, []));
  await page.setViewportSize({ width: 899, height: 800 });
  await page.goto('/projects');

  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible();
  await expect(page.getByRole('button', { name: '+ New Project' })).toBeVisible();
  await expect(page.getByText('A larger screen is recommended for editing workflows.')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();

  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
});
