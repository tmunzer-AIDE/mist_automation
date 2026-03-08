import { Component } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { PageHeaderComponent } from '../../shared/components/page-header/page-header.component';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [RouterModule, MatTabsModule, PageHeaderComponent],
  template: `
    <app-page-header title="Profile" subtitle="Manage your account"></app-page-header>

    <nav mat-tab-nav-bar [tabPanel]="tabPanel">
      <a mat-tab-link routerLink="general" routerLinkActive #g="routerLinkActive"
         [active]="g.isActive">General</a>
      <a mat-tab-link routerLink="settings" routerLinkActive #s="routerLinkActive"
         [active]="s.isActive">Password</a>
      <a mat-tab-link routerLink="sessions" routerLinkActive #ss="routerLinkActive"
         [active]="ss.isActive">Sessions</a>
    </nav>
    <mat-tab-nav-panel #tabPanel>
      <router-outlet></router-outlet>
    </mat-tab-nav-panel>
  `,
  styles: [`
    mat-tab-nav-panel {
      padding-top: 24px;
    }
  `],
})
export class ProfileComponent {}
