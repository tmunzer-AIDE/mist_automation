import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { RecipeResponse, RecipeService } from '../../../core/services/recipe.service';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';

const CATEGORIES = [
  { value: '', label: 'All' },
  { value: 'monitoring', label: 'Monitoring' },
  { value: 'deployment', label: 'Deployment' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'incident_response', label: 'Incident Response' },
  { value: 'reporting', label: 'Reporting' },
];

const DIFFICULTY_ICONS: Record<string, string> = {
  beginner: 'signal_cellular_alt_1_bar',
  intermediate: 'signal_cellular_alt_2_bar',
  advanced: 'signal_cellular_alt',
};

@Component({
  selector: 'app-recipe-picker-dialog',
  standalone: true,
  imports: [
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressBarModule,
    MatSnackBarModule,
    AiIconComponent,
  ],
  template: `
    <h2 mat-dialog-title>Create New Workflow</h2>
    <mat-dialog-content>
      <!-- Top: Quick start options -->
      <div class="quick-start">
        <button class="start-card" (click)="startFromScratch()">
          <mat-icon>add_circle_outline</mat-icon>
          <span class="card-title">New Workflow</span>
          <span class="card-desc">Blank canvas with a trigger node</span>
        </button>
        <button class="start-card" (click)="startFromScratch('subflow')">
          <mat-icon>account_tree</mat-icon>
          <span class="card-title">New Sub-Flow</span>
          <span class="card-desc">Reusable callable workflow</span>
        </button>
        @if (llmAvailable) {
          <button class="start-card" (click)="startWithAI()">
            <app-ai-icon [size]="28" [animated]="false"></app-ai-icon>
            <span class="card-title">Create with AI</span>
            <span class="card-desc">Describe your workflow in plain text</span>
          </button>
        }
      </div>

      <!-- Recipe section -->
      <div class="section-header">Use a Recipe</div>

      @if (loading()) {
        <mat-progress-bar mode="indeterminate" />
      } @else if (recipes().length === 0) {
        <div class="no-recipes">No recipes available.</div>
      } @else {
        <!-- Category chips -->
        <div class="category-chips">
          @for (cat of categories; track cat.value) {
            <button
              mat-stroked-button
              [class.active]="selectedCategory() === cat.value"
              (click)="filterByCategory(cat.value)"
            >
              {{ cat.label }}
            </button>
          }
        </div>

        <!-- Recipe cards -->
        <div class="recipe-grid">
          @for (recipe of filteredRecipes(); track recipe.id) {
            <button class="recipe-card" (click)="selectRecipe(recipe)" [class.selected]="selectedRecipe()?.id === recipe.id">
              <div class="recipe-header">
                <span class="recipe-name">{{ recipe.name }}</span>
                <mat-icon class="difficulty-icon">{{ getDifficultyIcon(recipe.difficulty) }}</mat-icon>
              </div>
              <span class="recipe-desc">{{ recipe.description }}</span>
              <div class="recipe-meta">
                <span class="recipe-badge">{{ recipe.node_count }} nodes</span>
                <span class="recipe-badge">{{ recipe.difficulty }}</span>
              </div>
            </button>
          }
        </div>

        <!-- Selected recipe detail -->
        @if (selectedRecipe(); as recipe) {
          <div class="recipe-detail">
            <div class="detail-header">{{ recipe.name }}</div>
            <p>{{ recipe.description }}</p>
            @if (recipe.placeholders.length > 0) {
              <div class="placeholders-note">
                <mat-icon>info</mat-icon>
                {{ recipe.placeholders.length }} field(s) to configure after creation
              </div>
            }
            <button mat-flat-button color="primary" (click)="useRecipe(recipe)" [disabled]="instantiating()">
              {{ instantiating() ? 'Creating...' : 'Use this Recipe' }}
            </button>
          </div>
        }
      }
    </mat-dialog-content>
  `,
  styles: [
    `
      mat-dialog-content {
        min-width: 500px;
        max-height: 70vh;
      }

      .quick-start {
        display: flex;
        gap: 12px;
        margin-bottom: 20px;
      }

      .start-card {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        padding: 16px;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 12px;
        background: var(--mat-sys-surface, #fff);
        cursor: pointer;
        transition: border-color 0.15s, background 0.15s;

        &:hover {
          border-color: var(--mat-sys-primary, #1976d2);
          background: var(--mat-sys-primary-container, #e3f2fd);
        }

        mat-icon { font-size: 28px; width: 28px; height: 28px; color: var(--mat-sys-primary, #1976d2); }
        .card-title { font-size: 14px; font-weight: 500; }
        .card-desc { font-size: 12px; color: var(--mat-sys-on-surface-variant, #666); }
      }

      .section-header {
        font-size: 13px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-bottom: 12px;
      }

      .category-chips {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-bottom: 12px;

        button {
          font-size: 12px;
          min-height: 28px;
          line-height: 28px;
          padding: 0 10px;

          &.active {
            background: var(--mat-sys-primary-container, #e3f2fd);
            color: var(--mat-sys-on-primary-container, #1565c0);
            border-color: var(--mat-sys-primary, #1976d2);
          }
        }
      }

      .recipe-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
        margin-bottom: 12px;
      }

      .recipe-card {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 12px;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 10px;
        background: var(--mat-sys-surface, #fff);
        cursor: pointer;
        text-align: left;
        transition: border-color 0.15s;

        &:hover, &.selected {
          border-color: var(--mat-sys-primary, #1976d2);
        }

        &.selected {
          background: var(--mat-sys-primary-container, #e3f2fd);
        }

        .recipe-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .recipe-name { font-size: 13px; font-weight: 500; }
        .recipe-desc { font-size: 11px; color: var(--mat-sys-on-surface-variant, #666); line-height: 1.4; }
        .recipe-meta { display: flex; gap: 6px; }

        .recipe-badge {
          font-size: 10px;
          padding: 1px 6px;
          border-radius: 4px;
          background: var(--mat-sys-surface-variant, #f5f5f5);
          color: var(--mat-sys-on-surface-variant, #666);
          text-transform: capitalize;
        }

        .difficulty-icon { font-size: 16px; width: 16px; height: 16px; color: var(--mat-sys-on-surface-variant, #888); }
      }

      .recipe-detail {
        padding: 12px;
        border: 1px solid var(--mat-sys-primary, #1976d2);
        border-radius: 10px;
        background: var(--mat-sys-primary-container, #e3f2fd);

        .detail-header { font-size: 14px; font-weight: 500; margin-bottom: 4px; }
        p { font-size: 12px; margin: 0 0 8px; color: var(--mat-sys-on-surface-variant, #555); }
      }

      .placeholders-note {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-bottom: 8px;

        mat-icon { font-size: 16px; width: 16px; height: 16px; }
      }

      .no-recipes {
        text-align: center;
        padding: 20px;
        color: var(--mat-sys-on-surface-variant, #888);
      }
    `,
  ],
})
export class RecipePickerDialogComponent implements OnInit {
  private readonly recipeService = inject(RecipeService);
  private readonly router = inject(Router);
  private readonly dialogRef = inject(MatDialogRef<RecipePickerDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  readonly llmAvailable: boolean = inject(MAT_DIALOG_DATA)?.llmAvailable ?? false;

  readonly categories = CATEGORIES;

  loading = signal(true);
  instantiating = signal(false);
  recipes = signal<RecipeResponse[]>([]);
  filteredRecipes = signal<RecipeResponse[]>([]);
  selectedCategory = signal('');
  selectedRecipe = signal<RecipeResponse | null>(null);

  ngOnInit(): void {
    this.recipeService.list().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (recipes) => {
        this.recipes.set(recipes);
        this.filteredRecipes.set(recipes);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  filterByCategory(category: string): void {
    this.selectedCategory.set(category);
    this.selectedRecipe.set(null);
    if (!category) {
      this.filteredRecipes.set(this.recipes());
    } else {
      this.filteredRecipes.set(this.recipes().filter((r) => r.category === category));
    }
  }

  selectRecipe(recipe: RecipeResponse): void {
    this.selectedRecipe.set(recipe);
  }

  getDifficultyIcon(difficulty: string): string {
    return DIFFICULTY_ICONS[difficulty] || 'signal_cellular_alt';
  }

  startFromScratch(type?: string): void {
    this.dialogRef.close();
    if (type === 'subflow') {
      this.router.navigate(['/workflows/new'], { queryParams: { type: 'subflow' } });
    } else {
      this.router.navigate(['/workflows/new']);
    }
  }

  startWithAI(): void {
    this.dialogRef.close('ai');
  }

  useRecipe(recipe: RecipeResponse): void {
    this.instantiating.set(true);
    this.recipeService.instantiate(recipe.id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (result) => {
        this.dialogRef.close();
        const queryParams: Record<string, string> = {};
        if (result.placeholders?.length) {
          // Pass only essential fields to keep URL size under limits
          const slim = result.placeholders.map((p) => ({
            node_id: p.node_id,
            field_path: p.field_path,
            label: p.label,
            placeholder_type: p.placeholder_type,
            description: (p.description || '').slice(0, 100),
          }));
          queryParams['placeholders'] = JSON.stringify(slim);
        }
        this.router.navigate(['/workflows', result.workflow_id], { queryParams });
        this.snackBar.open(`Workflow created from "${recipe.name}"`, '', { duration: 3000 });
      },
      error: () => {
        this.instantiating.set(false);
        this.snackBar.open('Failed to create workflow from recipe', 'OK', { duration: 5000 });
      },
    });
  }
}
