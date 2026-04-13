import { describe, expect, it } from 'vitest';
import { computeLayerRollup } from './layer-rollup';
import { CheckResultModel, PredictionReportModel } from '../models/twin-session.model';

function check(id: string, layer: number, status: CheckResultModel['status']): CheckResultModel {
  return {
    check_id: id,
    check_name: id,
    layer,
    status,
    summary: '',
    details: [],
    affected_objects: [],
    affected_sites: [],
    remediation_hint: null,
    description: '',
  };
}

function report(checks: CheckResultModel[]): PredictionReportModel {
  return {
    total_checks: checks.length,
    passed: checks.filter((c) => c.status === 'pass').length,
    warnings: checks.filter((c) => c.status === 'warning').length,
    errors: checks.filter((c) => c.status === 'error').length,
    critical: checks.filter((c) => c.status === 'critical').length,
    skipped: checks.filter((c) => c.status === 'skipped').length,
    check_results: checks,
    overall_severity: 'clean',
    summary: '',
    execution_safe: true,
  };
}

describe('computeLayerRollup', () => {
  it('returns all 6 layers L0..L5 in order', () => {
    const rollup = computeLayerRollup(report([]));
    expect(rollup.map((r) => r.layer)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('marks layers with no checks as skipped', () => {
    const rollup = computeLayerRollup(report([check('a', 1, 'pass')]));
    expect(rollup[0].status).toBe('skip');
    expect(rollup[1].status).toBe('pass');
    expect(rollup[1].passed).toBe(1);
    expect(rollup[1].total).toBe(1);
  });

  it('picks the worst status within a layer', () => {
    const rollup = computeLayerRollup(
      report([
        check('a', 1, 'pass'),
        check('b', 1, 'warning'),
        check('c', 1, 'error'),
      ]),
    );
    expect(rollup[1].status).toBe('err');
    expect(rollup[1].passed).toBe(1);
    expect(rollup[1].total).toBe(3);
  });

  it('treats critical as worse than error', () => {
    const rollup = computeLayerRollup(
      report([check('a', 2, 'error'), check('b', 2, 'critical')]),
    );
    expect(rollup[2].status).toBe('crit');
  });

  it('returns a fully-skipped rollup for null report', () => {
    const rollup = computeLayerRollup(null);
    expect(rollup.every((r) => r.status === 'skip')).toBe(true);
  });

  it('keeps skipped-only layers as skip', () => {
    const rollup = computeLayerRollup(report([check('a', 0, 'skipped')]));
    expect(rollup[0].status).toBe('skip');
    expect(rollup[0].passed).toBe(0);
    expect(rollup[0].total).toBe(1);
  });
});
