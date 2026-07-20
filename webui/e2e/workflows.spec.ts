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

const completedExecutionResult = {
  attempt_id: 'attempt-1',
  total_runs: 1,
  successful: 1,
  failed: 0,
  failure_ids: [],
  runs: [{
    run_id: 'sub-01_task-tapping',
    status: 'completed',
    subject: 'sub-01',
    session: '',
    run: '01',
    started_at: '2026-07-18T10:00:00Z',
    completed_at: '2026-07-18T10:01:00Z',
    atom_results: [
      {
        atom_id: 'dataset_discovery',
        status: 'skipped',
        output_handles: {},
        artifacts: [],
        warnings: ['Run-scope execution skips project-scope dataset discovery.'],
      },
      {
        atom_id: 'channel_output',
        status: 'completed',
        output_handles: { result: 'dict' },
        warnings: [],
        artifacts: [{
          artifact_id: 'a1',
          type: 'json',
          uri: 'project://outputs/derivatives/channel/sub-01_channel_results.json',
          path: 'outputs/derivatives/channel/sub-01_channel_results.json',
          resolved_path: '/tmp/sub-01_channel_results.json',
          relative_path: 'derivatives/channel/sub-01_channel_results.json',
          checksum: 'abc123',
          exists: true,
          atom_id: 'channel_output',
          step_id: 'channel_output',
        }],
      },
    ],
    artifacts: [{
      artifact_id: 'a1',
      type: 'json',
      uri: 'project://outputs/derivatives/channel/sub-01_channel_results.json',
      path: 'outputs/derivatives/channel/sub-01_channel_results.json',
      resolved_path: '/tmp/sub-01_channel_results.json',
      relative_path: 'derivatives/channel/sub-01_channel_results.json',
      checksum: 'abc123',
      exists: true,
      atom_id: 'channel_output',
      step_id: 'channel_output',
    }],
  }],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function installProjectApi(
  page: Page,
  flowState: { value: Record<string, unknown> },
  examples: Array<{ id: string; label: string; flow: Record<string, unknown> }> = []
) {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/example-flows' && request.method() === 'GET') {
      return json(route, examples.map(({ id, label }) => ({ id, label })));
    }
    const exampleMatch = path.match(/^\/api\/example-flows\/([^/]+)$/);
    if (exampleMatch && request.method() === 'GET') {
      const example = examples.find((item) => item.id === exampleMatch[1]);
      return json(route, example?.flow || {}, example ? 200 : 404);
    }
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

test('project creation accepts a typed local data folder path', async ({ page }) => {
  let createdBody: Record<string, unknown> | null = null;
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, []);
    if (path === '/api/projects' && request.method() === 'POST') {
      createdBody = request.postDataJSON();
      return json(route, {
        ...project,
        id: 'typed-data-root',
        name: String(createdBody?.name || ''),
        description: String(createdBody?.description || ''),
        data_root: String(createdBody?.data_root || ''),
      });
    }
    if (path === '/api/projects/typed-data-root' && request.method() === 'GET') {
      return json(route, { ...project, id: 'typed-data-root', data_root: String(createdBody?.data_root || '') });
    }
    if (path === '/api/projects/typed-data-root/flow') return json(route, { flow_id: 'flow-typed', nodes: [], edges: [] });
    if (path === '/api/projects/typed-data-root/status') return json(route, readiness);
    if (path === '/api/projects/typed-data-root/import-status') {
      return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    }
    if (path === '/api/projects/typed-data-root/attempts') return json(route, []);
    if (path === '/api/projects/typed-data-root/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
    if (path === '/api/atom-templates') return json(route, []);
    return json(route, {});
  });

  await page.goto('/projects');
  await page.getByRole('button', { name: '+ New Project' }).click();
  await page.getByPlaceholder('Project name').fill('Typed Root Project');
  await page.getByLabel('Data folder path').fill('E:/data/bids-nirs-tapping');
  await expect(page.getByText('Data folder ready')).toBeVisible();
  await page.getByRole('button', { name: 'Create' }).click();

  await expect(page).toHaveURL(/\/projects\/typed-data-root\/flow$/);
  expect(createdBody?.data_root).toBe('E:/data/bids-nirs-tapping');
});

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
          config: { high_pass: 0.01, method: 'fir | iir' },
          parameter_specs: { high_pass: { minimum: 0, maximum: 0.5 } },
        },
      ],
      edges: [],
    },
  };
  await installProjectApi(page, flowState);
  await page.goto('/projects/p1/flow');

  await page.getByText('filtering', { exact: true }).click();
  await page.getByRole('button', { name: /Parameters/ }).click();
  const highPassRow = page.locator('.param-row').filter({ hasText: 'high_pass' });
  await expect(highPassRow.getByText('Range:')).toBeVisible();
  const methodRow = page.locator('.param-row').filter({ hasText: 'method' });
  await expect(methodRow.locator('select')).toBeVisible();
  await methodRow.locator('select').selectOption('iir');
  const input = highPassRow.locator('input');
  await input.fill('0.02');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();
  expect(((flowState.value.nodes as Array<Record<string, unknown>>)[0].config as Record<string, unknown>).high_pass).toBe(0.02);
  expect(((flowState.value.nodes as Array<Record<string, unknown>>)[0].config as Record<string, unknown>).method).toBe('iir');

  await page.reload();
  await page.getByText('filtering', { exact: true }).click();
  await page.getByRole('button', { name: /Parameters/ }).click();
  await expect(page.locator('.param-row').filter({ hasText: 'high_pass' }).locator('input')).toHaveValue('0.02');
});

test('example flow replaces the current canvas instead of appending atoms', async ({ page }) => {
  const flowState = {
    value: {
      flow_id: 'flow-1',
      nodes: [
        {
          id: 'existing-filter',
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
  await installProjectApi(page, flowState, [
    {
      id: 'blank_template',
      label: 'Blank Template',
      flow: {
        schema_version: '0.3.0',
        flow_id: 'blank-template',
        nodes: [],
        flow_atoms: [],
        edges: [],
        metadata: { checklist: {} },
      },
    },
  ]);
  await page.goto('/projects/p1/flow');

  await expect(page.getByText('filtering', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Blank Template' }).click();
  await expect(page.getByText('filtering', { exact: true })).toHaveCount(0);
  await expect(page.getByText('0 atoms')).toBeVisible();
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
  let forkFlowRequests = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/projects/p1/flow') return json(route, { flow_id: 'flow-1', nodes: [], edges: [] });
    if (path === '/api/projects/fork-1' && request.method() === 'GET') return json(route, {
      ...project,
      id: 'fork-1',
      name: 'Editable Copy',
      flow_id: 'fork-flow-1',
    });
    if (path === '/api/projects/fork-1/flow') {
      forkFlowRequests += 1;
      return json(route, { flow_id: 'fork-flow-1', nodes: [], edges: [] });
    }
    if (path === '/api/projects/fork-1/status') return json(route, { ...readiness, read_only: false });
    if (path === '/api/projects/fork-1/import-status') {
      return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    }
    if (path === '/api/projects/fork-1/attempts') return json(route, []);
    if (path === '/api/projects/fork-1/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
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
  await expect(page).toHaveURL(/\/projects\/fork-1\/flow$/);
  await expect.poll(() => forkFlowRequests).toBeGreaterThan(0);
});

test('run monitor page actions work under toast overlay and atom rows expand', async ({ page }) => {
  let dryRunRequests = 0;
  let executeRequests = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') {
      return json(route, { flow_id: 'flow-1', nodes: [], edges: [] });
    }
    if (path === '/api/projects/p1/status') return json(route, readiness);
    if (path === '/api/projects/p1/import-status') {
      return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    }
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
    if (path === '/api/projects/p1/validate' && request.method() === 'POST') {
      return json(route, { is_valid: true, errors: [], warnings: [], risks: [] });
    }
    if (path === '/api/projects/p1/dry-run' && request.method() === 'POST') {
      dryRunRequests += 1;
      return json(route, {
        total_runs: 1,
        status: 'ok',
        summary: {},
        planned_runs: [{
          run_id: 'sub-01_task-tapping_run-01',
          status: 'planned',
          subject: 'sub-01',
          session: '',
          run: '01',
          started_at: '',
          completed_at: '',
        }],
      });
    }
    if (path === '/api/projects/p1/execute' && request.method() === 'POST') {
      executeRequests += 1;
      return json(route, {
        attempt_id: 'attempt-1',
        project_id: 'p1',
        status: 'completed',
        created_at: '2026-07-18T10:00:00Z',
        started_at: '2026-07-18T10:00:00Z',
        completed_at: '2026-07-18T10:01:00Z',
        recovery_count: 0,
        cancel_requested: false,
        result: completedExecutionResult,
      }, 202);
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/runs');
  await page.getByRole('button', { name: 'Validate flow' }).click();
  await expect(page.getByText('Validation passed')).toBeVisible();
  await page.getByRole('button', { name: 'Dry run project' }).click();

  expect(dryRunRequests).toBe(1);
  await expect(page.getByText('sub-01_task-tapping_run-01')).toBeVisible();
  await expect(page.locator('.status-chip.planned')).toBeVisible();

  await page.getByRole('button', { name: 'Execute project' }).click();
  expect(executeRequests).toBe(1);
  await expect(page.getByText('Execution Summary')).toBeVisible();
  await expect(page.getByText('sub-01_task-tapping')).toBeVisible();

  await page.getByRole('button', { name: 'Show atom details for sub-01_task-tapping' }).click();
  await expect(page.locator('.atom-results-row')).toBeVisible();
  await expect(page.locator('.atom-result-card').filter({ hasText: 'channel_output' })).toBeVisible();
});

test('results tabs show their selected backend result panes', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') return json(route, { flow_id: 'flow-1', nodes: [], edges: [] });
    if (path === '/api/projects/p1/status') return json(route, { ...readiness, executed: true });
    if (path === '/api/projects/p1/import-status') return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    if (path === '/api/projects/p1/attempts') {
      return json(route, [{
        attempt_id: 'attempt-1',
        project_id: 'p1',
        status: 'completed',
        created_at: '2026-07-18T10:00:00Z',
        started_at: '2026-07-18T10:00:00Z',
        completed_at: '2026-07-18T10:01:00Z',
        recovery_count: 0,
        cancel_requested: false,
        result: completedExecutionResult,
      }]);
    }
    if (path === '/api/projects/p1/progress') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    }
    if (path === '/api/projects/p1/results/qc') {
      return json(route, { kind: 'qc', file_count: 1, files: [{ path: 'qc.json', data: { summaries: [{ metric: 'sci', value: 0.98 }] } }], figures: [] });
    }
    if (path === '/api/projects/p1/results/channel') {
      return json(route, { kind: 'channel', file_count: 1, files: [{ path: 'channel.json', data: [{ channel: 'channel_0', beta: 1.2 }] }], figures: [] });
    }
    if (path === '/api/projects/p1/results/roi') {
      return json(route, { kind: 'roi', file_count: 0, files: [], figures: [] });
    }
    if (path === '/api/projects/p1/results/group') {
      return json(route, { kind: 'group', file_count: 1, files: [{ path: 'group.json', data: { summaries: [{ id_column: 'participant_id', group_column: 'sex' }] } }], figures: [] });
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/results');
  await expect(page.getByText('Atom derivative locations')).toBeVisible();

  await page.getByRole('button', { name: 'QC Results' }).click();
  await expect(page.getByRole('heading', { name: 'QC Results' })).toBeVisible();
  await expect(page.getByText('sci')).toBeVisible();
  await expect(page.getByText('Atom derivative locations')).toHaveCount(0);

  await page.getByRole('button', { name: 'ROI' }).click();
  await expect(page.getByRole('heading', { name: 'ROI Results' })).toBeVisible();
  await expect(page.getByText('No ROI result files are available. This can happen when the selected demo flow completes channel and group summaries without ROI-level exports.')).toBeVisible();

  await page.getByRole('button', { name: 'Channel' }).click();
  await expect(page.getByRole('heading', { name: 'Channel Results' })).toBeVisible();
  await expect(page.getByText('channel_0')).toBeVisible();

  await page.getByRole('button', { name: 'Group' }).click();
  await expect(page.getByRole('heading', { name: 'Group Summary' })).toBeVisible();
  await expect(page.getByText('participant_id')).toBeVisible();
  await expect(page.getByText('sex')).toBeVisible();
});

test('export package success shows the generated package path', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') return json(route, { flow_id: 'flow-1', nodes: [], edges: [] });
    if (path === '/api/projects/p1/status') return json(route, readiness);
    if (path === '/api/projects/p1/import-status') return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    if (path === '/api/package-profiles') {
      return json(route, [{
        profile_id: 'reproducibility_package',
        name: 'Reproducibility Package',
        description: 'Full package',
        include_patterns: ['plan.json'],
      }]);
    }
    if (path === '/api/projects/p1/export-package' && request.method() === 'POST') {
      return json(route, {
        package_path: '/tmp/p1.fnirsflow.zip',
        size_bytes: 11264,
        profile: 'reproducibility_package',
        contents: ['plan.json', 'flow.json'],
      });
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/package');
  await page.getByRole('button', { name: 'Export Package' }).click();
  await expect(page.getByRole('status')).toContainText('Package exported successfully!');
  await expect(page.getByText('/tmp/p1.fnirsflow.zip')).toBeVisible();
  await expect(page.getByText('11 KB')).toBeVisible();
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
  await expect(page.getByText('Candidate summary')).toBeVisible();
  expect(flowState.value.flow_id).toBe('flow-1');

  await page.getByRole('button', { name: 'Validate draft' }).click();
  await expect(page.getByText('AI_CONFIRMATION_REQUIRED')).toBeVisible();
  await page.getByRole('button', { name: /^3 Review$/ }).click();
  await expect(page.getByText('Diff from current flow')).toBeVisible();
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

test('flow checklist recommends, builds, skips, persists, and links validation risks', async ({ page }) => {
  const taskGlmChecklist = {
    scenario_id: 'task_glm',
    label: 'Task GLM',
    description: 'Guided task GLM flow.',
    version: 'e2e',
    steps: [
      {
        slot_id: 'data_input',
        label: 'Data input',
        required: true,
        recommended_template_ids: ['dataset_discovery'],
        recommended_atom_types: ['dataset_discovery'],
        default_template_id: 'dataset_discovery',
        alternative_template_ids: [],
        input_requirements: [],
        depends_on: [],
        allow_empty_marker: false,
        category: 'data',
        guidance: 'Discover files.',
      },
      {
        slot_id: 'read_run',
        label: 'Read run',
        required: true,
        recommended_template_ids: ['read_run'],
        recommended_atom_types: ['read_run'],
        default_template_id: 'read_run',
        alternative_template_ids: [],
        input_requirements: ['DataManifest'],
        depends_on: ['data_input'],
        allow_empty_marker: false,
        category: 'data',
        guidance: 'Read runs.',
      },
      {
        slot_id: 'quality_control',
        label: 'Quality control',
        required: false,
        recommended_template_ids: ['qc_metrics', 'sci_check'],
        recommended_atom_types: ['signal_qc'],
        default_template_id: 'qc_metrics',
        alternative_template_ids: ['sci_check'],
        input_requirements: ['RawData'],
        depends_on: ['read_run'],
        allow_empty_marker: false,
        category: 'validation',
        guidance: 'Review quality.',
      },
      {
        slot_id: 'filtering',
        label: 'Filtering',
        required: false,
        recommended_template_ids: ['bandpass_filter'],
        recommended_atom_types: ['filter'],
        default_template_id: 'bandpass_filter',
        alternative_template_ids: [],
        input_requirements: ['RawData'],
        depends_on: ['read_run'],
        allow_empty_marker: true,
        category: 'preprocessing',
        guidance: 'Filter or mark as reviewed empty processing.',
      },
    ],
  };
  const mlChecklist = {
    ...taskGlmChecklist,
    scenario_id: 'ml_classification',
    label: 'ML Classification',
    description: 'Guided ML flow.',
    steps: [{
      ...taskGlmChecklist.steps[0],
      slot_id: 'model',
      label: 'Model',
      recommended_template_ids: ['ml_model'],
      recommended_atom_types: ['ml_classification'],
      default_template_id: 'ml_model',
      guidance: 'Train model.',
    }],
  };
  const summaries = [
    { scenario_id: 'task_glm', label: 'Task GLM', description: 'Guided task GLM flow.', version: 'e2e', step_count: 4 },
    { scenario_id: 'ml_classification', label: 'ML Classification', description: 'Guided ML flow.', version: 'e2e', step_count: 1 },
  ];
  const templates = [
    {
      id: 'dataset_discovery',
      atom_type: 'dataset_discovery',
      display_name: 'Dataset discovery',
      category: 'data',
      operation: 'dataset_discovery',
      description: 'Discover data',
      input_ports: [],
      output_ports: [{ name: 'manifest', schema: 'DataManifest', required: true }],
      evidence_refs: [],
    },
    {
      id: 'read_run',
      atom_type: 'read_run',
      display_name: 'Read run',
      category: 'data',
      operation: 'read_run',
      description: 'Read run',
      input_ports: [{ name: 'manifest', schema: 'DataManifest', required: true }],
      output_ports: [{ name: 'raw', schema: 'RawData', required: true }],
      evidence_refs: [],
    },
    {
      id: 'qc_metrics',
      atom_type: 'signal_qc',
      display_name: 'QC metrics',
      category: 'validation',
      operation: 'qc_metrics',
      description: 'QC',
      input_ports: [{ name: 'raw', schema: 'RawData', required: true }],
      output_ports: [{ name: 'qc', schema: 'QCReport', required: true }],
      evidence_refs: [],
    },
    {
      id: 'sci_check',
      atom_type: 'signal_qc',
      display_name: 'SCI check',
      category: 'validation',
      operation: 'sci_check',
      description: 'SCI',
      input_ports: [{ name: 'raw', schema: 'RawData', required: true }],
      output_ports: [{ name: 'sci', schema: 'FloatArray', required: true }],
      evidence_refs: [],
    },
    {
      id: 'ml_model',
      atom_type: 'ml_classification',
      display_name: 'ML model',
      category: 'analysis',
      operation: 'ml_model',
      description: 'ML',
      input_ports: [],
      output_ports: [],
      evidence_refs: [],
    },
  ];
  const emptySpecs = [{
    category: 'preprocessing',
    input_schema: 'RawData',
    output_schema: 'RawData',
    label: 'Empty preprocessing',
    atom_id: 'empty_preprocessing',
    template_id: 'empty_preprocessing',
  }];
  const flowState = {
    value: {
      flow_id: 'flow-1',
      nodes: [{
        id: 'model-1',
        atom_type: 'ml_classification',
        template_id: 'ml_model',
        operation: 'ml_model',
        category: 'analysis',
        position: { x: 50, y: 50 },
        ports: [],
      }],
      edges: [],
      metadata: {},
    } as Record<string, unknown>,
  };

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/projects/p1/flow' && request.method() === 'GET') return json(route, flowState.value);
    if (path === '/api/projects/p1/flow' && request.method() === 'PUT') {
      flowState.value = request.postDataJSON().flow;
      return json(route, { status: 'updated' });
    }
    if (path === '/api/projects/p1/status') return json(route, readiness);
    if (path === '/api/projects/p1/import-status') return json(route, { imported: false, read_only: false, quarantined_atoms: [] });
    if (path === '/api/projects/p1/attempts') return json(route, []);
    if (path === '/api/projects/p1/progress') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    if (path === '/api/atom-templates') return json(route, templates);
    if (path === '/api/empty-marker-specs') return json(route, emptySpecs);
    if (path === '/api/flow-checklists') return json(route, summaries);
    if (path === '/api/flow-checklists/task_glm') return json(route, taskGlmChecklist);
    if (path === '/api/flow-checklists/ml_classification') return json(route, mlChecklist);
    if (path === '/api/projects/p1/validate' && request.method() === 'POST') {
      return json(route, {
        is_valid: true,
        errors: [],
        warnings: [],
        risks: [{
          risk_id: 'checklist-empty-task_glm-filtering',
          code: 'CHECKLIST_STEP_EMPTY_MARKER',
          severity: 'low',
          domain: 'design',
          affected_object: 'checklist:filtering',
          message: "Checklist step 'Filtering' is marked as empty/no-op",
          suggested_action: 'Replace with real processing when available',
        }],
      });
    }
    return json(route, {});
  });

  await page.goto('/projects/p1/flow');
  await expect(page.getByLabel('Scenario')).toHaveValue('ml_classification');
  await page.locator('.checklist-step').filter({ hasText: 'Model' }).click();
  await expect(page.locator('.atom-item.checklist-recommended')).toContainText('ML model');
  await expect(page.locator('.atom-item').filter({ hasText: 'ML model' })).toContainText('Best fit');
  await expect(page.getByLabel('Checklist progress')).toContainText('100%');

  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();
  expect((flowState.value.metadata as Record<string, any>).checklist.scenario_id).toBe('ml_classification');
  expect((flowState.value.metadata as Record<string, any>).checklist.recommendation_source).toBe('flow_atoms');

  await page.getByLabel('Scenario').selectOption('task_glm');
  await expect(page.getByLabel('Checklist progress')).toContainText('0%');
  await expect(page.locator('.checklist-next-action')).toContainText('Next: Add Data input');
  await expect(page.locator('.checklist-step.priority')).toContainText('Data input');
  await page.locator('.checklist-step').filter({ hasText: 'Quality control' }).click();
  await expect(page.locator('.atom-item').filter({ hasText: 'QC metrics' })).toContainText('Best fit');
  await expect(page.locator('.atom-item').filter({ hasText: 'QC metrics' })).toContainText('Default for this step');
  await expect(page.locator('.atom-item').filter({ hasText: 'SCI check' })).toContainText('Recommended');
  await expect(page.locator('.atom-item').filter({ hasText: 'SCI check' })).toContainText('Matches this processing slot');
  await page.locator('.checklist-step').filter({ hasText: 'Quality control' }).locator('select').selectOption('sci_check');
  await page.getByRole('button', { name: 'Add missing' }).click();
  await expect(page.locator('.checklist-preview')).toContainText('Add 3 atoms');
  await page.locator('.checklist-preview').getByRole('button', { name: 'Apply' }).click();
  await expect(page.getByRole('status')).toContainText('Connected 2 links');
  await page.getByRole('button', { name: 'Add missing' }).click();
  await expect(page.locator('.checklist-preview')).toContainText('No new atoms are needed');
  await page.locator('.checklist-preview').getByRole('button', { name: 'Cancel' }).click();
  await page.locator('.checklist-step').filter({ hasText: 'Filtering' }).locator('.checklist-skip-reason select')
    .selectOption('method_not_needed');
  await page.locator('.checklist-step').filter({ hasText: 'Filtering' }).getByRole('button', { name: 'Skip' }).click();
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();

  const savedFlow = flowState.value as Record<string, any>;
  expect(savedFlow.metadata.checklist.scenario_id).toBe('task_glm');
  expect(savedFlow.metadata.checklist.choices.quality_control.template_id).toBe('sci_check');
  expect(savedFlow.metadata.checklist.choices.filtering.skipped).toBe(true);
  expect(savedFlow.metadata.checklist.choices.filtering.skip_reason).toBe('method_not_needed');
  expect(savedFlow.metadata.order_policy.allow_empty_edges).toBe(true);
  const emptyAtom = savedFlow.nodes.find((node: Record<string, unknown>) => node.id === 'empty_preprocessing');
  expect(emptyAtom).toBeTruthy();
  expect(emptyAtom.metadata.skip_reason).toBe('method_not_needed');
  expect(savedFlow.edges.some((edge: Record<string, unknown>) => edge.source === 'dataset_discovery_2' && edge.target === 'read_run_3')).toBe(true);
  expect(savedFlow.edges.some((edge: Record<string, unknown>) => edge.source === 'read_run_3' && edge.target === 'sci_check_4')).toBe(true);

  await page.getByRole('button', { name: 'Validate' }).click();
  await expect(page.getByText('CHECKLIST_STEP_EMPTY_MARKER')).toBeVisible();
  await page.getByText("Checklist step 'Filtering' is marked as empty/no-op").click();
  await expect(page.locator('.checklist-step.selected')).toContainText('Filtering');

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Report' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('task_glm_checklist_report.json');

  await page.getByRole('button', { name: 'Empty risk' }).click();
  await expect(page.getByRole('dialog', { name: 'Disable Empty risk' })).toContainText('Remove 1 empty atom');
  await page.getByRole('dialog', { name: 'Disable Empty risk' }).getByRole('button', { name: 'Apply' }).click();
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Flow saved')).toBeVisible();
  expect((flowState.value as Record<string, any>).metadata.order_policy.allow_empty_edges).toBe(false);
  expect((flowState.value as Record<string, any>).metadata.checklist.choices.filtering.skipped).toBeUndefined();
  expect((flowState.value as Record<string, any>).nodes.some((node: Record<string, unknown>) => node.id === 'empty_preprocessing')).toBe(false);
});
