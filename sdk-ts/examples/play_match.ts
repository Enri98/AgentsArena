/**
 * Play one match with the TypeScript SDK: create it over HTTP, play both seats,
 * and watch it as a spectator. Prints a JSON summary.
 *
 *   node examples/play_match.ts http://127.0.0.1:8080 tictactoe [first|last]
 *
 * Each seat plays the first (or last) legal action it is offered; a spectator
 * renders every committed turn as one line. ("last" suits Pig: roll, then hold.)
 */

import {
  type JsonObject,
  type ObservationRequest,
  type SpectatorEvent,
  createMatch,
  fetchPublicTranscript,
  playMatch,
  spectate,
} from "../src/index.ts";

const [httpBase = "http://127.0.0.1:8080", gameId = "tictactoe", pick = "first"] =
  process.argv.slice(2);
const wsBase = httpBase.replace(/^http/, "ws");

function firstLegal(request: ObservationRequest): JsonObject {
  const legal = request.observation.legal_actions as JsonObject[];
  return pick === "last" ? legal[legal.length - 1] : legal[0];
}

function renderTurn(event: SpectatorEvent): string | null {
  if (event.type !== "turn_committed") return null;
  const turn = event.payload.turn_record;
  if (turn.kind === "chance") return `#${turn.turn_index} chance ${JSON.stringify(turn.outcome)}`;
  if (turn.kind === "joint") {
    const parts = Object.entries(turn.actions ?? {}).map(([seat, a]) => `${seat}:${JSON.stringify(a)}`);
    return `#${turn.turn_index} round ${parts.join(" vs ")}`;
  }
  return `#${turn.turn_index} seat ${turn.seat} ${JSON.stringify(turn.action)}`;
}

const match = await createMatch(httpBase, gameId, { perTurnDeadlineMs: 10_000 });
const rendered: string[] = [];
const watching = spectate(`${wsBase}/matches/${match.match_id}/spectate`, {
  onEvent: (event) => {
    const line = renderTurn(event);
    if (line) rendered.push(line);
  },
});
watching.catch(() => {}); // awaited below; if a seat fails first, not an unhandled rejection
const [seat0, seat1] = await Promise.all([
  playMatch(match.seat_0_url, 0, firstLegal),
  playMatch(match.seat_1_url, 1, firstLegal),
]);
const spectated = await watching;
const stored = await fetchPublicTranscript(httpBase, match.match_id);

console.log(
  JSON.stringify({
    match_id: match.match_id,
    lifecycle: [seat0.transcript.lifecycle, seat1.transcript.lifecycle],
    turns: seat0.transcript.match_transcript?.turns.length ?? 0,
    spectator_lifecycle: spectated.lifecycle,
    spectator_lines: rendered,
    public_transcript_turns: stored?.match_transcript?.turns.length ?? null,
  }),
);
