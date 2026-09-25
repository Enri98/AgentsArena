# @agents-arena/sdk

A TypeScript client for the AgentsArena WebSocket protocol, **wire `schema_version` 4**.

The protocol (`docs/NETWORK_PROTOCOL.md` in the repository) is the source of truth. This
package is a reference client for it, as the Python `arena.sdk` is. It has no runtime
dependencies: it uses the standard `WebSocket` and `fetch`, built into Node 22+ and every
browser.

## Play a seat

```ts
import { createMatch, playMatch } from "@agents-arena/sdk";

const match = await createMatch("http://127.0.0.1:8080", "tictactoe");

// Each seat answers its observation requests. `choose` may be async (an LLM
// call): pings are answered in the background while it thinks.
const firstLegal = (request) => request.observation.legal_actions[0];
const [seat0, seat1] = await Promise.all([
  playMatch(match.seat_0_url, 0, firstLegal),
  playMatch(match.seat_1_url, 1, firstLegal),
]);
console.log(seat0.transcript.lifecycle); // "finished"
```

`playMatch` chooses again after an `action_rejected` while retries remain, and rejects with
`MatchAbortedError` (carrying the abort and the transcript) if the match aborts. For full
control use `SeatSession`: `connect`, `recv`, `sendAction`, `close`, and `resumeToken` to
resume a dropped seat.

## Watch a match

```ts
import { spectate } from "@agents-arena/sdk";

const transcript = await spectate(`ws://127.0.0.1:8080/matches/${id}/spectate`, {
  onWelcome: (welcome) => console.log("history so far:", welcome.transcript),
  onEvent: (event) => {
    if (event.type === "turn_committed") console.log(event.payload.turn_record);
  },
});
```

A spectator gets the public view. For a hidden-information game (Liar's Dice) that means no
hand before a showdown. Ended matches' public transcripts stay available over HTTP:
`fetchPublicTranscript(httpBase, matchId)`.

## Turns

A `TurnRecord` has a `kind`:
- `"action"`: one seat acted (`seat`, `action`);
- `"chance"`: a random outcome resolved (`outcome`), with no seat;
- `"joint"`: a simultaneous round (v4), where `actions` maps each acting seat (`"0"`, `"1"`)
  to its action.

## Development

```sh
npm install
npm run typecheck
npm test                                  # unit tests (node --test)
node examples/play_match.ts http://127.0.0.1:8080 rps   # against a running server
```

Node 22.18+ (or 23.6+) runs the TypeScript sources directly. `npm run build` emits `dist/`
for publishing. The repository's pytest suite (`tests/integration/test_typescript_sdk.py`)
plays the SDK against the Python server.
