import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormArray, FormControl } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatStepperModule } from '@angular/material/stepper';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { RecipePlaceholder } from '../../../core/services/recipe.service';
import { ApiService } from '../../../core/services/api.service';

@Component({
  selector: 'app-placeholder-wizard',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    MatStepperModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <div class="wizard-container">
      <div class="wizard-header">
        <mat-icon>auto_fix_high</mat-icon>
        <div>
          <h3>Configure Your Workflow</h3>
          <p>Fill in the required fields to get started.</p>
        </div>
      </div>

      <mat-stepper [linear]="false" #stepper>
        @for (ph of placeholders; track ph.node_id + ph.field_path; let i = $index) {
          <mat-step [label]="ph.label">
            <div class="step-content">
              @if (ph.description) {
                <p class="step-desc">{{ ph.description }}</p>
              }
              <mat-form-field appearance="outline" class="step-field">
                <mat-label>{{ ph.label }}</mat-label>

                @if (ph.placeholder_type === 'site_id') {
                  @if (loadingSites()) {
                    <mat-select disabled>
                      <mat-option>Loading sites...</mat-option>
                    </mat-select>
                  } @else {
                    <mat-select [formControl]="controls.at(i)" (selectionChange)="onSiteSelected(i)">
                      @for (site of siteOptions(); track site.id) {
                        <mat-option [value]="site.id">{{ site.name }}</mat-option>
                      }
                    </mat-select>
                  }
                } @else if (ph.placeholder_type === 'ap_mac_list') {
                  @if (loadingAps()) {
                    <mat-select multiple disabled>
                      <mat-option>Select a site first...</mat-option>
                    </mat-select>
                  } @else {
                    <mat-select multiple [formControl]="apMultiControl" (selectionChange)="onApSelectionChange(i)">
                      @for (ap of apOptions(); track ap.mac) {
                        <mat-option [value]="ap.mac">{{ ap.name || ap.mac }}</mat-option>
                      }
                    </mat-select>
                  }
                } @else {
                  <input
                    matInput
                    [type]="ph.placeholder_type === 'url' ? 'url' : 'text'"
                    [placeholder]="getPlaceholderHint(ph)"
                    [formControl]="controls.at(i)"
                    (input)="onValueChange(i)"
                  />
                }

              </mat-form-field>
              <div class="step-actions">
                @if (i > 0) {
                  <button mat-button matStepperPrevious>Back</button>
                }
                @if (i < placeholders.length - 1) {
                  <button mat-flat-button matStepperNext>Next</button>
                } @else {
                  <button mat-flat-button (click)="finish()">Start Editing</button>
                }
              </div>
            </div>
          </mat-step>
        }
      </mat-stepper>

      <button mat-button class="skip-btn" (click)="finish()">Skip setup</button>
    </div>
  `,
  styles: [
    `
      .wizard-container {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
      }

      .wizard-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 20px;

        mat-icon {
          font-size: 28px;
          width: 28px;
          height: 28px;
          color: var(--mat-sys-primary);
        }

        h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 500;
        }

        p {
          margin: 2px 0 0;
          font-size: 12px;
          color: var(--mat-sys-on-surface-variant);
        }
      }

      .step-content {
        padding: 12px 0;
      }

      .step-desc {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
        margin: 0 0 12px;
      }

      .step-field {
        width: 100%;
      }

      .step-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
        margin-top: 8px;
      }

      .skip-btn {
        align-self: center;
        margin-top: 12px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
      }
    `,
  ],
})
export class PlaceholderWizardComponent implements OnChanges {
  @Input() placeholders: RecipePlaceholder[] = [];
  @Output() placeholderFilled = new EventEmitter<{ nodeId: string; fieldPath: string; value: string }>();
  @Output() completed = new EventEmitter<void>();

  private readonly api = inject(ApiService);

  controls = new FormArray<FormControl<string>>([]);
  apMultiControl = new FormControl<string[]>([], { nonNullable: true });
  siteOptions = signal<{ id: string; name: string }[]>([]);
  apOptions = signal<{ mac: string; name: string }[]>([]);
  loadingSites = signal(false);
  loadingAps = signal(true);  // starts true = "select a site first"
  private selectedSiteId: string | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['placeholders']) {
      this.controls = new FormArray(
        this.placeholders.map(() => new FormControl('', { nonNullable: true }))
      );

      // Fetch dynamic options for placeholder types that need them
      if (this.placeholders.some((p) => p.placeholder_type === 'site_id')) {
        this.loadingSites.set(true);
        this.api.get<{ sites: { id: string; name: string }[] }>('/admin/mist/sites').subscribe({
          next: (res) => {
            this.siteOptions.set(res.sites);
            this.loadingSites.set(false);
          },
          error: () => this.loadingSites.set(false),
        });
      }
    }
  }

  onValueChange(index: number): void {
    const value = this.controls.at(index).value;
    const ph = this.placeholders[index];
    this.placeholderFilled.emit({ nodeId: ph.node_id, fieldPath: ph.field_path, value });
  }

  onSiteSelected(index: number): void {
    this.onValueChange(index);
    const siteId = this.controls.at(index).value;
    if (siteId && siteId !== this.selectedSiteId) {
      this.selectedSiteId = siteId;
      // Fetch APs for the selected site (used by ap_mac_list placeholders)
      if (this.placeholders.some((p) => p.placeholder_type === 'ap_mac_list')) {
        this.loadingAps.set(true);
        this.api.get<{ aps: { mac: string; name: string }[] }>(
          `/admin/mist/sites/${siteId}/aps`
        ).subscribe({
          next: (res) => {
            this.apOptions.set(res.aps || []);
            this.loadingAps.set(false);
          },
          error: () => {
            this.apOptions.set([]);
            this.loadingAps.set(false);
          },
        });
      }
    }
  }

  onApSelectionChange(index: number): void {
    const selected = this.apMultiControl.value;
    const ph = this.placeholders[index];
    // Store as comma-separated MAC list for use in Jinja2 templates
    this.placeholderFilled.emit({ nodeId: ph.node_id, fieldPath: ph.field_path, value: selected.join(',') });
  }

  getPlaceholderHint(ph: RecipePlaceholder): string {
    switch (ph.placeholder_type) {
      case 'url': return 'https://hooks.slack.com/services/...';
      case 'cron': return '0 */6 * * *';
      case 'site_id': return 'Select a site';
      default: return '';
    }
  }

  finish(): void {
    this.completed.emit();
  }
}
