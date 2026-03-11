import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTreeModule, MatTreeNestedDataSource } from '@angular/material/tree';
import { NestedTreeControl } from '@angular/cdk/tree';
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

@Component({
  selector: 'app-variable-picker',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatTreeModule,
    MatTooltipModule,
    MatInputModule,
    MatFormFieldModule,
    FormsModule,
  ],
  template: `
    <div class="variable-picker">
      <div class="picker-header">
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
            <div class="section-header" (click)="toggleSection(section.name)">
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
                </div>
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
                    </div>
                  }
                }
              }
            }
          </div>
        }

        <!-- Utilities section -->
        @if (utilities.length > 0) {
          <div class="section">
            <div class="section-header" (click)="toggleSection('Utilities')">
              <mat-icon>{{ expandedSections.has('Utilities') ? 'expand_more' : 'chevron_right' }}</mat-icon>
              <span>Utilities</span>
            </div>
            @if (expandedSections.has('Utilities')) {
              @for (u of utilities; track u.path) {
                <div class="var-item leaf" (click)="selectVariable(u)" [matTooltip]="u.type">
                  <mat-icon class="var-icon">schedule</mat-icon>
                  <span class="var-name">{{ u.name }}</span>
                  <code class="var-path">{{ '{{' }} {{ u.path }} {{ '}}' }}</code>
                </div>
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
    this.variableSelected.emit(`{{ ${node.path} }}`);
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
