import { Component, input, computed } from '@angular/core';

@Component({
  selector: 'app-ai-icon',
  standalone: true,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      [class.ai-icon]="animated()"
      [class.ai-icon-static]="!animated()"
    >
      <!-- Glow ring -->
      <circle class="ai-glow" cx="24" cy="24" r="7"/>

      <!-- Connection lines + pulse lines + nodes — each wrapped in a drifting group -->
      <g class="ai-drift ai-drift-1">
        <line class="ai-link" x1="24" y1="24" x2="11" y2="11"/>
        <line class="ai-pulse ai-p1" x1="24" y1="24" x2="11" y2="11"/>
        <circle class="ai-node ai-nd1" cx="11" cy="11" r="2.8"/>
      </g>

      <g class="ai-drift ai-drift-2">
        <line class="ai-link" x1="24" y1="24" x2="37" y2="11"/>
        <line class="ai-pulse ai-p2" x1="24" y1="24" x2="37" y2="11"/>
        <circle class="ai-node ai-nd2" cx="37" cy="11" r="2.8"/>
      </g>

      <g class="ai-drift ai-drift-3">
        <line class="ai-link" x1="24" y1="24" x2="9" y2="31"/>
        <circle class="ai-node ai-nd3" cx="9" cy="31" r="2.8"/>
      </g>

      <g class="ai-drift ai-drift-4">
        <line class="ai-link" x1="24" y1="24" x2="39" y2="31"/>
        <line class="ai-pulse ai-p3" x1="24" y1="24" x2="39" y2="31"/>
        <circle class="ai-node ai-nd4" cx="39" cy="31" r="2.8"/>
      </g>

      <g class="ai-drift ai-drift-5">
        <line class="ai-link" x1="24" y1="24" x2="24" y2="41"/>
        <circle class="ai-node ai-nd5" cx="24" cy="41" r="2.8"/>
      </g>

      <!-- Center hub (static position) -->
      <circle class="ai-hub" cx="24" cy="24" r="4.5"/>
      <circle cx="23.5" cy="22.5" r="1.8" fill="white" opacity="0.4"/>
    </svg>
  `,
  styles: [
    `
      :host { display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; }

      /* Static mode: no animations, slightly lighter for toolbar harmony */
      .ai-icon-static * { animation: none !important; }
      .ai-icon-static { opacity: 0.85; }

      /* ── Node drift (orbital wobble) ── */
      @keyframes drift-1 {
        0%, 100% { transform: translate(0, 0); }
        25% { transform: translate(1.5px, -2px); }
        50% { transform: translate(-1px, 1px); }
        75% { transform: translate(2px, 1.5px); }
      }
      @keyframes drift-2 {
        0%, 100% { transform: translate(0, 0); }
        25% { transform: translate(-2px, 1px); }
        50% { transform: translate(1px, 2px); }
        75% { transform: translate(-1px, -1.5px); }
      }
      @keyframes drift-3 {
        0%, 100% { transform: translate(0, 0); }
        25% { transform: translate(2px, 1px); }
        50% { transform: translate(-1.5px, -2px); }
        75% { transform: translate(1px, 1px); }
      }
      @keyframes drift-4 {
        0%, 100% { transform: translate(0, 0); }
        25% { transform: translate(-1px, -1.5px); }
        50% { transform: translate(2px, 1px); }
        75% { transform: translate(-2px, 2px); }
      }
      @keyframes drift-5 {
        0%, 100% { transform: translate(0, 0); }
        25% { transform: translate(1px, -1px); }
        50% { transform: translate(-1.5px, 0.5px); }
        75% { transform: translate(0.5px, 2px); }
      }

      .ai-drift-1 { animation: drift-1 7s ease-in-out infinite; }
      .ai-drift-2 { animation: drift-2 8s ease-in-out infinite 0.5s; }
      .ai-drift-3 { animation: drift-3 9s ease-in-out infinite 1s; }
      .ai-drift-4 { animation: drift-4 7.5s ease-in-out infinite 1.5s; }
      .ai-drift-5 { animation: drift-5 8.5s ease-in-out infinite 2s; }

      /* ── Pulse travel ── */
      @keyframes pulse-travel-1 { 0%, 100% { stroke-dashoffset: 30; } 40%, 60% { stroke-dashoffset: 0; } }
      @keyframes pulse-travel-2 { 0%, 100% { stroke-dashoffset: 30; } 50%, 70% { stroke-dashoffset: 0; } }
      @keyframes pulse-travel-3 { 0%, 100% { stroke-dashoffset: 30; } 60%, 80% { stroke-dashoffset: 0; } }

      /* ── Node breathe ── */
      @keyframes node-breathe { 0%, 100% { r: 2.8; } 50% { r: 3.4; } }

      /* ── Hub ── */
      @keyframes hub-breathe { 0%, 100% { r: 4.5; opacity: 0.85; } 50% { r: 5.2; opacity: 1; } }
      @keyframes glow-ring { 0%, 100% { r: 7; opacity: 0.08; } 50% { r: 9; opacity: 0.15; } }

      /* ── Styles ── */
      .ai-link { stroke: #0078d4; stroke-width: 1; opacity: 0.25; }
      .ai-pulse {
        stroke-dasharray: 3 27; fill: none; stroke-width: 1.5; opacity: 0.9;
      }
      .ai-p1 { stroke: #34d399; animation: pulse-travel-1 2.8s ease-in-out infinite; }
      .ai-p2 { stroke: #34d399; animation: pulse-travel-2 3.2s ease-in-out infinite 0.6s; }
      .ai-p3 { stroke: #059669; animation: pulse-travel-3 3.6s ease-in-out infinite 1.2s; }

      .ai-node { fill: #0078d4; }
      .ai-nd1 { animation: node-breathe 2.8s ease-in-out infinite; }
      .ai-nd2 { animation: node-breathe 2.8s ease-in-out infinite 0.5s; }
      .ai-nd3 { animation: node-breathe 2.8s ease-in-out infinite 1.0s; }
      .ai-nd4 { animation: node-breathe 2.8s ease-in-out infinite 1.5s; }
      .ai-nd5 { animation: node-breathe 2.8s ease-in-out infinite 2.0s; }

      .ai-hub { fill: #0078d4; animation: hub-breathe 3s ease-in-out infinite; }
      .ai-glow { fill: #0078d4; animation: glow-ring 3s ease-in-out infinite; }
    `,
  ],
})
export class AiIconComponent {
  /** Icon size in pixels (default 24) */
  size = input(24);

  /** Whether animations are enabled (default true). Set false for toolbar buttons. */
  animated = input(true);
}
