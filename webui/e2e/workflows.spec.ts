import { expect, test, type Page, type Route } from '@playwright/test';

const project = {
  id: 'p1',
  name: 'Browser Project',
  description: '',
  flow_id: 'flow-1',
  package_path: '/projects/p1.fnirsflow',
  storage_format: 'fnirsflow_bundle',
  revision: 3,
  integrity_status: 'verified',
};
const readiness = {
  flow_saved: true,
  validated: true,
  compiled: true,
  data_discovered: true,
  runnable_runs: 1,
  executed: false,
  flow_hash: 'flow-hash',
  compiled_flow_hash: 'flow-hash',
  last_attempt_id: '',
  last_execution_status: '',
  read_only: false,
  quarantined_atoms: [],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function installProjectApi(page: Page, flowState: { value: Record<string, unknown> }) {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') return json(route, flowState.value);
    if (path === '/api/projects/p1/flow' && request.method() === 'PUT') {
      flowState.value = request.postDataJSON().flow;
      return json(route, { status: 'updated' });
    }
    if (path === '/api/projects/p1/status') return json(route, readiness);
    if (path === '/api/projects/p1/import-status') {
      return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    }
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
    return json(route, {});
  });
}

test('parameter edits persist across save and browser refresh', async ({ page }) => {
  const flowState = {
    value: {
      flow_id: 'flow-1',
      nodes: [
        {
          id: 'filter-1',
          atom_type: 'filtering',
          operation: 'filtering',
          category: 'preprocessing',
          position: { x: 100, y: 100 },
          config: { high_pass: 0.01 },
        },
      ],
      edges: [],
    },
  };
  await installProjectApi(page, flowState);
  await page.goto('/projects/p1/flow');

  await page.getByText('filtering', { exact: true }).click();
  await page.getByRole('button', { name: /Parameters/ }).click();
  const input = page.locator('.param-row').filter({ hasText: 'high_pass' }).locator('input');
  await input.fill('0.02');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();
  expect(((flowState.value.nodes as Array<Record<string, unknown>>)[0].config as Record<string, unknown>).high_pass).toBe(0.02);

  await page.reload();
  await page.getByText('filtering', { exact: true }).click();
  await page.getByRole('button', { name: /Parameters/ }).click();
  await expect(page.locator('.param-row').filter({ hasText: 'high_pass' }).locator('input')).toHaveValue('0.02');
});

test('imported package can be relinked, trusted, and forked', async ({ page }) => {
  let imported = false;
  let quarantined = ['custom-glm'];
  let relinked = false;
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/projects/p1/flow') return json(route, { flow_id: 'flow-1', nodes: [], edges: [] });
    if (path === '/api/projects/p1/status') return json(route, { ...readiness, read_only: imported });
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
    if (path === '/api/projects/p1/import-package' && request.method() === 'POST') {
      imported = true;
      return json(route, { status: 'imported' });
    }
    if (path === '/api/projects/p1/import-status') {
      return json(route, {
        imported,
        read_only: imported,
        quarantined_atoms: quarantined,
        relinked,
        data_root: relinked ? '/data/ds007738' : '',
      });
    }
    if (path === '/api/projects/p1/relink-data' && request.method() === 'POST') {
      relinked = true;
      return json(route, { status: 'relinked', data_root: '/data/ds007738' });
    }
    if (path === '/api/projects/p1/trust-atom/custom-glm' && request.method() === 'POST') {
      quarantined = [];
      return json(route, { status: 'trusted' });
    }
    if (path === '/api/projects/p1/fork' && request.method() === 'POST') {
      return json(route, { fork_project_id: 'fork-1' });
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/import');
  await page.getByLabel('Package Path').fill('/packages/analysis.fnirsflow.zip');
  await page.locator('.import-form').filter({ has: page.getByLabel('Package Path') })
    .getByRole('button', { name: 'Import' }).click();
  await expect(page.getByText('Read-Only Package')).toBeVisible();

  await page.getByLabel('Data Root').fill('/data/ds007738');
  await page.getByRole('button', { name: 'Relink' }).click();
  await expect(page.getByText('Linked to /data/ds007738')).toBeVisible();

  await page.locator('.quarantine-item').getByRole('button', { name: 'Trust' }).click();
  await expect(page.locator('.quarantine-item')).toHaveCount(0);

  await page.getByRole('button', { name: 'Fork to Editable Copy' }).click();
  await expect(page.getByText('Fork created')).toBeVisible();
  await expect(page.getByText('New project: fork-1')).toBeVisible();
});

test('project version history requires confirmation and refreshes after restore', async ({ page }) => {
  let currentRevision = 3;
  let restoreRequests = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') {
      return json(route, [{ ...project, revision: currentRevision }]);
    }
    if (path === '/api/projects/p1/version-history' && request.method() === 'GET') {
      return json(route, [
        { revision: currentRevision, saved_at: '2026-07-14T08:00:00Z', reason: 'current', current: true, path: '' },
        { revision: 2, saved_at: '2026-07-13T08:00:00Z', reason: 'flow_saved', current: false, path: '' },
      ]);
    }
    if (path === '/api/projects/p1/bundle/restore/2' && request.method() === 'POST') {
      restoreRequests += 1;
      currentRevision = 4;
      return json(route, { ...project, revision: currentRevision });
    }
    return json(route, {});
  });

  await page.goto('/projects');
  await page.getByRole('button', { name: /Browser Project/ }).click();
  await expect(page.getByText('Version History')).toBeVisible();
  await page.getByRole('button', { name: 'Restore' }).click();

  await expect(page.getByRole('alertdialog', { name: 'Restore revision 2' })).toBeVisible();
  expect(restoreRequests).toBe(0);

  await page.getByRole('button', { name: 'Confirm restore' }).click();
  await expect(page.getByRole('status')).toHaveText('Revision 2 restored as revision 4.');
  await expect(page.getByText('Verified .fnirsflow bundle · revision 4')).toBeVisible();
  expect(restoreRequests).toBe(1);
});
