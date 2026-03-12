import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { FormsModule } from '@angular/forms';
import { VariableTree } from '../../../../core/models/workflow.model';

interface VarNode {
  name: string;
  path: string;
  type: string;
  children?: VarNode[];
}

interface FilterDef {
  name: string;
  syntax: string;
  description: string;
}

@Component({
  selector: 'app-variable-picker',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatInputModule,
    MatFormFieldModule,
    FormsModule,
  ],
  template: `
    <ng-template #filterMenu let-varNode>
      @if (filterMenuNode?.path === varNode.path) {
        <div class="filter-menu" (click)="$event.stopPropagation()">
          @for (f of availableFilters; track f.name) {
            <div
              class="filter-item"
              (click)="selectWithFilter(varNode, f.syntax)"
              [matTooltip]="f.description"
            >
              <code>| {{ f.name }}</code>
            </div>
          }
        </div>
      }
    </ng-template>
    <div class="variable-picker">
      <div class="picker-header" (click)="$event.stopPropagation()">
        <span class="picker-title">Insert Variable</span>
        <mat-form-field appearance="outline" class="search-field" subscriptSizing="dynamic">
          <mat-icon matPrefix>search</mat-icon>
          <input matInput placeholder="Filter..." [(ngModel)]="filter" (ngModelChange)="applyFilter()" />
        </mat-form-field>
      </div>

      <div class="picker-tree">
        @if (flatNodes.length === 0) {
          <div class="empty-state">
            <mat-icon>info_outline</mat-icon>
            <span>No variables available. Connect upstream nodes first.</span>
          </div>
        }

        @for (section of filteredSections; track section.name) {
          <div class="section">
            <div class="section-header" (click)="$event.stopPropagation(); toggleSection(section.name)">
              <mat-icon>{{ expandedSections.has(section.name) ? 'expand_more' : 'chevron_right' }}</mat-icon>
              <span>{{ section.name }}</span>
            </div>
            @if (expandedSections.has(section.name)) {
              @for (node of section.children; track node.path) {
                <div
                  class="var-item"
                  [class.leaf]="!node.children?.length"
                  (click)="selectVariable(node)"
                  [matTooltip]="node.type"
                >
                  <mat-icon class="var-icon">
                    {{ node.children?.length ? 'folder_open' : 'data_object' }}
                  </mat-icon>
                  <span class="var-name">{{ node.name }}</span>
                  <code class="var-path">{{ '{{' }} {{ node.path }} {{ '}}' }}</code>
                  @if (!node.children?.length) {
                    <button
                      class="pipe-btn"
                      (click)="$event.stopPropagation(); toggleFilterMenu(node)"
                      matTooltip="Apply filter"
                    >|</button>
                  }
                </div>
                <ng-container *ngTemplateOutlet="filterMenu; context: { $implicit: node }"></ng-container>
                @if (node.children?.length) {
                  @for (child of node.children; track child.path) {
                    <div
                      class="var-item nested"
                      (click)="selectVariable(child)"
                      [matTooltip]="child.type"
                    >
                      <mat-icon class="var-icon">data_object</mat-icon>
                      <span class="var-name">{{ child.name }}</span>
                      <code class="var-path">{{ '{{' }} {{ child.path }} {{ '}}' }}</code>
                      <button
                        class="pipe-btn"
                        (click)="$event.stopPropagation(); toggleFilterMenu(child)"
                        matTooltip="Apply filter"
                      >|</button>
                    </div>
                    <ng-container *ngTemplateOutlet="filterMenu; context: { $implicit: child }"></ng-container>
                  }
                }
              }
            }
          </div>
        }

        <!-- Utilities section -->
        @if (utilities.length > 0) {
          <div class="section">
            <div class="section-header" (click)="$event.stopPropagation(); toggleSection('Utilities')">
              <mat-icon>{{ expandedSections.has('Utilities') ? 'expand_more' : 'chevron_right' }}</mat-icon>
              <span>Utilities</span>
            </div>
            @if (expandedSections.has('Utilities')) {
              @for (u of utilities; track u.path) {
                <div class="var-item leaf" (click)="selectVariable(u)" [matTooltip]="u.type">
                  <mat-icon class="var-icon">schedule</mat-icon>
                  <span class="var-name">{{ u.name }}</span>
                  <code class="var-path">{{ '{{' }} {{ u.path }} {{ '}}' }}</code>
                  <button
                    class="pipe-btn"
                    (click)="$event.stopPropagation(); toggleFilterMenu(u)"
                    matTooltip="Apply filter"
                  >|</button>
                </div>
                <ng-container *ngTemplateOutlet="filterMenu; context: { $implicit: u }"></ng-container>
              }
            }
          </div>
        }
      </div>
    </div>
  `,
  styles: [
    `
      .variable-picker {
        display: flex;
        flex-direction: column;
        max-height: 400px;
        min-width: 300px;
      }

      .picker-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        border-bottom: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
      }

      .picker-title {
        font-weight: 500;
        font-size: 13px;
      }

      .search-field {
        width: 140px;
        font-size: 12px;
      }

      .picker-tree {
        overflow-y: auto;
        flex: 1;
        padding: 4px 0;
      }

      .empty-state {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px;
        color: var(--mat-sys-on-surface-variant, #666);
        font-size: 13px;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .section-header {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        cursor: pointer;
        font-weight: 500;
        font-size: 12px;
        text-transform: uppercase;
        color: var(--mat-sys-on-surface-variant, #666);
        letter-spacing: 0.5px;

        &:hover {
          background: var(--mat-sys-surface-variant, #f5f5f5);
        }

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .var-item {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px 4px 28px;
        cursor: pointer;
        font-size: 12px;

        &:hover {
          background: var(--mat-sys-primary-container, #e3f2fd);

          .pipe-btn {
            opacity: 1;
          }
        }

        &.nested {
          padding-left: 44px;
        }
      }

      .var-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
        color: var(--mat-sys-on-surface-variant, #666);
      }

      .var-name {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .var-path {
        font-size: 10px;
        color: var(--mat-sys-on-surface-variant, #999);
        max-width: 120px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .pipe-btn {
        opacity: 0;
        border: none;
        background: var(--mat-sys-surface-variant, #e8e8e8);
        color: var(--mat-sys-on-surface-variant, #666);
        font-family: var(--app-font-mono, monospace);
        font-size: 12px;
        font-weight: 700;
        width: 20px;
        height: 20px;
        border-radius: 4px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: opacity 0.15s, background 0.15s;

        &:hover {
          background: var(--mat-sys-primary);
          color: var(--mat-sys-on-primary);
        }
      }

      .filter-menu {
        background: var(--mat-sys-surface-container, #f3f3f3);
        border-left: 2px solid var(--mat-sys-primary);
        margin: 0 8px 4px 36px;
        border-radius: 0 4px 4px 0;
        padding: 4px 0;
      }

      .filter-item {
        padding: 4px 12px;
        cursor: pointer;
        font-size: 11px;
        color: var(--mat-sys-on-surface);

        &:hover {
          background: var(--mat-sys-primary-container, #e3f2fd);
        }

        code {
          font-family: var(--app-font-mono, monospace);
          color: var(--mat-sys-primary);
        }
      }
    `,
  ],
})
export class VariablePickerComponent implements OnChanges {
  @Input() variableTree: VariableTree | null = null;
  @Output() variableSelected = new EventEmitter<string>();

  flatNodes: VarNode[] = [];
  utilities: VarNode[] = [];
  sections: { name: string; children: VarNode[] }[] = [];
  filteredSections: { name: string; children: VarNode[] }[] = [];
  expandedSections = new Set<string>();
  filter = '';
  filterMenuNode: VarNode | null = null;

  readonly availableFilters: FilterDef[] = [
    { name: 'datetimeformat', syntax: "datetimeformat('%Y-%m-%d %H:%M')", description: 'Format timestamp to date/time (Unix epoch or ISO string)' },
    { name: 'upper', syntax: 'upper', description: 'Convert to UPPERCASE' },
    { name: 'lower', syntax: 'lower', description: 'Convert to lowercase' },
    { name: 'title', syntax: 'title', description: 'Convert to Title Case' },
    { name: 'trim', syntax: 'trim', description: 'Strip leading/trailing whitespace' },
    { name: 'int', syntax: 'int', description: 'Convert to integer' },
    { name: 'float', syntax: 'float', description: 'Convert to decimal number' },
    { name: 'round', syntax: 'round', description: 'Round to nearest integer' },
    { name: 'length', syntax: 'length', description: 'Get length or item count' },
    { name: 'first', syntax: 'first', description: 'Get first item of a list' },
    { name: 'last', syntax: 'last', description: 'Get last item of a list' },
    { name: 'join', syntax: "join(', ')", description: 'Join list items with separator' },
    { name: 'default', syntax: "default('')", description: 'Provide fallback value if empty' },
    { name: 'tojson', syntax: 'tojson', description: 'Convert to JSON string' },
    { name: 'replace', syntax: "replace('old', 'new')", description: 'Replace text occurrences' },
    { name: 'truncate', syntax: 'truncate(50)', description: 'Truncate to N characters' },
  ];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['variableTree']) {
      this.buildTree();
    }
  }

  private buildTree(): void {
    this.flatNodes = [];
    this.utilities = [];
    this.sections = [];

    if (!this.variableTree) {
      this.filteredSections = [];
      return;
    }

    // Trigger section
    if (this.variableTree.trigger && Object.keys(this.variableTree.trigger).length > 0) {
      const triggerNodes = this.objectToVarNodes(this.variableTree.trigger, 'trigger');
      this.sections.push({ name: 'Trigger', children: triggerNodes });
      this.flatNodes.push(...triggerNodes);
      this.expandedSections.add('Trigger');
    }

    // Node sections
    if (this.variableTree.nodes) {
      for (const [nodeName, schema] of Object.entries(this.variableTree.nodes)) {
        const nodeNodes = this.objectToVarNodes(
          schema as Record<string, unknown>,
          `nodes.${nodeName}`
        );
        this.sections.push({ name: nodeName, children: nodeNodes });
        this.flatNodes.push(...nodeNodes);
        this.expandedSections.add(nodeName);
      }
    }

    // Utilities
    if (this.variableTree.utilities) {
      for (const [name, desc] of Object.entries(this.variableTree.utilities)) {
        this.utilities.push({ name, path: name, type: desc });
      }
    }

    this.filteredSections = [...this.sections];
  }

  private objectToVarNodes(
    obj: Record<string, unknown>,
    prefix: string
  ): VarNode[] {
    const nodes: VarNode[] = [];
    for (const [key, value] of Object.entries(obj)) {
      const path = `${prefix}.${key}`;
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const children = this.objectToVarNodes(
          value as Record<string, unknown>,
          path
        );
        nodes.push({ name: key, path, type: 'object', children });
      } else if (Array.isArray(value)) {
        nodes.push({ name: key, path, type: 'array' });
      } else {
        nodes.push({ name: key, path, type: String(value) });
      }
    }
    return nodes;
  }

  toggleSection(name: string): void {
    if (this.expandedSections.has(name)) {
      this.expandedSections.delete(name);
    } else {
      this.expandedSections.add(name);
    }
  }

  selectVariable(node: VarNode): void {
    this.filterMenuNode = null;
    this.variableSelected.emit(`{{ ${node.path} }}`);
  }

  toggleFilterMenu(node: VarNode): void {
    this.filterMenuNode = this.filterMenuNode?.path === node.path ? null : node;
  }

  selectWithFilter(node: VarNode, filterSyntax: string): void {
    this.filterMenuNode = null;
    this.variableSelected.emit(`{{ ${node.path} | ${filterSyntax} }}`);
  }

  applyFilter(): void {
    if (!this.filter.trim()) {
      this.filteredSections = [...this.sections];
      return;
    }

    const term = this.filter.toLowerCase();
    this.filteredSections = this.sections
      .map((section) => ({
        name: section.name,
        children: section.children.filter(
          (n) =>
            n.name.toLowerCase().includes(term) ||
            n.path.toLowerCase().includes(term)
        ),
      }))
      .filter((s) => s.children.length > 0);
  }
}
