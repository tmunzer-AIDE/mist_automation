import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { DomSanitizer } from '@angular/platform-browser';
import { Artifact } from '../../../core/models/llm.model';
import { ThemeService } from '../../../core/services/theme.service';

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  code: { label: 'Code', color: '#60a5fa' },
  markdown: { label: 'Document', color: '#a78bfa' },
  html: { label: 'HTML', color: '#f472b6' },
  mermaid: { label: 'Diagram', color: '#34d399' },
  svg: { label: 'SVG', color: '#fb923c' },
  chart: { label: 'Chart', color: '#fbbf24' },
};

@Component({
  selector: 'app-artifact-card',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule],
  template: `
    <div class="artifact-card" [class.expanded]="expanded()">
      <div class="artifact-header" (click)="toggle()">
        <span class="type-badge" [style.background]="badgeColor()">{{ badgeLabel() }}</span>
        <span class="artifact-title">{{ artifact().title }}</span>
        <span class="header-actions">
          <button mat-icon-button matTooltip="Copy" (click)="copy($event)" class="copy-btn">
            <mat-icon>content_copy</mat-icon>
          </button>
          <mat-icon class="expand-icon">{{ expanded() ? 'expand_less' : 'expand_more' }}</mat-icon>
        </span>
      </div>
      @if (state() === 'loading') {
        <div class="artifact-loading">
          <div class="shimmer"></div>
          <div class="shimmer short"></div>
        </div>
      } @else if (expanded()) {
        <div class="artifact-body">
          <iframe
            #iframeEl
            [srcdoc]="srcdoc()"
            sandbox="allow-scripts"
            (load)="onIframeLoad()"
          ></iframe>
        </div>
      } @else {
        <div class="artifact-preview" (click)="toggle()">
          <pre>{{ preview() }}</pre>
        </div>
      }
    </div>
  `,
  styles: `
    :host { display: block; }

    .artifact-card {
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 8px;
      overflow: hidden;
      max-width: 100%;
    }

    .artifact-card.expanded {
      border-color: transparent;
    }

    .artifact-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: var(--mat-sys-surface-container);
      cursor: pointer;
      user-select: none;
    }

    .type-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 10px;
      color: white;
      font-weight: 500;
      white-space: nowrap;
    }

    .artifact-title {
      font-size: 13px;
      color: var(--mat-sys-on-surface);
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 2px;
      margin-left: auto;
    }

    .copy-btn {
      width: 28px;
      height: 28px;
      --mdc-icon-button-icon-size: 16px;
    }

    .expand-icon {
      font-size: 20px;
      color: var(--mat-sys-on-surface-variant);
    }

    .artifact-preview {
      padding: 8px 12px;
      cursor: pointer;
      background: var(--mat-sys-surface-container-low);
    }

    .artifact-preview pre {
      margin: 0;
      font-size: 11px;
      color: var(--mat-sys-on-surface-variant);
      overflow: hidden;
      max-height: 48px;
      white-space: pre-wrap;
      word-break: break-all;
    }

    .artifact-body {
      background: var(--mat-sys-surface-container);
    }

    .artifact-body iframe {
      width: 100%;
      border: none;
      display: block;
      min-height: 200px;
      max-height: 600px;
      overflow: auto;
      background: transparent;
    }

    .artifact-loading {
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .shimmer {
      height: 14px;
      border-radius: 4px;
      background: linear-gradient(
        90deg,
        var(--mat-sys-surface-container) 25%,
        var(--mat-sys-surface-container-high) 50%,
        var(--mat-sys-surface-container) 75%
      );
      background-size: 200% 100%;
      animation: shimmer 1.5s ease-in-out infinite;
    }

    .shimmer.short { width: 60%; }

    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }
  `,
})
export class ArtifactCardComponent implements OnInit, OnDestroy {
  artifact = input.required<Artifact>();
  state = input<'loading' | 'ready'>('ready');

  expanded = signal(false);
  private readonly visualTypes = new Set(['chart', 'mermaid', 'svg']);

  private readonly snackBar = inject(MatSnackBar);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly themeService = inject(ThemeService);
  private readonly iframeEl = viewChild<ElementRef<HTMLIFrameElement>>('iframeEl');
  private messageListener: ((e: MessageEvent) => void) | null = null;

  ngOnInit(): void {
    if (this.visualTypes.has(this.artifact().type)) {
      this.expanded.set(true);
    }
  }

  badgeLabel = computed(() => TYPE_LABELS[this.artifact().type]?.label ?? this.artifact().type);
  badgeColor = computed(() => TYPE_LABELS[this.artifact().type]?.color ?? '#888');

  preview = computed(() => {
    const content = this.artifact().content;
    const lines = content.split('\n').slice(0, 3);
    const text = lines.join('\n');
    return text.length > 200 ? text.slice(0, 200) + '...' : text;
  });

  srcdoc = computed(() =>
    this.sanitizer.bypassSecurityTrustHtml(this._buildSrcdoc(this.artifact(), this.themeService.isDark())),
  );

  toggle(): void {
    this.expanded.update((v) => !v);
  }

  copy(event: Event): void {
    event.stopPropagation();
    navigator.clipboard.writeText(this.artifact().content);
    this.snackBar.open('Copied to clipboard', '', { duration: 2000 });
  }

  onIframeLoad(): void {
    if (this.messageListener) window.removeEventListener('message', this.messageListener);
    this.messageListener = (e: MessageEvent) => {
      if (e.data?.type === 'artifact-height') {
        const iframe = this.iframeEl()?.nativeElement;
        if (iframe) {
          iframe.style.height = Math.min(e.data.height + 16, 600) + 'px';
        }
      }
    };
    window.addEventListener('message', this.messageListener);
  }

  ngOnDestroy(): void {
    if (this.messageListener) window.removeEventListener('message', this.messageListener);
  }

  // Known Azure palette values from Angular Material 3 compiled CSS
  private static readonly THEME_COLORS = {
    light: { surface: '#efedf0', onSurface: '#1a1b1f', outlineVariant: '#c4c6d0', onSurfaceVariant: '#44474e' },
    dark: { surface: '#1f2022', onSurface: '#e3e2e6', outlineVariant: '#44474e', onSurfaceVariant: '#e0e2ec' },
  };

  private _buildSrcdoc(artifact: Artifact, isDark: boolean): string {
    const theme = isDark ? ArtifactCardComponent.THEME_COLORS.dark : ArtifactCardComponent.THEME_COLORS.light;
    const bg = theme.surface;
    const fg = theme.onSurface;
    const codeBg = isDark ? '#14141e' : '#f5f5f5';

    const baseStyle = `
      <style>
        * { box-sizing: border-box; }
        body { margin: 0; padding: 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: ${bg}; color: ${fg}; font-size: 14px; line-height: 1.6; }
        pre { background: ${codeBg}; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; margin: 0; }
        code { font-family: 'SF Mono', 'Fira Code', monospace; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid ${isDark ? '#333' : '#ddd'}; padding: 6px 10px; text-align: left; font-size: 13px; }
        th { background: ${isDark ? '#252535' : '#f0f0f0'}; }
      </style>
    `;

    const heightScript = `
      <script>
        function reportHeight() {
          parent.postMessage({ type: 'artifact-height', height: document.body.scrollHeight }, '*');
        }
        window.addEventListener('load', reportHeight);
        new ResizeObserver(reportHeight).observe(document.body);
      <\/script>
    `;

    switch (artifact.type) {
      case 'code':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/${isDark ? 'github-dark' : 'github'}.min.css">
          <script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"><\/script>
          ${heightScript}
          </head><body>
          <pre><code class="language-${artifact.language || 'plaintext'}">${this._escapeHtml(artifact.content)}</code></pre>
          <script>hljs.highlightAll();<\/script>
          </body></html>`;

      case 'markdown':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"><\/script>
          <script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.9/dist/purify.min.js"><\/script>
          ${heightScript}
          </head><body>
          <div id="content"></div>
          <script>
            document.getElementById('content').innerHTML = DOMPurify.sanitize(marked.parse(${JSON.stringify(artifact.content)}));
          <\/script>
          </body></html>`;

      case 'html':
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body>${artifact.content}</body></html>`;

      case 'mermaid':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.0/dist/mermaid.min.js"><\/script>
          ${heightScript}
          </head><body>
          <pre class="mermaid">${this._escapeHtml(artifact.content)}</pre>
          <script>mermaid.initialize({ startOnLoad: true, theme: '${isDark ? 'dark' : 'default'}' });<\/script>
          </body></html>`;

      case 'svg':
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body>${artifact.content}</body></html>`;

      case 'chart': {
        // Use the app's actual --app-chart-topic-* palette
        const palette = isDark
          ? "['#93c5fd','#c4b5fd','#6ee7b7','#fde68a','#fca5a5','#f9a8d4','#67e8f9','#bef264','#fdba74','#c7d2fe']"
          : "['#60a5fa','#a78bfa','#34d399','#fbbf24','#f87171','#f9a8d4','#22d3ee','#a3e635','#fb923c','#a5b4fc']";
        const chartBg = bg;
        const legendColor = fg;
        const gridColor = theme.outlineVariant;
        const tickColor = theme.onSurfaceVariant;
        return `<!DOCTYPE html><html><head>
          <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"><\/script>
          ${heightScript}
          </head><body style="margin:0;padding:12px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:${chartBg};color:${fg};font-size:14px;">
          <div style="position:relative; width:100%;">
            <canvas id="chart"></canvas>
          </div>
          <script>
            try {
              // Set Chart.js global defaults for this iframe
              Chart.defaults.color = '${legendColor}';
              Chart.defaults.backgroundColor = '${chartBg}';

              var spec = ${JSON.stringify(artifact.content)};
              var parsed = JSON.parse(spec);
              var palette = ${palette};
              var isDark = ${isDark};
              var chartType = parsed.chartType || 'bar';

              // Auto-upgrade pie to doughnut for modern look
              if (chartType === 'pie') chartType = 'doughnut';
              var isCircular = chartType === 'doughnut' || chartType === 'polarArea';

              parsed.data.datasets.forEach(function(ds, i) {
                if (!ds.backgroundColor) ds.backgroundColor = isCircular ? palette : palette[i % palette.length];
                if (isCircular) {
                  ds.borderWidth = 0;
                } else {
                  if (!ds.borderColor) ds.borderColor = palette[i % palette.length];
                  if (!ds.borderWidth) ds.borderWidth = 2;
                  if (!ds.borderRadius) ds.borderRadius = 6;
                }
                if (isCircular && !ds.hoverOffset) ds.hoverOffset = 6;
              });

              // Build legend label callback to show "Label -- Value"
              var labelCallback = isCircular ? {
                generateLabels: function(chart) {
                  var data = chart.data;
                  return data.labels.map(function(label, i) {
                    var ds = data.datasets[0];
                    var value = ds.data[i];
                    return {
                      text: label + ' \\u2014 ' + value,
                      fontColor: '${legendColor}',
                      fillStyle: Array.isArray(ds.backgroundColor) ? ds.backgroundColor[i] : ds.backgroundColor,
                      strokeStyle: Array.isArray(ds.borderColor) ? ds.borderColor[i] : ds.borderColor,
                      lineWidth: 1,
                      index: i,
                      hidden: false,
                      pointStyle: 'circle',
                    };
                  });
                },
              } : {};

              var opts = {
                responsive: true,
                maintainAspectRatio: true,
                cutout: isCircular ? '60%' : undefined,
                layout: { padding: { top: 4, bottom: 4 } },
                plugins: {
                  legend: {
                    position: isCircular ? 'top' : 'top',
                    align: 'start',
                    labels: Object.assign({
                      color: '${legendColor}',
                      padding: 16,
                      usePointStyle: true,
                      pointStyle: 'circle',
                      font: { size: 12, weight: '500', family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
                    }, labelCallback),
                  },
                  tooltip: {
                    backgroundColor: isDark ? 'rgba(30,41,59,0.95)' : 'rgba(15,23,42,0.9)',
                    titleColor: '#f1f5f9',
                    bodyColor: '#e2e8f0',
                    borderColor: isDark ? '#475569' : '#334155',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 12,
                    titleFont: { size: 13, weight: '600' },
                    bodyFont: { size: 13 },
                    displayColors: true,
                    boxPadding: 4,
                  },
                },
                scales: isCircular ? {} : {
                  x: {
                    ticks: { color: '${tickColor}', font: { size: 11 } },
                    grid: { color: '${gridColor}', lineWidth: 0.5 },
                    border: { display: false },
                  },
                  y: {
                    ticks: { color: '${tickColor}', font: { size: 11 } },
                    grid: { color: '${gridColor}', lineWidth: 0.5 },
                    border: { display: false },
                  },
                },
              };

              // Merge user-provided options (but don't override our styling)
              if (parsed.options) {
                if (parsed.options.indexAxis) opts.indexAxis = parsed.options.indexAxis;
                if (parsed.options.plugins && parsed.options.plugins.title) {
                  opts.plugins.title = Object.assign({ color: '${legendColor}' }, parsed.options.plugins.title);
                }
              }

              new Chart(document.getElementById('chart'), {
                type: chartType,
                data: parsed.data,
                options: opts,
              });
            } catch (e) {
              document.body.innerHTML = '<pre style="color:#ef4444">Invalid chart spec: ' + e.message + '<\/pre>';
            }
          <\/script>
          </body></html>`;
      }

      default:
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body><pre>${this._escapeHtml(artifact.content)}</pre></body></html>`;
    }
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
