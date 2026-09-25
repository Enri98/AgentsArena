/**
 * A WebSocket connection with an ordered message inbox.
 *
 * Pings are answered as soon as they arrive, even while the caller is busy
 * deciding (an LLM can take longer than the server's heartbeat allows).
 * Everything else is queued in order for `next()`.
 */

import {
  ConnectionClosedError,
  type Envelope,
  ProtocolError,
  type ServerMessage,
  WIRE_SCHEMA_VERSION,
  parseMessage,
} from "./protocol.ts";

type Waiter = {
  resolve: (message: ServerMessage) => void;
  reject: (error: Error) => void;
};

export class Connection {
  readonly #socket: WebSocket;
  readonly #inbox: ServerMessage[] = [];
  readonly #waiters: Waiter[] = [];
  #closed: ConnectionClosedError | null = null;

  private constructor(socket: WebSocket) {
    this.#socket = socket;
    socket.addEventListener("message", (event: MessageEvent) => this.#onMessage(event));
    socket.addEventListener("close", (event: CloseEvent) => {
      this.#closed = new ConnectionClosedError(event.code, event.reason);
      for (const waiter of this.#waiters.splice(0)) waiter.reject(this.#closed);
    });
  }

  /** Open a connection; rejects if the socket cannot open. */
  static open(url: string): Promise<Connection> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      const connection = new Connection(socket);
      socket.addEventListener("open", () => resolve(connection), { once: true });
      socket.addEventListener(
        "close",
        (event: CloseEvent) => reject(new ConnectionClosedError(event.code, event.reason)),
        { once: true },
      );
    });
  }

  send(envelope: Envelope): void {
    if (this.#closed) throw this.#closed;
    this.#socket.send(JSON.stringify(envelope));
  }

  /** The next message in order; rejects once the connection has closed. */
  next(timeoutMs?: number): Promise<ServerMessage> {
    const queued = this.#inbox.shift();
    if (queued) return Promise.resolve(queued);
    if (this.#closed) return Promise.reject(this.#closed);
    return new Promise((resolve, reject) => {
      const waiter: Waiter = { resolve, reject };
      this.#waiters.push(waiter);
      if (timeoutMs !== undefined) {
        setTimeout(() => {
          const index = this.#waiters.indexOf(waiter);
          if (index >= 0) {
            this.#waiters.splice(index, 1);
            reject(new ProtocolError(`no message within ${timeoutMs} ms`));
          }
        }, timeoutMs);
      }
    });
  }

  close(code = 1000, reason = ""): void {
    if (!this.#closed) this.#socket.close(code, reason);
  }

  #onMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return; // the server sends text frames only
    let message: ServerMessage | null;
    try {
      message = parseMessage(event.data);
    } catch {
      return; // a frame we cannot parse is dropped, like an unknown type
    }
    if (message === null) return; // section 7: ignore unknown message types
    if (message.type === "ping") {
      this.send({
        type: "pong",
        schema_version: WIRE_SCHEMA_VERSION,
        match_id: message.match_id ?? null,
        payload: { nonce: message.payload.nonce },
      });
      return;
    }
    const waiter = this.#waiters.shift();
    if (waiter) waiter.resolve(message);
    else this.#inbox.push(message);
  }
}
