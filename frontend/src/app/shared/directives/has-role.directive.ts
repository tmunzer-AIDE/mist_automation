import {
  Directive,
  Input,
  TemplateRef,
  ViewContainerRef,
  inject,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { Store } from '@ngrx/store';
import { Subscription } from 'rxjs';
import { selectUserRoles } from '../../core/state/auth/auth.selectors';

@Directive({ selector: '[appHasRole]', standalone: true })
export class HasRoleDirective implements OnInit, OnDestroy {
  @Input('appHasRole') role!: string | string[];

  private readonly store = inject(Store);
  private readonly templateRef = inject(TemplateRef<unknown>);
  private readonly viewContainer = inject(ViewContainerRef);
  private subscription?: Subscription;
  private hasView = false;

  ngOnInit(): void {
    this.subscription = this.store.select(selectUserRoles).subscribe((roles) => {
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

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }
}
