export type TimeRange = '1h' | '6h' | '24h';

// Scope summary
export interface BandSummary {
  avg_util_all: number;
  avg_noise_floor: number;
}
export interface APScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  max_cpu_util: number;
  avg_mem_usage: number;
  total_clients: number;
  bands: Record<string, BandSummary>;
}
export interface SwitchScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  avg_mem_usage: number;
  total_clients: number;
  ports_up: number;
  ports_total: number;
  poe_draw_total: number;
  poe_max_total: number;
  total_dhcp_leases: number;
}
export interface GatewayScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  avg_mem_usage: number;
  wan_links_up: number;
  wan_links_total: number;
  total_dhcp_leases: number;
  avg_spu_cpu: number;
  total_spu_sessions: number;
}
export interface ScopeSummary {
  ap: APScopeSummary | null;
  switch: SwitchScopeSummary | null;
  gateway: GatewayScopeSummary | null;
}

// Scope devices
export interface DeviceSummaryRecord {
  mac: string;
  site_id: string;
  device_type: string;
  name: string;
  model: string;
  cpu_util: number | null;
  num_clients: number | null;
  last_seen: number | null;
  fresh: boolean;
}
export interface ScopeDevices {
  total: number;
  devices: DeviceSummaryRecord[];
}

export interface ScopeSite {
  site_id: string;
  site_name: string;
  device_counts: Record<string, number>;
  total_devices: number;
}

export interface ScopeSites {
  sites: ScopeSite[];
  total: number;
}

// Latest device stats
export interface LatestStats {
  mac: string;
  fresh: boolean;
  updated_at: number | null;
  stats: Record<string, unknown> | null;
}

// Aggregate query result
export interface AggregatePoint {
  _time: string;
  _value: number;
  [key: string]: unknown;
}
export interface AggregateResult {
  points: AggregatePoint[];
  count: number;
}

// WebSocket live event
export interface BandStats {
  band: string;
  util_all: number;
  num_clients: number;
  noise_floor: number;
  channel: number;
  power: number;
  bandwidth: number;
}
export interface PortStats {
  port_id: string;
  speed: number;
  tx_pkts: number;
  rx_pkts: number;
}
export interface ModuleStats {
  fpc_idx: number;
  vc_role: string;
  temp_max: number;
  poe_draw: number;
  vc_links_count: number;
  mem_usage: number;
}
export interface DhcpStats {
  network_name: string;
  num_ips: number;
  num_leased: number;
  utilization_pct: number;
}
export interface WanStats {
  port_id: string;
  wan_name: string;
  up: boolean;
  tx_bytes: number;
  rx_bytes: number;
  tx_pkts: number;
  rx_pkts: number;
}
export interface SpuStats {
  spu_cpu: number;
  spu_sessions: number;
  spu_max_sessions: number;
  spu_memory: number;
}
export interface ClusterStats {
  status: string;
  operational: boolean;
  primary_health: number;
  secondary_health: number;
  control_link_up: boolean;
  fabric_link_up: boolean;
}
export interface ResourceStats {
  resource_type: string;
  count: number;
  limit: number;
  utilization_pct: number;
}
export interface DeviceSummaryStats {
  cpu_util: number;
  mem_usage: number;
  num_clients?: number;
  uptime: number;
  poe_draw_total?: number;
  poe_max_total?: number;
  ha_state?: string;
  config_status?: string;
}
export interface DeviceLiveEvent {
  device_type: 'ap' | 'switch' | 'gateway';
  timestamp: number;
  summary: DeviceSummaryStats;
  bands?: BandStats[];
  ports?: PortStats[];
  modules?: ModuleStats[];
  dhcp?: DhcpStats[];
  wan?: WanStats[];
  spu?: SpuStats;
  cluster?: ClusterStats;
  resources?: ResourceStats[];
  raw?: Record<string, unknown>;
}

export interface RangeResult {
  mac: string;
  measurement: string;
  start: string;
  end: string;
  points: Record<string, unknown>[];
  count: number;
}
