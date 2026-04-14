import { Component, OnInit, inject } from '@angular/core';
import { RouterModule } from '@angular/router';
import { TelemetryNavService } from './telemetry-nav.service';
import { TopbarService } from '../../core/services/topbar.service';
import { TelemetryHeaderComponent } from './components/telemetry-header/telemetry-header.component';

@Component({
  selector: 'app-telemetry-shell',
  standalone: true,
  imports: [RouterModule, TelemetryHeaderComponent],
  templateUrl: './telemetry-shell.component.html',
  styleUrl: './telemetry-shell.component.scss',
})
export class TelemetryShellComponent implements OnInit {
  private readonly topbarService = inject(TopbarService);
  readonly nav = inject(TelemetryNavService);

  ngOnInit(): void {
    this.topbarService.setTitle('Telemetry');
    this.nav.loadSites();
  }
}
