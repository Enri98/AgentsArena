/**
 * Edge cases against a running server; prints a JSON summary. Run by the
 * repository's pytest suite (tests/integration/test_typescript_sdk.py):
 *
 *   node test/live/edge_cases.ts http://127.0.0.1:8080
 */

import {
  ConnectionClosedError,
  type JsonObject,
  MatchAbortedError,
  type ObservationRequest,
  SeatSession,
  createMatch,
  playMatch,
  spectate,
} from "../../src/index.ts";

const [httpBase = "http://127.0.0.1:8080"] = process.argv.slice(2);
const wsBase = httpBase.replace(/^http/, "ws");
const summary: Record<string, unknown> = {};

function describe(error: unknown): string {
  if (error instanceof MatchAbortedError) return `aborted:${error.abort.reason}`;
  if (error instanceof ConnectionClosedError) return `closed:${error.code}`;
  return `other:${String(error)}`;
}

const firstLegal = (request: ObservationRequest): JsonObject =>
  (request.observation.legal_actions as JsonObject[])[0];

// 1. A refused connection reports the protocol's close code, not 1006.
const unknown = `${wsBase}/matches/no-such-match/play?seat=0`;
summary.unknown_match = await SeatSession.connect(unknown, 0).then(
  () => "connected",
  describe,
);

// 2. A deadline expiring while `choose` thinks: both seats see the abort.
const match = await createMatch(httpBase, "tictactoe", { perTurnDeadlineMs: 400 });
const slow = async (request: ObservationRequest): Promise<JsonObject> => {
  await new Promise((resolve) => setTimeout(resolve, 1200));
  return firstLegal(request);
};
summary.deadline = await Promise.all([
  playMatch(match.seat_0_url, 0, slow).then(() => "finished", describe),
  playMatch(match.seat_1_url, 1, firstLegal).then(() => "finished", describe),
]);

// 3. Watching a match that already aborted.
summary.spectate_aborted = await spectate(`${wsBase}/matches/${match.match_id}/spectate`).then(
  () => "finished",
  describe,
);

// 4. Nothing left running: no timer keeps the process alive after the work.
summary.pending_timers = process
  .getActiveResourcesInfo()
  .filter((resource) => resource === "Timeout").length;

console.log(JSON.stringify(summary));
