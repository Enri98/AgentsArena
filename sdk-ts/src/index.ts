/**
 * @agents-arena/sdk: a TypeScript client for the AgentsArena WebSocket protocol.
 *
 * The protocol (docs/NETWORK_PROTOCOL.md in the repository) is the source of
 * truth; this is a reference client for it, as the Python `arena.sdk` is.
 */

export { Connection } from "./connection.ts";
export {
  CLIENT_NAME,
  CLIENT_VERSION,
  ConnectionClosedError,
  MatchAbortedError,
  ProtocolError,
  SUPPORTED_SCHEMA_VERSIONS,
  WIRE_SCHEMA_VERSION,
  parseMessage,
} from "./protocol.ts";
export type * from "./protocol.ts";
export {
  type ChooseAction,
  type ConnectOptions,
  type MatchOutcome,
  SeatSession,
  playMatch,
} from "./seat.ts";
export { type SpectateOptions, type SpectatorEvent, spectate } from "./spectator.ts";
export {
  ArenaHttpError,
  createMatch,
  type CreateMatchOptions,
  type CreatedMatch,
  fetchPublicTranscript,
} from "./http.ts";
