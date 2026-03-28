import { Component, input } from '@angular/core';

@Component({
  selector: 'app-skeleton-loader',
  standalone: true,
  template: `
    @for (_ of rowArray(); track $index) {
      <div class="skeleton-row">
        @for (w of colWidths(); track $index) {
          <div class="skeleton-cell" [style.flex]="w">
            <div class="shimmer" [style.width.%]="60 + ($index * 13) % 30"></div>
          </div>
        }
      </div>
    }
  `,
  styles: [
    `
      @keyframes shimmer {
        0% { background-position: -200px 0; }
        100% { background-position: 200px 0; }
      }

      .shimmer {
        height: 14px;
        border-radius: 4px;
        background: linear-gradient(
          90deg,
          var(--mat-sys-surface-container) 0%,
          var(--mat-sys-surface-container-high) 50%,
          var(--mat-sys-surface-container) 100%
        );
        background-size: 400px 100%;
        animation: shimmer var(--app-duration-emphasis) ease-in-out infinite;
      }

      .skeleton-row {
        display: flex;
        align-items: center;
        padding: 14px 16px;
        border-bottom: 1px solid var(--mat-sys-outline-variant);

        &:last-child {
          border-bottom: none;
        }
      }

      .skeleton-cell {
        padding: 0 8px;
      }
    `,
  ],
})
export class SkeletonLoaderComponent {
  rows = input(5);
  columns = input(4);

  rowArray = () => Array.from({ length: this.rows() });
  colWidths = () => Array.from({ length: this.columns() }, () => 1);
}
