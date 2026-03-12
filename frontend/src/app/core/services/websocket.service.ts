import { Injectable, inject } from '@angular/core';
import { BehaviorSubject, Observable, Subject, filter, map } from 'rxjs';
import { TokenService } from './token.service';

interface WsMessage {
  type: string;
  channel?: string;
  data?: unknown;
}

@Injectable({ providedIn: 'root' })
export class WebSocketService {
  private readonly tokenService = inject(TokenService);

  private ws: WebSocket | null = null;
  private readonly message$ = new Subject<WsMessage>();
  private readonly connectedSubject = new BehaviorSubject(false);

  /** Observable of connection status. */
  readonly connected$ = this.connectedSubject.asObservable();

  /** Channels with active subscriber count. */
  private readonly channelRefs = new Map<string, number>();

  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private pingTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private authenticated = false;

  /**
   * Subscribe to a WebSocket channel. Lazily opens the connection on first call.
   * Returns an Observable of messages for the given channel.
   */
  subscribe<T = unknown>(channel: string): Observable<T> {
    const current = this.channelRefs.get(channel) ?? 0;
    if (current === 0) {
      this.ensureConnection();
      this.sendSubscribe(channel);
    }
    this.channelRefs.set(channel, current + 1);

    return new Observable<T>((subscriber) => {
      const sub = this.message$
        .pipe(
          filter((msg) => msg.type !== 'ping' && msg.type !== 'pong'),
          filter((msg) => !msg.channel || msg.channel === channel),
          map((msg) => msg as unknown as T),
        )
        .subscribe(subscriber);

      return () => {
        sub.unsubscribe();
        const refs = (this.channelRefs.get(channel) ?? 1) - 1;
        if (refs <= 0) {
          this.channelRefs.delete(channel);
          this.sendUnsubscribe(channel);
          if (this.channelRefs.size === 0) {
            this.closeConnection();
          }
        } else {
          this.channelRefs.set(channel, refs);
        }
      };
    });
  }

  private ensureConnection(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.connect();
  }

  private connect(): void {
    const token = this.tokenService.getToken();
    if (!token) return;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${window.location.host}/api/v1/ws`;

    this.intentionalClose = false;
    this.authenticated = false;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      // Send auth message as first frame
      this.ws?.send(JSON.stringify({ type: 'auth', token }));
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);

        // Handle auth response
        if (msg.type === 'auth_ok') {
          this.authenticated = true;
          this.connectedSubject.next(true);
          this.reconnectDelay = 1000;
          // Re-subscribe all active channels after auth
          for (const ch of this.channelRefs.keys()) {
            this.sendSubscribe(ch);
          }
          this.startPingMonitor();
          return;
        }

        if (msg.type === 'auth_error') {
          this.ws?.close();
          return;
        }

        if (msg.type === 'ping') {
          this.ws?.send(JSON.stringify({ type: 'pong' }));
          this.resetPingMonitor();
          return;
        }
        this.message$.next(msg);
      } catch {
        // Ignore non-JSON messages
      }
    };

    this.ws.onclose = () => {
      this.authenticated = false;
      this.connectedSubject.next(false);
      this.stopPingMonitor();
      if (!this.intentionalClose && this.channelRefs.size > 0) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror
    };
  }

  private closeConnection(): void {
    this.intentionalClose = true;
    this.authenticated = false;
    this.stopPingMonitor();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connectedSubject.next(false);
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
  }

  private sendSubscribe(channel: string): void {
    if (this.ws?.readyState === WebSocket.OPEN && this.authenticated) {
      this.ws.send(JSON.stringify({ action: 'subscribe', channel }));
    }
  }

  private sendUnsubscribe(channel: string): void {
    if (this.ws?.readyState === WebSocket.OPEN && this.authenticated) {
      this.ws.send(JSON.stringify({ action: 'unsubscribe', channel }));
    }
  }

  // If no ping received within 45s, consider connection dead
  private startPingMonitor(): void {
    this.stopPingMonitor();
    this.pingTimer = setTimeout(() => {
      this.ws?.close();
    }, 45000);
  }

  private resetPingMonitor(): void {
    this.startPingMonitor();
  }

  private stopPingMonitor(): void {
    if (this.pingTimer) {
      clearTimeout(this.pingTimer);
      this.pingTimer = null;
    }
  }
}
