/**
 * Utility functions for extracting and computing device status information.
 * Used by report-detail and other components that need to display device validation results.
 */

export interface DeviceCheck {
  check: string;
  status: string;
  value: string;
  ports?: WanPort[];
}

export interface WanPort {
  port: string;
  up: boolean;
  speed: number;
  full_duplex: boolean;
}

export interface VcMember {
  member_id: string;
  mac: string;
  serial: string;
  model: string;
  firmware: string;
  status: string;
  vc_ports_up: number;
  checks: DeviceCheck[];
}

export interface CableTestResult {
  port: string;
  status: string;
  pairs: { pair: string; status: string; length: string }[];
  raw?: string[];
}

export interface DeviceResult {
  device_id: string;
  name: string;
  mac: string;
  model: string;
  checks: DeviceCheck[];
}

export interface SwitchResult extends DeviceResult {
  virtual_chassis: { status: string; members: VcMember[]; message?: string } | null;
  cable_tests: CableTestResult[];
}

export interface GatewayResult extends DeviceResult {
  wan_ports: { interface: string; name: string; up: boolean; wan_type: string }[];
  lan_ports: { interface: string; network: string }[];
}

/**
 * Get a specific check value for a device.
 */
export function getCheckValue(device: DeviceResult, checkName: string): string {
  return device.checks.find((c) => c.check === checkName)?.value ?? '';
}

/**
 * Get a specific check status for a device.
 */
export function getCheckStatus(device: DeviceResult, checkName: string): string {
  return device.checks.find((c) => c.check === checkName)?.status ?? 'info';
}

/**
 * Extract WAN ports from device checks.
 */
export function getWanPorts(device: DeviceResult): WanPort[] {
  const check = device.checks.find((c) => c.check === 'wan_port_status');
  return (check?.ports as WanPort[]) ?? [];
}

/**
 * Get the overall status of a device based on all its checks and cable tests.
 */
export function getDeviceOverallStatus(device: DeviceResult | SwitchResult): 'pass' | 'fail' | 'warn' | 'info' {
  // Check all device checks for failures
  const hasFail = device.checks.some((c) => c.status === 'fail');
  if (hasFail) return 'fail';

  // Check cable tests (switches only)
  if ('cable_tests' in device) {
    const sw = device as SwitchResult;
    if (sw.cable_tests?.some((ct) => ct.status === 'fail')) return 'fail';
    // Check VC member failures
    if (sw.virtual_chassis?.members?.some((m) => m.checks.some((c) => c.status === 'fail')))
      return 'fail';
  }

  // Check for warnings
  const hasWarn = device.checks.some((c) => c.status === 'warn');
  if (hasWarn) return 'warn';

  // Fall back to connection status
  return (getCheckStatus(device, 'connection_status') as 'pass' | 'warn' | 'info') ?? 'info';
}

/**
 * Get cable test summary string for display.
 */
export function getCableTestSummary(sw: SwitchResult): string {
  if (!sw.cable_tests?.length) return '';
  const failed = sw.cable_tests.filter((ct) => ct.status === 'fail').length;
  if (failed > 0) return `${sw.cable_tests.length} ports (${failed} failed)`;
  return `${sw.cable_tests.length} ports`;
}

/**
 * Get cable test overall status.
 */
export function getCableTestStatus(sw: SwitchResult): 'pass' | 'fail' | 'warn' | 'info' {
  if (!sw.cable_tests?.length) return 'info';
  if (sw.cable_tests.some((ct) => ct.status === 'fail')) return 'fail';
  if (sw.cable_tests.some((ct) => ct.status === 'warn')) return 'warn';
  return 'pass';
}

/**
 * Check if a cable test status is acceptable (OK states).
 */
export function isCableStatusOk(status: string): boolean {
  const s = status.toLowerCase();
  return s === 'normal' || s === 'ok' || s === 'pass' || s === 'passed';
}

/**
 * Convert a status code to human-readable label.
 */
export function statusLabel(status: string): string {
  switch (status.toLowerCase()) {
    case 'pass':
      return 'Success';
    case 'fail':
      return 'Failed';
    case 'warn':
      return 'Warning';
    case 'info':
      return 'Info';
    default:
      return 'Unknown';
  }
}
