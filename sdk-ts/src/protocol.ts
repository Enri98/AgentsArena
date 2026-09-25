/**
 * AgentsArena wire protocol types (docs/NETWORK_PROTOCOL.md), schema_version 4.
 *
 * Game-specific payloads (observations, actions, states, events) are plain
 * JSON: their shape is each game's, published as JSON Schema at `GET /games`
 * and `GET /schemas/payloads`.
 */

export const WIRE_SCHEMA_VERSION = 4;
/** Versions this client reads. The server serves only its own (section 7). */
export const SUPPORTED_SCHEMA_VERSIONS: readonly number[] = [4];
export const CLIENT_NAME = "arena-sdk-ts";
export const CLIENT_VERSION = "0.1.0";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export interface Envelope<T extends string = string, P = unknown> {
  type: T;
  schema_version: number;
  match_id?: string | null;
  seat?: number | null;
  turn_id?: string | null;
  payload: P;
}

export interface PlayerInfo {
  player_id: string;
  label: string | null;
  seat: number;
}

/** A runtime transcript (section 17): what `match_finished` and friends carry. */
export interface RuntimeTranscript {
  match_id: string;
  game_id: string;
  schema_version: number;
  lifecycle: "created" | "running" | "finished" | "aborted";
  players: { player_id: string; seat: number; label: string | null }[];
  events: { event_scope: "runtime"; event_type: string; payload: JsonObject }[];
  abort: AbortInfo | null;
  match_transcript: MatchTranscript | null;
  view: "full" | "seat" | "public";
  viewer_seat: number | null;
}

export interface MatchTranscript {
  game_id: string;
  schema_version: number;
  config: JsonObject;
  initial_snapshot: JsonObject;
  turns: TurnRecord[];
  view: "full" | "seat" | "public";
  viewer_seat: number | null;
}

/**
 * One committed turn. `kind` is "action" (one seat acted), "chance" (a random
 * outcome resolved; no seat, see `outcome`) or, since v4, "joint" (a
 * simultaneous round: `actions` maps each acting seat, as a string key, to its
 * action; `seat` and `action` are null).
 */
export interface TurnRecord {
  kind: "action" | "chance" | "joint" | string;
  seat: number | null;
  action: JsonObject | null;
  outcome?: JsonObject | null;
  actions?: Record<string, JsonObject>;
  turn_index?: number;
  events: JsonObject[];
  post_snapshot: JsonObject;
  result?: JsonObject | null;
}

export interface AbortInfo {
  reason: string;
  message: string;
  cause_type: string | null;
  cause_message: string | null;
}

export interface DomainError {
  code: string;
  message: string;
  details?: JsonObject | null;
}

export interface ObservationRequest {
  game_id: string;
  schema_version: number;
  seat: number;
  /** Game-specific; includes `legal_actions` for every built-in game. */
  observation: JsonObject;
}

export interface WelcomeBody {
  match_id: string;
  game_id: string;
  game_schema_version: number;
  seat: number;
  lifecycle: string;
  schema_version: number;
  negotiated_schema_version: number;
  resume_token: string | null;
  per_turn_deadline_ms: number;
  per_action_retry_budget: number;
  disconnect_grace_ms: number;
  players: PlayerInfo[];
  match_config: JsonObject;
  transcript: RuntimeTranscript | null;
}

export interface MatchStateBody {
  lifecycle: string;
  current_seat: number | null;
  /** v4: every seat that acts now (several in a simultaneous round). */
  acting_seats?: number[] | null;
  turn_count: number;
  result: JsonObject | null;
  abort: JsonObject | null;
}

export interface ObservationRequestBody {
  observation_request: ObservationRequest;
  deadline_ms: number;
}

export interface ActionRejectedBody {
  turn_id: string;
  error: DomainError;
  /** Further attempts still allowed; 0 on the final rejection (section 8.6). */
  retries_remaining: number;
}

export interface TurnCommittedBody {
  turn_record: TurnRecord;
  post_snapshot: JsonObject;
  events: JsonObject[];
  public_snapshot?: JsonObject | null;
}

export interface MatchFinishedBody {
  result: JsonObject;
  transcript: RuntimeTranscript;
}

export interface MatchAbortedBody {
  abort: AbortInfo;
  transcript: RuntimeTranscript;
}

export interface ErrorBody {
  code: string;
  message: string;
}

export interface SpectatorWelcomeBody {
  match_id: string;
  game_id: string;
  game_schema_version: number;
  lifecycle: string;
  schema_version: number;
  negotiated_schema_version: number;
  players: PlayerInfo[];
  turn_count: number;
  transcript: RuntimeTranscript | null;
}

/** Everything a seat or spectator can receive, discriminated by `type`. */
export type ServerMessage =
  | Envelope<"welcome", WelcomeBody>
  | Envelope<"spectator_welcome", SpectatorWelcomeBody>
  | Envelope<"match_state", MatchStateBody>
  | Envelope<"observation_request", ObservationRequestBody>
  | Envelope<"action_rejected", ActionRejectedBody>
  | Envelope<"turn_committed", TurnCommittedBody>
  | Envelope<"match_finished", MatchFinishedBody>
  | Envelope<"match_aborted", MatchAbortedBody>
  | Envelope<"ping", { nonce: string }>
  | Envelope<"error", ErrorBody>;

const KNOWN_TYPES = new Set([
  "welcome",
  "spectator_welcome",
  "match_state",
  "observation_request",
  "action_rejected",
  "turn_committed",
  "match_finished",
  "match_aborted",
  "ping",
  "error",
]);

/** Parse a frame; `null` for a type this client does not know (section 7: ignore it). */
export function parseMessage(text: string): ServerMessage | null {
  const value = JSON.parse(text) as { type?: unknown };
  if (typeof value !== "object" || value === null || typeof value.type !== "string") {
    throw new ProtocolError("A frame must be a JSON object with a string `type`.");
  }
  return KNOWN_TYPES.has(value.type) ? (value as ServerMessage) : null;
}

/** The connection closed; `code` is the WebSocket close code (section 9). */
export class ConnectionClosedError extends Error {
  readonly code: number;
  readonly reason: string;

  constructor(code: number, reason: string) {
    super(`connection closed ${code}${reason ? ` (${reason})` : ""}`);
    this.name = "ConnectionClosedError";
    this.code = code;
    this.reason = reason;
  }
}

/** The server broke the protocol (an unparseable frame, a missing welcome). */
export class ProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtocolError";
  }
}

/** The match ended in an abort; carries the abort and the final transcript. */
export class MatchAbortedError extends Error {
  readonly abort: AbortInfo;
  readonly transcript: RuntimeTranscript;

  constructor(body: MatchAbortedBody) {
    super(`match aborted: ${body.abort.reason} (${body.abort.message})`);
    this.name = "MatchAbortedError";
    this.abort = body.abort;
    this.transcript = body.transcript;
  }
}
