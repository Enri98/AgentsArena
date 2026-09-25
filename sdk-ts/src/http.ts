/** The HTTP side of the protocol (section 4): creating matches, fetching transcripts. */

import { type JsonObject, type RuntimeTranscript, WIRE_SCHEMA_VERSION } from "./protocol.ts";

export interface CreateMatchOptions {
  gameConfig?: JsonObject;
  players?: { label?: string }[];
  perTurnDeadlineMs?: number;
  perActionRetryBudget?: number;
  disconnectGraceMs?: number;
}

export interface CreatedMatch {
  match_id: string;
  game_id: string;
  schema_version: number;
  lifecycle: string;
  seat_0_url: string;
  seat_1_url: string;
  per_turn_deadline_ms: number;
  per_action_retry_budget: number;
  disconnect_grace_ms: number;
}

/** `POST /matches`. Throws with the server's error code on a non-201 answer. */
export async function createMatch(
  httpBase: string,
  gameId: string,
  options: CreateMatchOptions = {},
): Promise<CreatedMatch> {
  const body: JsonObject = {
    game_id: gameId,
    supported_schema_versions: [WIRE_SCHEMA_VERSION],
  };
  if (options.gameConfig) body.game_config = options.gameConfig;
  if (options.players) body.players = options.players as JsonObject[];
  if (options.perTurnDeadlineMs !== undefined) body.per_turn_deadline_ms = options.perTurnDeadlineMs;
  if (options.perActionRetryBudget !== undefined) {
    body.per_action_retry_budget = options.perActionRetryBudget;
  }
  if (options.disconnectGraceMs !== undefined) body.disconnect_grace_ms = options.disconnectGraceMs;
  const response = await fetch(`${httpBase.replace(/\/+$/, "")}/matches`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as JsonObject;
  if (response.status !== 201) {
    const error = payload.error as { code?: string; message?: string } | undefined;
    throw new Error(`create match failed: ${response.status} ${error?.code}: ${error?.message}`);
  }
  return payload as unknown as CreatedMatch;
}

/**
 * `GET /matches/{id}/public-transcript` (Phase 40). Resolves `null` for 404
 * (unknown or expired) and 409 (not ended yet).
 */
export async function fetchPublicTranscript(
  httpBase: string,
  matchId: string,
): Promise<RuntimeTranscript | null> {
  const response = await fetch(
    `${httpBase.replace(/\/+$/, "")}/matches/${encodeURIComponent(matchId)}/public-transcript`,
  );
  if (response.status === 404 || response.status === 409) return null;
  if (!response.ok) throw new Error(`public transcript: HTTP ${response.status}`);
  return (await response.json()) as RuntimeTranscript;
}
