import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  input,
  model,
  output,
  signal,
  inject,
  effect,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { AiIconComponent } from '../ai-icon/ai-icon.component';
import { RestoreDiffCardComponent, RestoreDiffData } from './restore-diff-card.component';
import { TwinResultCardComponent, TwinResultData } from './twin-result-card.component';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { Subscription } from 'rxjs';
import { Artifact, McpConfigAvailable } from '../../../core/models/llm.model';
import { LlmService } from '../../../core/services/llm.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { ArtifactCardComponent } from '../artifact-card/artifact-card.component';
import { ArtifactParserService } from '../../services/artifact-parser.service';
import { extractErrorMessage } from '../../utils/error.utils';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  html: string;
  metadata?: {
    tool_calls?: {
      tool: string;
      server: string;
      status: string;
      arguments?: Record<string, unknown>;
      result_preview?: string;
    }[];
    thinking_texts?: string[];
  } | null;
  timestamp?: string;
}

export interface MessageSection {
  type: 'prose' | 'artifact';
  html?: string;
  artifact?: Artifact;
  state?: 'loading' | 'ready';
}

export type TimelineItem =
  | {
      kind: 'message';
      role: 'user' | 'assistant';
      content: string;
      html: string;
      sections?: MessageSection[];
      timestamp?: string;
    }
  | {
      kind: 'tool';
      tool: string;
      server: string;
      status: 'running' | 'success' | 'error';
      arguments?: Record<string, unknown>;
      resultPreview?: string;
      expanded: boolean;
      timestamp?: string;
    }
  | { kind: 'compaction'; timestamp?: string };

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

@Component({
  selector: 'app-ai-chat-panel',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    AiIconComponent,
    RestoreDiffCardComponent,
    TwinResultCardComponent,
    ArtifactCardComponent,
  ],
  template: `
    <div class="ai-chat-panel">
      <div class="chat-messages" #chatMessages aria-live="polite" aria-relevant="additions">
        @if (timeline().length === 0 && isLoading()) {
          <div class="loading-hint">
            <div class="typing-indicator"><span></span><span></span><span></span></div>
            <span>{{ loadingLabel() }}</span>
          </div>
        }

        @for (item of timeline(); track $index) {
          @if (item.kind === 'message') {
            @if (item.role === 'user' || item.content.trim()) {
              @if (item.timestamp) {
                <div class="message-timestamp" [class.user-ts]="item.role === 'user'">
                  {{ formatTimestamp(item.timestamp) }}
                </div>
              }
              <div
                class="chat-message"
                [class.user]="item.role === 'user'"
                [class.assistant]="item.role === 'assistant'"
              >
                @if (item.role === 'assistant') {
                  <div class="avatar assistant-avatar">
                    <app-ai-icon [size]="16"></app-ai-icon>
                  </div>
                }
                <div class="message-bubble" [class.has-artifacts]="item.sections?.length">
                  @if (item.role === 'assistant' && item.sections?.length) {
                    @for (section of item.sections; track $index) {
                      @if (section.type === 'prose' && section.html) {
                        <div class="message-content markdown-body" [innerHTML]="section.html"></div>
                      } @else if (section.type === 'artifact' && section.artifact) {
                        <app-artifact-card
                          [artifact]="section.artifact"
                          [state]="section.state ?? 'ready'"
                        />
                      }
                    }
                  } @else if (item.role === 'assistant') {
                    <div class="message-content markdown-body" [innerHTML]="item.html"></div>
                  } @else {
                    <div class="message-content">{{ item.content }}</div>
                  }
                </div>
                @if (item.role === 'user') {
                  <div class="avatar user-avatar">
                    <mat-icon>person</mat-icon>
                  </div>
                }
              </div>
            }
          } @else if (item.kind === 'tool') {
            <div
              class="tool-call-inline"
              [class.running]="item.status === 'running'"
              [class.success]="item.status === 'success'"
              [class.error]="item.status === 'error'"
            >
              @if (item.timestamp) {
                <div class="message-timestamp tool-timestamp">
                  {{ formatTimestamp(item.timestamp) }}
                </div>
              }
              <div class="tool-call-header" (click)="toggleToolExpand($index)">
                @if (item.status === 'running') {
                  <mat-icon class="tool-status-icon spinning">hub</mat-icon>
                } @else if (item.status === 'success') {
                  <mat-icon class="tool-status-icon">check_circle</mat-icon>
                } @else {
                  <mat-icon class="tool-status-icon">error</mat-icon>
                }
                <span class="tool-call-label">
                  <strong>{{ item.tool }}</strong>
                  <span class="tool-server">on {{ item.server }}</span>
                </span>
                @if (item.resultPreview || (item.arguments && objectKeys(item.arguments).length)) {
                  <mat-icon class="tool-expand-icon">{{
                    item.expanded ? 'expand_less' : 'expand_more'
                  }}</mat-icon>
                }
              </div>
              @if (item.expanded) {
                @if (item.arguments && objectKeys(item.arguments).length) {
                  <div class="tool-call-section">
                    <div class="tool-call-section-label">Parameters</div>
                    <pre class="tool-call-arguments">{{ formatJson(item.arguments) }}</pre>
                  </div>
                }
                @if (item.resultPreview) {
                  @if (
                    item.tool === 'digital_twin' && _parseTwinResult(item.resultPreview);
                    as twinData
                  ) {
                    <app-twin-result-card [data]="twinData" />
                  } @else {
                    <div class="tool-call-section">
                      <div class="tool-call-section-label">Response</div>
                      <pre class="tool-call-result">{{ item.resultPreview }}</pre>
                    </div>
                  }
                }
              }
            </div>
          } @else if (item.kind === 'compaction') {
            <div class="compaction-notice">
              <mat-icon>compress</mat-icon>
              <span>Earlier messages have been summarized to save context</span>
            </div>
          }
        }

        @if (
          isLoading() &&
          timeline().length > 0 &&
          (waitingAfterTool() || (!hasStreamingContent() && !hasToolCalls()))
        ) {
          <div class="chat-message assistant">
            <div class="avatar assistant-avatar">
              <app-ai-icon [size]="16"></app-ai-icon>
            </div>
            <div class="message-bubble typing-bubble">
              <div class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          </div>
        }

        @if (pendingElicitation(); as elicit) {
          @if (elicit.elicitationType === 'restore_confirm' && elicit.data) {
            <app-restore-diff-card
              [data]="elicit.data"
              [description]="elicit.description"
              (accepted)="respondElicitation(true)"
              (declined)="respondElicitation(false)"
            />
          } @else if (elicit.elicitationType === 'twin_approve') {
            <div class="twin-approve-card">
              <div class="twin-approve-header">
                <mat-icon class="twin-approve-icon">rocket_launch</mat-icon>
                <div>
                  <div class="twin-approve-label">Deploy Configuration Changes</div>
                  <div class="twin-approve-desc">{{ elicit.description }}</div>
                </div>
              </div>
              @if (elicit.data; as data) {
                <div class="twin-approve-summary">
                  <span>{{ data.writes_count }} write(s)</span>
                  <span>{{ data.affected_sites?.length || 0 }} site(s)</span>
                  @if (data.remediation_count > 0) {
                    <span>{{ data.remediation_count }} fix iteration(s)</span>
                  }
                </div>
              }
              <div class="twin-approve-actions">
                <button mat-stroked-button (click)="respondElicitation(false)">Cancel</button>
                <button mat-flat-button color="primary" (click)="respondElicitation(true)">
                  Deploy
                </button>
              </div>
            </div>
          } @else {
            <div class="elicitation-card">
              <div class="elicitation-icon">
                <mat-icon>verified_user</mat-icon>
              </div>
              <div class="elicitation-body">
                <div class="elicitation-label">Tool confirmation</div>
                <div class="elicitation-desc">{{ elicit.description }}</div>
                <div class="elicitation-actions">
                  <button mat-flat-button color="primary" (click)="respondElicitation(true)">
                    Accept
                  </button>
                  <button mat-stroked-button (click)="respondElicitation(false)">Decline</button>
                </div>
              </div>
            </div>
          }
        }

        @if (error()) {
          <div class="chat-error">
            <mat-icon>error_outline</mat-icon>
            <span>{{ error() }}</span>
          </div>
        }
      </div>

      @if (threadId()) {
        <div class="chat-input-container">
          <div class="chat-input-box">
            <textarea
              #chatInput
              class="chat-textarea"
              rows="1"
              [formControl]="followUpText"
              placeholder="Ask a follow-up question..."
              (keydown.enter)="onEnter($event)"
              (input)="autoGrow($event)"
            ></textarea>
            <div class="chat-input-actions">
              @if (mcpConfigs().length > 0) {
                <button
                  class="mcp-toggle"
                  [class.active]="mcpConfigIds().length > 0"
                  [matMenuTriggerFor]="mcpMenu"
                  [matTooltip]="mcpTooltip()"
                >
                  <mat-icon>hub</mat-icon>
                  <span>{{ mcpConfigIds().length }}</span>
                </button>
                <mat-menu #mcpMenu="matMenu">
                  @for (cfg of mcpConfigs(); track cfg.id) {
                    <button
                      mat-menu-item
                      (click)="toggleMcpServer(cfg.id); $event.stopPropagation()"
                    >
                      <mat-icon>{{
                        isMcpSelected(cfg.id) ? 'check_box' : 'check_box_outline_blank'
                      }}</mat-icon>
                      {{ cfg.name }}
                    </button>
                  }
                </mat-menu>
              }
              <span class="spacer"></span>
              <button
                class="send-button"
                (click)="sendFollowUp()"
                [disabled]="isLoading() || !followUpText.value?.trim()"
              >
                <mat-icon>arrow_upward</mat-icon>
              </button>
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow: hidden;
        border-radius: inherit;
      }

      .ai-chat-panel {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        border-radius: inherit;
        height: 100%;
      }

      .chat-messages {
        display: flex;
        flex-direction: column;
        gap: 16px;
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;

        &::-webkit-scrollbar {
          width: 6px;
        }
        &::-webkit-scrollbar-track {
          background: transparent;
          margin: 8px 0;
        }
        &::-webkit-scrollbar-thumb {
          background: rgba(128, 128, 128, 0.3);
          border-radius: 3px;
        }
        &::-webkit-scrollbar-thumb:hover {
          background: rgba(128, 128, 128, 0.5);
        }
      }

      .loading-hint {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 32px;
        color: var(--app-neutral);
        font-size: 13px;
      }

      .chat-message {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        width: fit-content;
        max-width: 85%;
        flex-shrink: 0;

        &.user {
          align-self: flex-end;
        }

        &.assistant {
          align-self: flex-start;
        }
      }

      .avatar {
        flex-shrink: 0;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .assistant-avatar {
        background: var(--app-purple-bg);
        color: var(--app-purple);
      }

      .user-avatar {
        background: var(--mat-sys-primary-container, #e3f2fd);
        color: var(--mat-sys-on-primary-container, #1565c0);
      }

      .message-bubble {
        min-width: 0;
        overflow: hidden;

        .user & {
          background: var(--mat-sys-primary-container, #e3f2fd);
          color: var(--mat-sys-on-primary-container, #1565c0);
          border-radius: 18px 18px 4px 18px;
          padding: 10px 16px;
        }

        .assistant & {
          background: var(--mat-sys-surface-container, #f5f5f5);
          color: var(--mat-sys-on-surface, inherit);
          border-radius: 18px 18px 18px 4px;
          padding: 10px 16px;
        }

        /* Full-bleed: let prose sections control their own padding so artifact cards
           can extend edge-to-edge within the bubble. overflow:hidden + border-radius
           on the parent clips everything to the bubble's rounded corners. */
        .assistant &.has-artifacts {
          padding: 0;
        }
      }

      .has-artifacts .message-content {
        padding: 10px 16px;
      }

      .message-content {
        font-size: 14px;
        line-height: 1.6;
        overflow-x: auto;
      }

      .typing-bubble {
        padding: 14px 20px;
      }

      .typing-indicator {
        display: flex;
        gap: 5px;
        align-items: center;

        span {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--app-neutral);
          animation: typing-bounce 1.4s infinite ease-in-out both;

          &:nth-child(1) {
            animation-delay: 0s;
          }
          &:nth-child(2) {
            animation-delay: 0.2s;
          }
          &:nth-child(3) {
            animation-delay: 0.4s;
          }
        }
      }

      @keyframes typing-bounce {
        0%,
        80%,
        100% {
          transform: scale(0.6);
          opacity: 0.4;
        }
        40% {
          transform: scale(1);
          opacity: 1;
        }
      }

      .tool-call-inline {
        margin: 4px 38px 4px 38px;
        border-radius: 8px;
        border: 1px solid var(--mat-sys-outline-variant);
        overflow: hidden;
        font-size: 12px;
        flex-shrink: 0;
        animation: tool-in 150ms ease-out;

        &.running {
          border-left: 3px solid var(--app-purple);
        }
        &.success {
          border-left: 3px solid var(--app-success);
        }
        &.error {
          border-left: 3px solid var(--app-error);
        }
      }

      @keyframes tool-in {
        from {
          opacity: 0;
          transform: translateY(4px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .tool-call-header {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        cursor: pointer;
        transition: background 0.1s;

        &:hover {
          background: var(--mat-sys-surface-container-low);
        }
      }

      .tool-status-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;

        .running & {
          color: var(--app-purple);
        }
        .success & {
          color: var(--app-success);
        }
        .error & {
          color: var(--app-error);
        }

        &.spinning {
          animation: tool-spin 1.5s linear infinite;
        }
      }

      @keyframes tool-spin {
        from {
          transform: rotate(0deg);
        }
        to {
          transform: rotate(360deg);
        }
      }

      .tool-call-label {
        flex: 1;
        min-width: 0;

        strong {
          font-family: var(--app-font-mono, monospace);
          font-size: 12px;
        }
      }

      .tool-server {
        color: var(--mat-sys-on-surface-variant);
        font-size: 11px;
        margin-left: 4px;
      }

      .tool-expand-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
        color: var(--mat-sys-on-surface-variant);
      }

      .tool-call-section {
        border-top: 1px solid var(--mat-sys-outline-variant);
      }

      .tool-call-section-label {
        font-size: 10px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--mat-sys-on-surface-variant);
        padding: 4px 10px 0;
      }

      .tool-call-arguments,
      .tool-call-result {
        font-size: 11px;
        font-family: var(--app-font-mono, monospace);
        background: var(--mat-sys-surface-variant, #f0f0f0);
        color: var(--mat-sys-on-surface-variant);
        padding: 4px 10px 6px;
        margin: 0;
        max-height: 200px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-all;
        scrollbar-width: thin;
      }

      .message-timestamp {
        font-size: 10px;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 2px;
        padding: 0 4px;
        margin-left: 38px;

        &.user-ts {
          text-align: right;
          margin-left: 0;
          margin-right: 38px;
        }
      }

      .tool-timestamp {
        margin-left: 0;
        padding: 2px 10px 4px;
      }

      .has-artifacts app-artifact-card {
        display: block;
      }

      :host ::ng-deep .markdown-body {
        p {
          margin: 0 0 8px;
        }
        p:last-child {
          margin-bottom: 0;
        }
        strong {
          font-weight: 600;
        }
        ul,
        ol {
          margin: 4px 0 8px;
          padding-left: 20px;
        }
        li {
          margin-bottom: 2px;
        }
        code {
          background: rgba(128, 128, 128, 0.15);
          padding: 1px 4px;
          border-radius: 3px;
          font-size: 13px;
        }
        pre {
          background: rgba(128, 128, 128, 0.1);
          padding: 8px 12px;
          border-radius: 6px;
          overflow-x: auto;
        }
        pre code {
          background: none;
          padding: 0;
        }
        h1,
        h2,
        h3 {
          margin: 12px 0 4px;
          font-size: 15px;
          font-weight: 600;
        }
        table {
          border-collapse: collapse;
          width: 100%;
          font-size: 13px;
          margin: 8px 0;
          border-radius: 6px;
          overflow: hidden;
          border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        }
        th,
        td {
          padding: 8px 12px;
          border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
          text-align: left;
        }
        th {
          font-weight: 600;
          font-size: 11px;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: var(--mat-sys-on-surface-variant, #666);
          background: var(--mat-sys-surface-container, rgba(0, 0, 0, 0.04));
        }
        tr:hover td {
          background: var(--mat-sys-surface-container-low, rgba(0, 0, 0, 0.02));
        }
      }

      .elicitation-card {
        display: flex;
        gap: 12px;
        padding: 14px 16px;
        margin: 0 4px;
        border-radius: 12px;
        border: 1px solid var(--app-warning-bg, #fff3cd);
        background: var(--mat-sys-surface-container, #f5f5f5);
        animation: elicit-in 200ms ease-out;
      }

      @keyframes elicit-in {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .elicitation-icon {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--app-warning-bg, #fff3cd);
        color: var(--app-warning, #e65100);
        display: flex;
        align-items: center;
        justify-content: center;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .elicitation-body {
        flex: 1;
        min-width: 0;
      }

      .elicitation-label {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--app-warning, #e65100);
        margin-bottom: 4px;
      }

      .elicitation-desc {
        font-size: 14px;
        line-height: 1.5;
        margin-bottom: 10px;
      }

      .elicitation-actions {
        display: flex;
        gap: 8px;

        button {
          font-size: 13px;
          height: 32px;
        }
      }

      .twin-approve-card {
        margin: 0 4px;
        border-radius: 12px;
        border: 1px solid var(--app-info-bg, #e3f2fd);
        background: var(--mat-sys-surface-container, #f5f5f5);
        overflow: hidden;
        animation: elicit-in 200ms ease-out;
        padding: 14px;
      }

      .twin-approve-header {
        display: flex;
        gap: 10px;
        align-items: flex-start;
      }

      .twin-approve-icon {
        flex-shrink: 0;
        font-size: 24px;
        width: 24px;
        height: 24px;
        color: var(--app-info, #1976d2);
      }

      .twin-approve-label {
        font-size: 14px;
        font-weight: 600;
      }

      .twin-approve-desc {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 2px;
        line-height: 1.4;
      }

      .twin-approve-summary {
        display: flex;
        gap: 12px;
        padding: 10px 0 0 34px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);

        span {
          padding: 2px 8px;
          border-radius: 10px;
          background: rgba(128, 128, 128, 0.1);
        }
      }

      .twin-approve-actions {
        display: flex;
        gap: 8px;
        padding-top: 12px;
        justify-content: flex-end;

        button {
          font-size: 13px;
          height: 32px;
        }
      }

      .chat-error {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--app-error);
        padding: 8px 12px;
        font-size: 13px;
        border-radius: var(--app-radius-sm);
        background: var(--app-error-bg);

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .compaction-notice {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        margin: 4px 0;
        border-radius: 12px;
        background: var(--app-neutral-bg);
        color: var(--app-neutral-text);
        font-size: 12px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .chat-input-container {
        padding: 12px 16px;
        border-top: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        flex-shrink: 0;
      }

      .chat-input-box {
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 20px;
        background: var(--mat-sys-surface-container, #f5f5f5);
        padding: 8px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition:
          border-color 0.15s ease,
          box-shadow 0.15s ease;

        &:focus-within {
          border-color: var(--mat-sys-primary, #1976d2);
          box-shadow: 0 0 0 1px var(--mat-sys-primary, #1976d2);
        }
      }

      .chat-textarea {
        width: 100%;
        margin: 0;
        box-sizing: border-box;
        border: none;
        padding: 8px 12px;
        font: inherit;
        font-size: 14px;
        line-height: 1.5;
        resize: none;
        overflow-y: auto;
        background: transparent;
        color: var(--mat-sys-on-surface, inherit);
        outline: none;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;

        &::-webkit-scrollbar {
          width: 6px;
        }
        &::-webkit-scrollbar-track {
          background: transparent;
          margin: 4px 0;
        }
        &::-webkit-scrollbar-thumb {
          background: rgba(128, 128, 128, 0.3);
          border-radius: 3px;
        }
        &::-webkit-scrollbar-thumb:hover {
          background: rgba(128, 128, 128, 0.5);
        }

        &:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        &::placeholder {
          color: var(--app-neutral);
        }
      }

      .chat-input-actions {
        display: flex;
        align-items: center;
        padding: 0 4px;
      }

      .spacer {
        flex: 1;
      }

      .send-button {
        flex-shrink: 0;
        width: 36px;
        height: 36px;
        border-radius: 50%;
        border: none;
        background: var(--mat-sys-primary, #1976d2);
        color: var(--mat-sys-on-primary, #fff);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: opacity 0.15s ease;

        &:hover:not(:disabled) {
          opacity: 0.85;
        }

        &:disabled {
          background: var(--app-neutral);
          opacity: 0.3;
          cursor: not-allowed;
        }

        mat-icon {
          font-size: 20px;
          width: 20px;
          height: 20px;
        }
      }
    `,
  ],
})
export class AiChatPanelComponent {
  /** Thread ID for follow-up messages */
  threadId = input<string | null>(null);

  /** Initial summary to display — set by parent, rendered on init */
  initialSummary = input<string | null>(null);

  /** Error message from parent */
  errorMessage = input<string | null>(null);

  /** Loading state from parent (initial summary generation) */
  parentLoading = input(false);

  /** Label shown during initial loading (default: "Thinking...") */
  loadingLabel = input('Thinking...');

  /** Pre-loaded messages (for loading existing threads). Takes priority over initialSummary. */
  initialMessages = input<ChatMessage[]>([]);

  /** Available MCP server configs */
  mcpConfigs = input<McpConfigAvailable[]>([]);

  /** Currently selected MCP config IDs (two-way bindable) */
  mcpConfigIds = model<string[]>([]);

  /** Emits when a follow-up is sent */
  followUpSent = output<void>();

  private readonly llmService = inject(LlmService);
  private readonly wsService = inject(WebSocketService);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);
  private readonly artifactParser = inject(ArtifactParserService);
  private readonly chatMessagesEl = viewChild<ElementRef<HTMLDivElement>>('chatMessages');
  private readonly chatInputEl = viewChild<ElementRef<HTMLTextAreaElement>>('chatInput');
  private streamSub: Subscription | null = null;
  private _artifactBuffer: string | null = null;
  private _artifactMeta: { type: string; title: string; language?: string } | null = null;
  /** Tracks how far into streamedContent has been fully rendered, so new artifact detection
   *  starts AFTER already-processed artifacts and doesn't re-match their opening tags. */
  private _streamProcessedTo = 0;

  /** Unified chronological timeline of messages and tool calls */
  timeline = signal<TimelineItem[]>([]);
  loading = signal(false);
  readonly isCompacted = signal(false);
  error = signal<string | null>(null);
  pendingElicitation = signal<{
    requestId: string;
    description: string;
    elicitationType?: string;
    data?: any;
  } | null>(null);
  /** True after a tool completes, until next thinking/tool_start arrives */
  waitingAfterTool = signal(false);
  followUpText = new FormControl('');

  isLoading = computed(() => this.loading() || this.parentLoading());
  hasStreamingContent = computed(() => {
    const tl = this.timeline();
    const last = tl[tl.length - 1];
    return (
      !!last && last.kind === 'message' && last.role === 'assistant' && last.content.length > 0
    );
  });
  hasToolCalls = computed(() => this.timeline().some((item) => item.kind === 'tool'));

  isMcpSelected(id: string): boolean {
    return this.mcpConfigIds().includes(id);
  }

  toggleMcpServer(id: string): void {
    const current = this.mcpConfigIds();
    if (current.includes(id)) {
      this.mcpConfigIds.set(current.filter((i) => i !== id));
    } else {
      this.mcpConfigIds.set([...current, id]);
    }
  }

  mcpTooltip = computed(() => {
    const ids = new Set(this.mcpConfigIds());
    const names = this.mcpConfigs()
      .filter((c) => ids.has(c.id))
      .map((c) => c.name);
    return names.length ? 'MCP: ' + names.join(', ') : 'No MCP servers active';
  });

  constructor() {
    // Auto-focus textarea when loading completes (only if user hasn't clicked elsewhere)
    effect(() => {
      const loading = this.isLoading();
      const thread = this.threadId();
      if (!loading && thread) {
        afterNextRender(
          () => {
            const el = this.chatInputEl()?.nativeElement;
            if (el && (!document.activeElement || document.activeElement === document.body)) {
              el.focus();
            }
          },
          { injector: this.injector },
        );
      }
    });

    // Reactively populate messages when initialSummary input changes
    // Replaces the last streamed assistant bubble with the final polished response
    effect(() => {
      const summary = this.initialSummary();
      if (!summary) return;
      untracked(() => {
        this.timeline.update((tl) => {
          let trimIdx = tl.length;
          while (
            trimIdx > 0 &&
            tl[trimIdx - 1].kind === 'message' &&
            (tl[trimIdx - 1] as { role: string }).role === 'assistant'
          ) {
            trimIdx--;
          }
          const existingTs = trimIdx < tl.length ? tl[trimIdx].timestamp : new Date().toISOString();
          const items = this._buildArtifactTimeline(summary, 'assistant', existingTs);
          const base = tl.slice(0, trimIdx);
          return [...base, ...items];
        });
      });
      this.streamSub?.unsubscribe();
      this.streamSub = null;
      this._artifactBuffer = null;
      this._artifactMeta = null;
      this.scrollToBottom();
    });
    // Load pre-existing messages (thread history) or clear on reset
    effect(() => {
      const msgs = this.initialMessages();
      if (msgs.length === 0) return; // Don't kill active stream on default empty init
      this.streamSub?.unsubscribe();
      this.streamSub = null;
      this.loading.set(false);
      this.error.set(null);
      this.pendingElicitation.set(null);
      this.followUpText.reset();
      // Reconstruct timeline: insert thinking texts + tool calls from metadata before assistant messages
      const tl: TimelineItem[] = [];
      for (const m of msgs) {
        if (m.metadata && m.role === 'assistant') {
          // Insert thinking texts (intermediate reasoning) before tool calls
          const thinkingTexts: string[] = m.metadata.thinking_texts ?? [];
          const toolCallsList = m.metadata.tool_calls ?? [];
          // Interleave: thinking[0] → tool calls → thinking[1] → ... → final assistant message
          for (let i = 0; i < Math.max(thinkingTexts.length, toolCallsList.length); i++) {
            if (i < thinkingTexts.length && thinkingTexts[i]) {
              tl.push({
                kind: 'message',
                role: 'assistant',
                content: thinkingTexts[i],
                html: renderMarkdown(thinkingTexts[i]),
                timestamp: m.timestamp,
              });
            }
            if (i < toolCallsList.length) {
              const tc = toolCallsList[i];
              tl.push({
                kind: 'tool',
                tool: tc.tool,
                server: tc.server,
                status: (tc.status as 'success' | 'error') || 'success',
                arguments: tc.arguments,
                resultPreview: tc.result_preview,
                expanded: false,
                timestamp: m.timestamp,
              });
            }
          }
        }
        // Skip empty assistant messages (tool-call-only responses have no text content)
        if (m.role === 'assistant' && m.content?.trim()) {
          const parsed = this._buildArtifactTimeline(m.content, 'assistant', m.timestamp);
          tl.push(...parsed);
        } else if (m.role === 'user' || m.content?.trim()) {
          tl.push({
            kind: 'message',
            role: m.role as 'user' | 'assistant',
            content: m.content,
            html: m.role === 'assistant' ? renderMarkdown(m.content) : '',
            timestamp: m.timestamp,
          });
        }
      }
      this.timeline.set(tl);
      if (msgs.length > 0) this.scrollToBottom();
    });
    effect(() => {
      this.error.set(this.errorMessage());
    });
  }

  /** Auto-grow textarea up to 10 lines, then scroll */
  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 210) + 'px';
  }

  /** Enter sends, Shift+Enter inserts newline */
  onEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (!ke.shiftKey) {
      ke.preventDefault();
      if (!this.isLoading()) {
        this.sendFollowUp();
      }
    }
  }

  sendFollowUp(): void {
    const text = (this.followUpText.value ?? '').trim();
    const thread = this.threadId();
    if (!text || !thread || this.isLoading()) return;

    this.timeline.update((tl) => [
      ...tl,
      {
        kind: 'message' as const,
        role: 'user' as const,
        content: text,
        html: '',
        timestamp: new Date().toISOString(),
      },
    ]);
    this.followUpText.reset();
    this.loading.set(true);
    this.error.set(null);
    this.waitingAfterTool.set(false);
    this.scrollToBottom();

    // Subscribe to streaming tokens via WebSocket
    const streamId = crypto.randomUUID();
    this._streamProcessedTo = 0;
    this._subscribeToStream(`llm:${streamId}`);

    // Send API request with stream_id
    this.llmService.followUp(thread, text, streamId, this.mcpConfigIds()).subscribe({
      next: (res) => {
        // Replace the last streamed assistant bubble with the final artifact-aware response
        this.timeline.update((tl) => {
          const last = tl[tl.length - 1];
          const ts =
            last?.kind === 'message' && last.role === 'assistant'
              ? last.timestamp
              : new Date().toISOString();
          const items = this._buildArtifactTimeline(res.reply, 'assistant', ts);
          if (last?.kind === 'message' && last.role === 'assistant') {
            return [...tl.slice(0, -1), ...items];
          }
          return [...tl, ...items];
        });
        this.loading.set(false);
        this.followUpSent.emit();
        this.scrollToBottom();
      },
      error: (err) => {
        this.streamSub?.unsubscribe();
        this.streamSub = null;
        this.error.set(extractErrorMessage(err));
        this.loading.set(false);
      },
    });
  }

  /** Parse content through artifact parser and return a single message with inline sections. */
  private _buildArtifactTimeline(
    content: string,
    role: 'user' | 'assistant',
    timestamp?: string,
  ): TimelineItem[] {
    if (role === 'user') {
      return [{ kind: 'message', role, content, html: '', timestamp }];
    }
    const parsed = this.artifactParser.parse(content);
    if (parsed.artifacts.length === 0) {
      return [{ kind: 'message', role, content, html: renderMarkdown(content), timestamp }];
    }
    // Build interleaved sections: prose + artifact + prose + ...
    const sections: MessageSection[] = [];
    const parts = parsed.prose.split(/\[artifact:[^\]]+\]/);
    const placeholders = [...parsed.prose.matchAll(/\[artifact:([^\]]+)\]/g)];
    for (let i = 0; i < parts.length; i++) {
      const text = parts[i].replace(/^\n+|\n+$/g, '');
      if (text) {
        sections.push({ type: 'prose', html: renderMarkdown(text) });
      }
      if (i < placeholders.length) {
        const artifactId = placeholders[i][1];
        const artifact = parsed.artifacts.find((a) => a.id === artifactId);
        if (artifact) {
          sections.push({ type: 'artifact', artifact, state: 'ready' });
        }
      }
    }
    return [{ kind: 'message', role, content, html: '', sections, timestamp }];
  }

  /** Subscribe to a WS stream channel and handle all event types. */
  private _subscribeToStream(channel: string): void {
    let streamedContent = '';
    let needsNewBubble = false;
    let streamTimestamp = new Date().toISOString();

    this.streamSub?.unsubscribe();
    this.streamSub = this.wsService
      .subscribe<{
        type: string;
        content?: string;
        tool?: string;
        server?: string;
        status?: string;
        arguments?: Record<string, unknown>;
        result_preview?: string;
        request_id?: string;
        description?: string;
        elicitation_type?: string;
        data?: RestoreDiffData;
      }>(channel)
      .subscribe((msg) => {
        if (msg.type === 'tool_start' && msg.tool) {
          this.waitingAfterTool.set(false);
          needsNewBubble = true;
          this.timeline.update((tl) => [
            ...tl,
            {
              kind: 'tool' as const,
              tool: msg.tool!,
              server: msg.server ?? '',
              status: 'running' as const,
              arguments: msg.arguments,
              expanded: false,
              timestamp: new Date().toISOString(),
            },
          ]);
          this.scrollToBottom();
        } else if (msg.type === 'tool_end' && msg.tool) {
          this.waitingAfterTool.set(true);
          this.timeline.update((tl) =>
            tl.map((item) =>
              item.kind === 'tool' && item.tool === msg.tool && item.status === 'running'
                ? {
                    ...item,
                    status: msg.status === 'error' ? ('error' as const) : ('success' as const),
                    resultPreview: msg.result_preview,
                  }
                : item,
            ),
          );
        } else if (msg.type === 'thinking' && msg.content) {
          this.waitingAfterTool.set(false);
          if (needsNewBubble) {
            streamedContent = '';
            streamTimestamp = new Date().toISOString();
            needsNewBubble = false;
          }
          streamedContent += msg.content;
          const entry: TimelineItem = {
            kind: 'message',
            role: 'assistant',
            content: streamedContent,
            html: renderMarkdown(streamedContent),
            timestamp: streamTimestamp,
          };
          this.timeline.update((tl) => {
            const last = tl[tl.length - 1];
            if (
              last?.kind === 'message' &&
              last.role === 'assistant' &&
              streamedContent.length > msg.content!.length
            ) {
              return [...tl.slice(0, -1), entry];
            }
            return [...tl, entry];
          });
          this.scrollToBottom();
        } else if (msg.type === 'token') {
          if (needsNewBubble) {
            streamedContent = '';
            streamTimestamp = new Date().toISOString();
            needsNewBubble = false;
          }
          this.waitingAfterTool.set(false);
          streamedContent += msg.content ?? '';

          if (this._artifactBuffer !== null) {
            // Buffering artifact content
            this._artifactBuffer += msg.content ?? '';
            if (this.artifactParser.hasClosingTag(this._artifactBuffer)) {
              // Artifact complete -- parse and render as single message with sections
              const items = this._buildArtifactTimeline(
                streamedContent,
                'assistant',
                streamTimestamp,
              );
              this.timeline.update((tl) => {
                // Remove the last assistant message (which had the loading artifact)
                const trimmed = tl.filter(
                  (item, idx) =>
                    !(
                      idx === tl.length - 1 &&
                      item.kind === 'message' &&
                      item.role === 'assistant'
                    ),
                );
                return [...trimmed, ...items];
              });
              this._artifactBuffer = null;
              this._artifactMeta = null;
              this._streamProcessedTo = streamedContent.length;
            }
          } else {
            // Search only from the last fully-processed position so prior artifact opening tags
            // are not re-matched when a subsequent artifact starts streaming.
            const unprocessed = streamedContent.slice(this._streamProcessedTo);
            const rawMeta = this.artifactParser.detectOpeningTag(unprocessed);
            const tagMeta = rawMeta
              ? {
                  ...rawMeta,
                  startIndex: rawMeta.startIndex + this._streamProcessedTo,
                  endIndex: rawMeta.endIndex + this._streamProcessedTo,
                }
              : null;
            const contentFromTag = tagMeta ? streamedContent.slice(tagMeta.startIndex) : '';
            if (tagMeta && !this.artifactParser.hasClosingTag(contentFromTag)) {
              // Opening tag detected -- start buffering, capture any content already after the tag
              this._artifactMeta = tagMeta;
              this._artifactBuffer = streamedContent.slice(tagMeta.endIndex);
              const proseBeforeTag = streamedContent
                .slice(0, tagMeta.startIndex)
                .replace(/^\n+|\n+$/g, '');
              const loadingArtifact: Artifact = {
                id: crypto.randomUUID(),
                type: tagMeta.type as Artifact['type'],
                title: tagMeta.title,
                language: tagMeta.language,
                content: '',
              };
              const sections: MessageSection[] = [];
              if (proseBeforeTag) {
                sections.push({ type: 'prose', html: renderMarkdown(proseBeforeTag) });
              }
              sections.push({ type: 'artifact', artifact: loadingArtifact, state: 'loading' });
              const entry: TimelineItem = {
                kind: 'message',
                role: 'assistant',
                content: streamedContent,
                html: '',
                sections,
                timestamp: streamTimestamp,
              };
              this.timeline.update((tl) => {
                const last = tl[tl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  return [...tl.slice(0, -1), entry];
                }
                return [...tl, entry];
              });
            } else if (tagMeta && this.artifactParser.hasClosingTag(contentFromTag)) {
              // Complete artifact arrived in one chunk
              this._streamProcessedTo = streamedContent.length;
              const items = this._buildArtifactTimeline(
                streamedContent,
                'assistant',
                streamTimestamp,
              );
              this.timeline.update((tl) => {
                const last = tl[tl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  return [...tl.slice(0, -1), ...items];
                }
                return [...tl, ...items];
              });
            } else {
              // Normal text
              const entry: TimelineItem = {
                kind: 'message',
                role: 'assistant',
                content: streamedContent,
                html: renderMarkdown(streamedContent),
                timestamp: streamTimestamp,
              };
              this.timeline.update((tl) => {
                const last = tl[tl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  return [...tl.slice(0, -1), entry];
                }
                return [...tl, entry];
              });
            }
          }
          this.scrollToBottom();
        } else if (msg.type === 'elicitation' && msg.request_id && msg.description) {
          this.pendingElicitation.set({
            requestId: msg.request_id,
            description: msg.description,
            elicitationType: msg.elicitation_type,
            data: msg.data,
          });
          this.scrollToBottom();
        } else if (msg.type === 'done') {
          if (this._artifactBuffer !== null && this._artifactMeta) {
            const truncatedArtifact: Artifact = {
              id: crypto.randomUUID(),
              type: (this._artifactMeta.type as Artifact['type']) || 'code',
              title: this._artifactMeta.title + ' (Truncated)',
              language: this._artifactMeta.language,
              content: this._artifactBuffer,
            };
            const section: MessageSection = {
              type: 'artifact',
              artifact: truncatedArtifact,
              state: 'ready',
            };
            this.timeline.update((tl) => {
              const last = tl[tl.length - 1];
              if (last?.kind === 'message' && last.role === 'assistant' && last.sections?.length) {
                // Replace loading section with ready truncated artifact
                const updatedSections = last.sections.map((s) =>
                  s.type === 'artifact' && s.state === 'loading' ? section : s,
                );
                return [...tl.slice(0, -1), { ...last, sections: updatedSections }];
              }
              return [
                ...tl,
                {
                  kind: 'message' as const,
                  role: 'assistant' as const,
                  content: '',
                  html: '',
                  sections: [section],
                  timestamp: streamTimestamp,
                },
              ];
            });
            this._artifactBuffer = null;
            this._artifactMeta = null;
          }
          this.streamSub?.unsubscribe();
          this.streamSub = null;
        }
      });
  }

  /** Start streaming for initial message flow — called by parent before HTTP request. */
  startStream(streamId: string, userMessage: string): void {
    this.timeline.set([
      {
        kind: 'message' as const,
        role: 'user' as const,
        content: userMessage,
        html: '',
        timestamp: new Date().toISOString(),
      },
    ]);
    this.waitingAfterTool.set(false);
    this._artifactBuffer = null;
    this._artifactMeta = null;
    this._streamProcessedTo = 0;
    this._subscribeToStream(`llm:${streamId}`);
  }

  /** Reset all state — called by parent when starting a new chat. */
  reset(): void {
    this.streamSub?.unsubscribe();
    this.streamSub = null;
    this.timeline.set([]);
    this.loading.set(false);
    this.error.set(null);
    this.pendingElicitation.set(null);
    this.waitingAfterTool.set(false);
    this.isCompacted.set(false);
    this.followUpText.reset();
    this._artifactBuffer = null;
    this._artifactMeta = null;
    this._streamProcessedTo = 0;
  }

  /** Show compaction notice at the top of the timeline (called once when thread is loaded). */
  setCompacted(compacted: boolean): void {
    if (compacted && !this.isCompacted()) {
      this.isCompacted.set(true);
      this.timeline.update((items) => {
        const notice: TimelineItem = { kind: 'compaction' };
        return [notice, ...items];
      });
    }
  }

  toggleToolExpand(index: number): void {
    this.timeline.update((tl) =>
      tl.map((item, i) =>
        i === index && item.kind === 'tool' ? { ...item, expanded: !item.expanded } : item,
      ),
    );
  }

  objectKeys = Object.keys;

  formatJson(obj: Record<string, unknown>): string {
    return JSON.stringify(obj, null, 2);
  }

  formatTimestamp(ts: string): string {
    const d = new Date(ts.endsWith('Z') || ts.includes('+') ? ts : ts + 'Z');
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const pad = (n: number) => n.toString().padStart(2, '0');
    const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === now.toDateString()) return time;
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ];
    const date = `${months[d.getMonth()]} ${d.getDate()}`;
    if (d.getFullYear() === now.getFullYear()) return `${date}, ${time}`;
    return `${date} ${d.getFullYear()}, ${time}`;
  }

  private _twinResultCache = new Map<string, TwinResultData | null>();

  _parseTwinResult(resultPreview: string | undefined): TwinResultData | null {
    if (!resultPreview) return null;
    const cached = this._twinResultCache.get(resultPreview);
    if (cached !== undefined) return cached;
    try {
      const parsed = JSON.parse(resultPreview);
      const result = parsed?.counts && parsed?.overall_severity ? (parsed as TwinResultData) : null;
      this._twinResultCache.set(resultPreview, result);
      return result;
    } catch {
      this._twinResultCache.set(resultPreview, null);
      return null;
    }
  }

  respondElicitation(accepted: boolean): void {
    const elicit = this.pendingElicitation();
    if (!elicit) return;
    this.pendingElicitation.set(null);
    this.llmService
      .respondToElicitation(elicit.requestId, accepted)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err) => {
          console.error('Failed to respond to elicitation:', err);
        },
      });
  }

  private scrollToBottom(): void {
    afterNextRender(
      () => {
        const el = this.chatMessagesEl()?.nativeElement;
        if (!el) return;
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      },
      { injector: this.injector },
    );
  }
}
