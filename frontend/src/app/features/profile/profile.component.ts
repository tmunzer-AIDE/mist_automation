import { Component, OnInit, inject } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { TopbarService } from '../../core/services/topbar.service';
import { PageHeaderComponent } from '../../shared/components/page-header/page-header.component';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [RouterModule, MatTabsModule, PageHeaderComponent],
  template: `
    <app-page-header subtitle="Manage your account"></app-page-header>

    <nav mat-tab-nav-bar [tabPanel]="tabPanel">
      <a
        mat-tab-link
        routerLink="general"
        routerLinkActive
        #g="routerLinkActive"
        [active]="g.isActive"
        >General</a
      >
      <a
        mat-tab-link
        routerLink="settings"
        routerLinkActive
        #s="routerLinkActive"
        [active]="s.isActive"
        >Password</a
      >
      <a
        mat-tab-link
        routerLink="sessions"
        routerLinkActive
        #ss="routerLinkActive"
        [active]="ss.isActive"
        >Sessions</a
      >
    </nav>
    <mat-tab-nav-panel #tabPanel>
      <router-outlet></router-outlet>
    </mat-tab-nav-panel>
  `,
  styles: [
    `
      mat-tab-nav-panel {
        padding-top: 24px;
      }
    `,
  ],
})
export class ProfileComponent implements OnInit {
  private readonly topbarService = inject(TopbarService);

  ngOnInit(): void {
    this.topbarService.setTitle('Profile');
  }
}
