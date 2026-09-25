/**
 * Playing a seat: the `hello`/`welcome` handshake, then observation requests
 * answered with actions until the match ends (docs/NETWORK_PROTOCOL.md sections
 * 5, 8 and 11).
 */

import { Connection } from "./connection.ts";
import {
  CLIENT_NAME,
  CLIENT_VERSION,
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
  /** How long to wait for `welcome`, in milliseconds (default 10 000). */
  handshakeTimeoutMs?: number;
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
    const connection = await Connection.open(url);
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
      connection.close();
      throw new ProtocolError(`expected welcome, got ${first.type}`);
    }
    if (first.payload.seat !== seat) {
      connection.close();
      throw new ProtocolError(`asked for seat ${seat}, got seat ${first.payload.seat}`);
    }
    return new SeatSession(connection, first.payload);
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
  sendAction(action: JsonObject, turnId: string = crypto.randomUUID()): string {
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

/** Chooses an action for an observation request; may be async (an LLM call). */
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
  try {
    for (;;) {
      const message = await session.recv();
      switch (message.type) {
        case "observation_request":
          pending = message.payload.observation_request;
          session.sendAction(await choose(pending));
          break;
        case "action_rejected":
          // The turn is still open and no new request follows: choose again,
          // unless that was the last attempt (the abort follows).
          if (pending && message.payload.retries_remaining > 0) {
            session.sendAction(await choose(pending));
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
