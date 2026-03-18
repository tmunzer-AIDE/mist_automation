import { ChartConfiguration } from 'chart.js/auto';

/** Fallback colors (light theme) used when CSS custom properties are unavailable */
const FALLBACKS = {
  completed: '#60a5fa',
  failed: '#f87171',
  webhooks: '#a78bfa',
  duration: '#fbbf24',
  objects: '#34d399',
  'backup-fail': '#fb923c',
  grid: '#e2e8f0',
  text: '#64748b',
  legend: '#475569',
} as const;

const TOPIC_FALLBACKS = [
  '#60a5fa',
  '#a78bfa',
  '#f87171',
  '#fbbf24',
  '#34d399',
  '#f9a8d4',
  '#22d3ee',
  '#a3e635',
  '#fb923c',
  '#a5b4fc',
];

/** Read a --app-chart-* CSS custom property at runtime */
function getCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(`--app-chart-${name}`).trim() ||
    fallback
  );
}

/** Read the current --app-chart-grid CSS custom property at runtime */
export function getChartGridColor(): string {
  return getCssVar('grid', FALLBACKS.grid);
}

/** Read a named chart color from CSS custom properties */
export function getChartColor(name: keyof typeof FALLBACKS): string {
  return getCssVar(name, FALLBACKS[name]);
}

/** Read the 10-color topic palette from CSS custom properties */
export function getTopicColors(): string[] {
  return TOPIC_FALLBACKS.map((fallback, i) => getCssVar(`topic-${i}`, fallback));
}

/**
 * Stable color map for known webhook topic names.
 * Unknown topics fall back to the cyclic topic palette.
 */
const TOPIC_NAME_SLOTS: Record<string, number> = {
  alarms: 0,
  audits: 3,
  'device-events': 4,
  'device-updowns': 2,
  'mxedge-events': 5,
};

/** Resolve a color for a topic name — stable for known topics, cyclic for others. */
export function getTopicColor(topic: string, fallbackIndex: number): string {
  const palette = getTopicColors();
  const slot = TOPIC_NAME_SLOTS[topic];
  if (slot !== undefined) return palette[slot % palette.length];
  return palette[fallbackIndex % palette.length];
}

/** Common chart options shared across backup list charts */
export function baseChartOptions(
  yLeftTitle: string,
  yRightTitle: string,
): ChartConfiguration<'bar'>['options'] {
  const textColor = getChartColor('text');
  const legendColor = getChartColor('legend');

  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        labels: { color: legendColor },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { maxTicksLimit: 15, font: { size: 10 }, color: textColor },
      },
      y: {
        position: 'left',
        stacked: true,
        beginAtZero: true,
        grid: { color: getChartGridColor() },
        ticks: { precision: 0, font: { size: 10 }, color: textColor },
        title: { display: true, text: yLeftTitle, font: { size: 11 }, color: textColor },
      },
      y1: {
        position: 'right',
        beginAtZero: true,
        grid: { drawOnChartArea: false },
        ticks: { precision: 0, font: { size: 10 }, color: textColor },
        title: { display: true, text: yRightTitle, font: { size: 11 }, color: textColor },
      },
    },
  };
}

/** Create a stacked bar dataset */
export function barDataset(
  label: string,
  data: number[],
  color: string,
  stack = 'jobs',
): ChartConfiguration<'bar'>['data']['datasets'][number] {
  return {
    label,
    data,
    backgroundColor: color,
    borderRadius: 2,
    stack,
    order: 1,
    yAxisID: 'y',
  };
}

/** Create a line overlay dataset on the secondary y axis */
export function lineDataset(label: string, data: number[], color: string): any {
  return {
    label,
    data,
    type: 'line' as const,
    borderColor: color,
    backgroundColor: 'transparent',
    fill: false,
    pointRadius: 2,
    tension: 0.3,
    borderWidth: 2,
    order: 0,
    yAxisID: 'y1',
  };
}
