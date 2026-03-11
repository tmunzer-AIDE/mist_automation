import { ChartConfiguration } from 'chart.js/auto';

/** Shared color palette for backup charts */
export const CHART_COLORS = {
  completed: '#2563eb',
  failed: '#ef4444',
  webhooks: '#8b5cf6',
  durationLine: '#f59e0b',
  objectsLine: '#10b981',
  grid: '#e2e8f0',
} as const;

/** Read the current --app-chart-grid CSS custom property at runtime */
export function getChartGridColor(): string {
  if (typeof document === 'undefined') return CHART_COLORS.grid;
  return getComputedStyle(document.documentElement).getPropertyValue('--app-chart-grid').trim() || CHART_COLORS.grid;
}

/** Common chart options shared across backup list charts */
export function baseChartOptions(
  yLeftTitle: string,
  yRightTitle: string,
): ChartConfiguration<'bar'>['options'] {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: true } },
    scales: {
      x: {
        grid: { display: false },
        ticks: { maxTicksLimit: 15, font: { size: 10 } },
      },
      y: {
        position: 'left',
        stacked: true,
        beginAtZero: true,
        grid: { color: getChartGridColor() },
        ticks: { precision: 0, font: { size: 10 } },
        title: { display: true, text: yLeftTitle, font: { size: 11 } },
      },
      y1: {
        position: 'right',
        beginAtZero: true,
        grid: { drawOnChartArea: false },
        ticks: { precision: 0, font: { size: 10 } },
        title: { display: true, text: yRightTitle, font: { size: 11 } },
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
