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
            sandbox="allow-scripts allow-same-origin"
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
      background: var(--mat-sys-surface-container-low);
    }

    .artifact-body iframe {
      width: 100%;
      border: none;
      display: block;
      min-height: 200px;
      max-height: 600px;
      overflow: auto;
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

  srcdoc = computed(() => this._buildSrcdoc(this.artifact(), this.themeService.isDark()));

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

  private _buildSrcdoc(artifact: Artifact, isDark: boolean): string {
    const bg = isDark ? '#1e1e2e' : '#ffffff';
    const fg = isDark ? '#cdd6f4' : '#1e1e2e';
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
        const colors = isDark
          ? "['#60a5fa','#34d399','#fbbf24','#f472b6','#a78bfa','#fb923c']"
          : "['#3b82f6','#10b981','#f59e0b','#ec4899','#8b5cf6','#f97316']";
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"><\/script>
          ${heightScript}
          </head><body>
          <canvas id="chart" style="max-height:500px"></canvas>
          <script>
            try {
              var spec = ${JSON.stringify(artifact.content)};
              var parsed = JSON.parse(spec);
              var colors = ${colors};
              parsed.data.datasets.forEach(function(ds, i) {
                if (!ds.backgroundColor) ds.backgroundColor = colors;
                if (!ds.borderColor && parsed.chartType !== 'pie' && parsed.chartType !== 'doughnut') ds.borderColor = colors[i % colors.length];
              });
              new Chart(document.getElementById('chart'), {
                type: parsed.chartType || 'bar',
                data: parsed.data,
                options: Object.assign({}, parsed.options, { responsive: true, maintainAspectRatio: true }),
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
