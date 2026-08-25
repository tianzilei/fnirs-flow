import type { Page, Route } from '@playwright/test';

export const project = {
  id: 'p1',
  name: 'Browser Project',
  description: '',
  flow_id: 'flow-1',
  package_path: '/projects/p1.fnirsflow',
  storage_format: 'fnirsflow_bundle',
  revision: 3,
  integrity_status: 'verified',
};

export const readiness = {
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

export const completedExecutionResult = {
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

export function apiPath(route: Route): string {
  return new URL(route.request().url()).pathname;
}

export function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

export function eventStream(route: Route) {
  return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
}

type FlowState = { value: Record<string, unknown> };
type ExampleFlow = { id: string; label: string; flow: Record<string, unknown> };

export async function installProjectApi(
  page: Page,
  flowState: FlowState,
  examples: ExampleFlow[] = [],
) {
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = apiPath(route);
    if (path === '/api/projects' && request.method() === 'GET') return json(route, [project]);
    if (path === '/api/atom-templates') return json(route, []);
    if (path === '/api/example-flows' && request.method() === 'GET') {
      return json(route, examples.map(({ id, label }) => ({ id, label })));
    }
    const exampleMatch = path.match(/^\/api\/example-flows\/([^/]+)$/);
    if (exampleMatch && request.method() === 'GET') {
      const example = examples.find((item) => item.id === exampleMatch[1]);
      return json(route, example?.flow ?? {}, example ? 200 : 404);
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
    if (path === '/api/projects/p1/progress') return eventStream(route);
    return json(route, {});
  });
}
