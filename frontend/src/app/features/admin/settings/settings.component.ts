import { Component, OnInit, inject } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [RouterModule, MatTabsModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
})
export class SettingsComponent implements OnInit {
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);

  ngOnInit(): void {
    this.topbarService.setTitle('System Settings');
    this.globalChatService.setContext({ page: 'Admin > Settings' });
  }
}
