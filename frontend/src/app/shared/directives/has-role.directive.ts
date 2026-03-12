import { Directive, Input, TemplateRef, ViewContainerRef, inject, OnInit, DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Store } from '@ngrx/store';
import { selectUserRoles } from '../../core/state/auth/auth.selectors';

@Directive({ selector: '[appHasRole]', standalone: true })
export class HasRoleDirective implements OnInit {
  @Input('appHasRole') role!: string | string[];

  private readonly store = inject(Store);
  private readonly templateRef = inject(TemplateRef<unknown>);
  private readonly viewContainer = inject(ViewContainerRef);
  private readonly destroyRef = inject(DestroyRef);
  private hasView = false;

  ngOnInit(): void {
    this.store
      .select(selectUserRoles)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((roles) => {
        const requiredRoles = Array.isArray(this.role) ? this.role : [this.role];
        const hasRole = requiredRoles.some((r) => roles.includes(r));

        if (hasRole && !this.hasView) {
          this.viewContainer.createEmbeddedView(this.templateRef);
          this.hasView = true;
        } else if (!hasRole && this.hasView) {
          this.viewContainer.clear();
          this.hasView = false;
        }
      });
  }
}
