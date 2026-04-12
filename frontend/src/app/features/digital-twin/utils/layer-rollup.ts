import { CheckResultModel, PredictionReportModel } from '../models/twin-session.model';

export interface LayerRollup {
  layer: number;
  passed: number;
  total: number;
  status: 'pass' | 'warn' | 'err' | 'crit' | 'skip';
}

const LAYER_NUMBERS = [ 1, 2, 3, 4, 5];

const STATUS_RANK: Record<CheckResultModel['status'], number> = {
  pass: 0,
  info: 0,
  skipped: 0,
  warning: 1,
  error: 2,
  critical: 3,
};

const RANK_TO_LAYER_STATUS: Record<number, LayerRollup['status']> = {
  0: 'pass',
  1: 'warn',
  2: 'err',
  3: 'crit',
};

export function computeLayerRollup(report: PredictionReportModel | null): LayerRollup[] {
  const checksByLayer = new Map<number, CheckResultModel[]>();
  for (const layer of LAYER_NUMBERS) {
    checksByLayer.set(layer, []);
  }

  for (const check of report?.check_results ?? []) {
    const arr = checksByLayer.get(check.layer);
    if (arr) arr.push(check);
  }

  return LAYER_NUMBERS.map((layer) => {
    const checks = checksByLayer.get(layer) ?? [];
    if (checks.length === 0) {
      return { layer, passed: 0, total: 0, status: 'skip' as const };
    }
    const passed = checks.filter((c) => c.status === 'pass' || c.status === 'info').length;
    const worstRank = Math.max(...checks.map((c) => STATUS_RANK[c.status] ?? 0));
    const status = RANK_TO_LAYER_STATUS[worstRank] ?? 'pass';
    return { layer, passed, total: checks.length, status };
  });
}
