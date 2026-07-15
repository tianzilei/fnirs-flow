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

test('selected canvas node can be deleted with keyboard', async ({ page }) => {
  const flowState = {
    value: {
      flow_id: 'flow-1',
      nodes: [
        {
          id: 'loader-1',
          atom_type: 'load_snirf',
          operation: 'load_snirf',
          category: 'data',
          position: { x: 0, y: 0 },
          output_ports: [{ name: 'raw', schema: 'RawNIRS' }],
        },
        {
          id: 'filter-1',
          atom_type: 'filtering',
          operation: 'filtering',
          category: 'preprocessing',
          position: { x: 180, y: 0 },
          input_ports: [{ name: 'raw', schema: 'RawNIRS' }],
          output_ports: [{ name: 'filtered', schema: 'RawNIRS' }],
        },
      ],
      edges: [{ id: 'edge-1', source: 'loader-1', target: 'filter-1' }],
    },
  };
  await installProjectApi(page, flowState);
  await page.goto('/projects/p1/flow?node=filter-1');

  await expect(page.locator('.canvas-status-pill')).toContainText('2 atoms');
  await expect(page.locator('.canvas-status-pill')).toContainText('1 links');
  await expect(page.locator('.inspection-panel')).toBeVisible();

  await page.keyboard.press('Delete');

  await expect(page.getByText('filtering', { exact: true })).toHaveCount(0);
  await expect(page.locator('.canvas-status-pill')).toContainText('1 atoms');
  await expect(page.locator('.canvas-status-pill')).toContainText('0 links');

  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();
  expect((flowState.value.nodes as Array<Record<string, unknown>>).map((node) => node.id)).toEqual(['loader-1']);
  expect(flowState.value.edges).toEqual([]);
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
  await expect(page.getByRole('heading', { name: 'Bundle Recovery' })).toBeVisible();
  await page.getByRole('button', { name: 'Restore' }).click();

  await expect(page.getByRole('alertdialog', { name: 'Restore revision 2' })).toBeVisible();
  expect(restoreRequests).toBe(0);

  await page.getByRole('button', { name: 'Confirm restore' }).click();
  await expect(page.getByRole('status')).toHaveText('Revision 2 restored as revision 4.');
  await expect(page.getByText('Verified .fnirsflow bundle · revision 4')).toBeVisible();
  expect(restoreRequests).toBe(1);
});

test('AI draft review isolates, validates, confirms, and discards candidates', async ({ page }) => {
  const originalFlow = {
    flow_id: 'flow-1',
    nodes: [{
      id: 'filter-1', atom_type: 'filtering', operation: 'filtering', category: 'preprocessing',
      position: { x: 100, y: 100 }, config: { high_pass: 0.01 },
    }],
    edges: [],
  };
  const draftFlow = {
    flow_id: 'draft-task-1234',
    name: 'Browser Project AI Draft',
    description: 'Candidate task flow requiring human review.',
    nodes: [
      { id: 'n_optical_density', type: 'optical_density', category: 'preprocessing', position: { x: 100, y: 100 }, ports: [] },
      { id: 'n_design_matrix', type: 'design_matrix', category: 'design', position: { x: 300, y: 100 }, ports: [] },
    ],
    edges: [],
    metadata: {
      ai_generation: {
        generated_by: 'generative_ai', model: 'api_template', created_at: '2026-07-15T00:00:00Z',
        input_summary: 'Scenario: task, format: snirf', assumptions: ['Data format: snirf', 'Scenario: Task GLM'],
        requires_user_confirmation: ['filtering: confirm parameters', 'design_matrix: confirm parameters'],
        confirmed_parameters: [], confirmed_by: '', confirmed_at: '', not_used_for_execution: true,
      },
    },
  };
  const flowState: { value: Record<string, unknown> } = { value: originalFlow };
  let pendingDraft: typeof draftFlow | null = null;
  let confirmationBody: Record<string, unknown> | null = null;

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') return json(route, flowState.value);
    if (path === '/api/projects/p1/status') return json(route, readiness);
    if (path === '/api/projects/p1/import-status') return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    if (path === '/api/projects/p1/ai/draft' && request.method() === 'GET') {
      return pendingDraft ? json(route, { status: 'draft_exists', draft: pendingDraft }) : json(route, { detail: 'No pending draft' }, 404);
    }
    if (path === '/api/projects/p1/ai/draft-flow' && request.method() === 'POST') {
      pendingDraft = structuredClone(draftFlow);
      return json(route, { status: 'draft_pending', flow_id: pendingDraft.flow_id });
    }
    if (path === '/api/projects/p1/ai/validate-draft' && request.method() === 'POST') {
      return json(route, {
        status: 'draft_validated', flow_id: draftFlow.flow_id, valid: true, errors: [], warnings: [],
        risks: [{
          risk_id: 'ai-confirm', code: 'AI_CONFIRMATION_REQUIRED', severity: 'fatal', domain: 'reproducibility',
          message: 'High-impact parameters require confirmation.', suggested_action: 'Review every item.',
        }],
        readiness: { status: 'Blocked', checks: [] },
      });
    }
    if (path === '/api/projects/p1/ai/confirm-draft' && request.method() === 'POST') {
      confirmationBody = request.postDataJSON();
      if (pendingDraft) {
        pendingDraft.metadata.ai_generation.confirmed_parameters = confirmationBody?.confirmed_parameters as string[];
        pendingDraft.metadata.ai_generation.confirmed_by = String(confirmationBody?.confirmed_by);
        flowState.value = pendingDraft;
        pendingDraft = null;
      }
      return json(route, { status: 'draft_confirmed', flow_id: draftFlow.flow_id, confirmed_count: 2 });
    }
    if (path === '/api/projects/p1/ai/draft' && request.method() === 'DELETE') {
      pendingDraft = null;
      return json(route, { status: 'draft_discarded' });
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/flow');
  await page.getByRole('button', { name: 'AI Draft' }).click();
  await expect(page.getByRole('heading', { name: 'AI Draft Review' })).toBeVisible();
  await page.getByRole('button', { name: 'Generate draft' }).click();
  await expect(page.getByText('Draft generated in isolation. The current flow is unchanged.')).toBeVisible();
  await expect(page.getByText('Diff from current flow')).toBeVisible();
  expect(flowState.value.flow_id).toBe('flow-1');

  await page.getByRole('button', { name: 'Validate draft' }).click();
  await expect(page.getByText('AI_CONFIRMATION_REQUIRED')).toBeVisible();
  const confirmations = page.locator('.confirmation-item input[type="checkbox"]');
  await expect(confirmations).toHaveCount(2);
  await confirmations.nth(0).check();
  await confirmations.nth(1).check();
  await page.getByLabel('Reviewer').fill('reviewer@example.org');
  await page.getByRole('button', { name: 'Apply reviewed draft' }).click();
  await expect(page.getByRole('alertdialog', { name: 'Apply AI draft' })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm apply' }).click();
  await expect(page.getByText('Reviewed draft applied to the current flow. Validate before compiling.')).toBeVisible();
  expect(flowState.value.flow_id).toBe(draftFlow.flow_id);
  expect(confirmationBody?.confirmed_by).toBe('reviewer@example.org');

  await page.getByRole('button', { name: 'Generate draft' }).click();
  await page.getByRole('button', { name: 'Discard' }).click();
  await expect(page.getByRole('alertdialog', { name: 'Discard AI draft' })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm discard' }).click();
  await expect(page.getByText('Pending AI draft discarded. The current flow was not changed.')).toBeVisible();
  expect(pendingDraft).toBeNull();
  expect(flowState.value.flow_id).toBe(draftFlow.flow_id);
});
