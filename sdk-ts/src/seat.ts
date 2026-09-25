/**
 * Playing a seat: the `hello`/`welcome` handshake, then observation requests
 * answered with actions until the match ends (docs/NETWORK_PROTOCOL.md sections
 * 5, 8 and 11).
 */

import { Connection } from "./connection.ts";
import {
  CLIENT_NAME,
  CLIENT_VERSION,
  ConnectionClosedError,
  type JsonObject,
  MatchAbortedError,
  type ObservationRequest,
  ProtocolError,
  type RuntimeTranscript,
  SUPPORTED_SCHEMA_VERSIONS,
  type ServerMessage,
  WIRE_SCHEMA_VERSION,
  type WelcomeBody,
} from "./protocol.ts";

export interface ConnectOptions {
  /** A token from an earlier `welcome`, to resume a dropped seat (section 11). */
  resumeToken?: string;
  /** How long to wait for the socket to open and then for `welcome`, in ms (default 10 000 each). */
  handshakeTimeoutMs?: number;
}

/** A fresh turn id. `crypto.randomUUID` is missing outside secure contexts (plain http pages). */
function newTurnId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid;
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** A connected seat: the low-level loop form. */
export class SeatSession {
  readonly welcome: WelcomeBody;
  readonly #connection: Connection;

  private constructor(connection: Connection, welcome: WelcomeBody) {
    this.#connection = connection;
    this.welcome = welcome;
  }

  /** Connect to a seat URL (`.../matches/{id}/play?seat=N`) and say hello. */
  static async connect(url: string, seat: number, options: ConnectOptions = {}): Promise<SeatSession> {
    const timeoutMs = options.handshakeTimeoutMs ?? 10_000;
    const connection = await Connection.open(url, timeoutMs);
    try {
      return new SeatSession(connection, await SeatSession.#handshake(connection, seat, options));
    } catch (error) {
      connection.close(); // never leave a socket open behind a failed handshake
      throw error;
    }
  }

  static async #handshake(connection: Connection, seat: number, options: ConnectOptions): Promise<WelcomeBody> {
    connection.send({
      type: "hello",
      schema_version: WIRE_SCHEMA_VERSION,
      seat,
      payload: {
        client_name: CLIENT_NAME,
        client_version: CLIENT_VERSION,
        supported_schema_versions: [...SUPPORTED_SCHEMA_VERSIONS],
        auth: null,
        requested_seat: seat,
        resume_token: options.resumeToken ?? null,
      },
    });
    const first = await connection.next(options.handshakeTimeoutMs ?? 10_000);
    if (first.type !== "welcome") {
      throw new ProtocolError(`expected welcome, got ${first.type}`);
    }
    if (first.payload.seat !== seat) {
      throw new ProtocolError(`asked for seat ${seat}, got seat ${first.payload.seat}`);
    }
    return first.payload;
  }

  get matchId(): string {
    return this.welcome.match_id;
  }

  get seat(): number {
    return this.welcome.seat;
  }

  /** The token that resumes this seat if the connection drops (rotates on each welcome). */
  get resumeToken(): string | null {
    return this.welcome.resume_token;
  }

  /** The next server message (pings are answered for you and never returned). */
  recv(timeoutMs?: number): Promise<ServerMessage> {
    return this.#connection.next(timeoutMs);
  }

  /** Answer the current observation request with a game-specific action. */
  sendAction(action: JsonObject, turnId: string = newTurnId()): string {
    this.#connection.send({
      type: "action_response",
      schema_version: WIRE_SCHEMA_VERSION,
      match_id: this.matchId,
      seat: this.seat,
      turn_id: turnId,
      payload: {
        action_response: {
          game_id: this.welcome.game_id,
          schema_version: 1,
          seat: this.seat,
          action,
        },
      },
    });
    return turnId;
  }

  close(): void {
    this.#connection.close();
  }
}

/**
 * Chooses an action for an observation request; may be async (an LLM call).
 *
 * Pings are answered while an async `choose` awaits. A synchronous one that
 * keeps the CPU busy blocks them, and the server's keepalive drops a seat that
 * goes quiet for about 40 s (protocol sections 3 and 8.10): move heavy work off
 * the event loop (a worker) or make it async.
 */
export type ChooseAction = (request: ObservationRequest) => JsonObject | Promise<JsonObject>;

export interface MatchOutcome {
  result: JsonObject;
  transcript: RuntimeTranscript;
}

/**
 * Play a seat to the end: the callback form.
 *
 * `choose` is called for every observation request, and again after a
 * rejection while retries remain. Resolves with the result and this seat's
 * transcript; rejects with `MatchAbortedError` if the match aborts, or
 * `ConnectionClosedError` if the connection drops.
 */
export async function playMatch(
  url: string,
  seat: number,
  choose: ChooseAction,
  options: ConnectOptions = {},
): Promise<MatchOutcome> {
  const session = await SeatSession.connect(url, seat, options);
  let pending: ObservationRequest | null = null;
  // The match can end while `choose` thinks (a deadline, the peer dropping).
  // The terminal frame is then already queued: sending fails, and the next
  // recv() returns it (match_aborted, with the transcript) before reporting
  // the close.
  const answer = async (request: ObservationRequest): Promise<void> => {
    const action = await choose(request);
    try {
      session.sendAction(action);
    } catch (error) {
      if (!(error instanceof ConnectionClosedError)) throw error;
    }
  };
  try {
    for (;;) {
      const message = await session.recv();
      switch (message.type) {
        case "observation_request":
          pending = message.payload.observation_request;
          await answer(pending);
          break;
        case "action_rejected":
          // The turn is still open and no new request follows: choose again,
          // unless that was the last attempt (the abort follows).
          if (pending && message.payload.retries_remaining > 0) {
            await answer(pending);
          }
          break;
        case "match_finished":
          return { result: message.payload.result, transcript: message.payload.transcript };
        case "match_aborted":
          throw new MatchAbortedError(message.payload);
        default:
          break; // match_state, turn_committed, error: bookkeeping
      }
    }
  } finally {
    session.close();
  }
}
