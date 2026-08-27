import type { StoreState } from '../../store/types';

const EMPTY_QUARANTINED_ATOMS: string[] = [];

export const selectProjectStatus = (state: StoreState) => {
  const { project, flow, validation, compileResult, discoverResult, executeInfo, readiness } = state;
  const hasFatalRisk = validation?.risks?.some(
    (risk: Record<string, unknown>) => risk.severity === 'fatal',
  ) ?? false;
  return {
    selected: !!project,
    flowSaved: Object.keys(flow).length > 0 || !!readiness?.flow_saved,
    validated: validation ? validation.is_valid && !hasFatalRisk : !!readiness?.validated,
    compiled: !!compileResult || !!readiness?.compiled,
    dataDiscovered: !!discoverResult || !!readiness?.data_discovered,
    executed: !!executeInfo || !!readiness?.executed,
    hasFatalRisk,
    quarantinedAtoms: readiness?.quarantined_atoms ?? EMPTY_QUARANTINED_ATOMS,
  };
};
