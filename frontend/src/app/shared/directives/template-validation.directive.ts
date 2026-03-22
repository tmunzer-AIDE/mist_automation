import {
  DestroyRef,
  Directive,
  ElementRef,
  inject,
  Input,
  OnChanges,
  OnDestroy,
  Renderer2,
  SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgControl } from '@angular/forms';
import { debounceTime } from 'rxjs';
import { VariableTree } from '../../core/models/workflow.model';

/**
 * Directive that validates Jinja2 template expressions in form fields.
 * Adds a visual indicator (green check or red warning) to fields containing {{ }} expressions.
 *
 * Usage: <input matInput [appTemplateValidation]="variableTree" formControlName="..." />
 */
@Directive({
  selector: '[appTemplateValidation]',
  standalone: true,
})
export class TemplateValidationDirective implements OnChanges, OnDestroy {
  @Input('appTemplateValidation') variableTree: VariableTree | null = null;

  private readonly el = inject(ElementRef);
  private readonly renderer = inject(Renderer2);
  private readonly control = inject(NgControl, { optional: true });
  private readonly destroyRef = inject(DestroyRef);
  private indicator: HTMLElement | null = null;
  private subscribed = false;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['variableTree'] && this.control?.value) {
      this.validate(this.control.value);
    }

    // Subscribe to value changes once
    if (!this.subscribed && this.control?.control) {
      this.subscribed = true;
      this.control.control.valueChanges
        .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
        .subscribe((value) => this.validate(value || ''));

      // Initial check
      if (this.control.value) {
        this.validate(this.control.value);
      }
    }
  }

  ngOnDestroy(): void {
    this.removeIndicator();
  }

  private validate(value: string): void {
    if (!value || typeof value !== 'string') {
      this.removeIndicator();
      return;
    }

    // Check if the value contains any {{ }} expressions
    const templateRegex = /\{\{.*?\}\}/g;
    const matches = value.match(templateRegex);
    if (!matches || !matches.length) {
      this.removeIndicator();
      return;
    }

    // Validate each expression
    const errors: string[] = [];

    // Check for unbalanced braces
    const openCount = (value.match(/\{\{/g) || []).length;
    const closeCount = (value.match(/\}\}/g) || []).length;
    if (openCount !== closeCount) {
      errors.push('Unmatched braces');
    }

    // Check variable paths against the tree if available
    if (this.variableTree) {
      for (const match of matches) {
        const path = match.replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '').trim();
        // Strip Jinja2 filters (everything after |)
        const cleanPath = path.split('|')[0].trim();
        if (cleanPath && !this.isKnownVariable(cleanPath)) {
          errors.push(`Unknown: ${cleanPath}`);
        }
      }
    }

    this.showIndicator(errors.length === 0, errors.join(', '));
  }

  private isKnownVariable(path: string): boolean {
    if (!this.variableTree) return true; // Can't validate without tree

    const parts = path.split('.');
    if (!parts.length) return true;

    const root = parts[0];

    // Check well-known roots
    if (root === 'trigger') return true; // Trigger variables are dynamic
    if (root === 'nodes') return true; // Node outputs are dynamic
    if (root === 'results') return true; // Set-variable results
    if (root === 'loop' || root === 'item') return true; // Loop variables
    if (root === 'callback') return true; // Callback variables

    // Check utilities
    if (this.variableTree.utilities && root in this.variableTree.utilities) return true;

    // Check if it's a saved result (top-level variable from set_variable)
    if (this.variableTree.results && root in this.variableTree.results) return true;

    // Unknown root
    return false;
  }

  private showIndicator(valid: boolean, tooltip: string): void {
    if (!this.indicator) {
      this.indicator = this.renderer.createElement('span');
      this.renderer.addClass(this.indicator, 'template-validation-indicator');

      // Insert after the input's parent (mat-form-field)
      const formField = this.el.nativeElement.closest('mat-form-field');
      if (formField) {
        this.renderer.setStyle(this.indicator, 'position', 'absolute');
        this.renderer.setStyle(this.indicator, 'top', '8px');
        this.renderer.setStyle(this.indicator, 'right', '40px');
        this.renderer.setStyle(this.indicator, 'font-size', '14px');
        this.renderer.setStyle(this.indicator, 'z-index', '1');
        this.renderer.setStyle(formField, 'position', 'relative');
        this.renderer.appendChild(formField, this.indicator);
      }
    }

    if (this.indicator) {
      this.indicator.textContent = valid ? '\u2713' : '\u26A0';
      this.renderer.setStyle(
        this.indicator,
        'color',
        valid ? 'var(--app-success, #4caf50)' : 'var(--app-error, #f44336)'
      );
      this.indicator.title = valid ? 'Template expressions valid' : tooltip;
    }
  }

  private removeIndicator(): void {
    if (this.indicator) {
      this.indicator.remove();
      this.indicator = null;
    }
  }
}
