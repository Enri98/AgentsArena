# Browser spectator

A single static page that watches a live match over `WS /matches/{id}/spectate`.

It is deliberately **not** an SDK: about 120 lines of plain browser `WebSocket`
glue, no build step, no dependencies. Phase 42 may add a packaged TypeScript
client once the wire settles; this is what proves the spectator channel works
from a browser today.

## Run it

1. Start a server:

   ```
   .\.venv\Scripts\python.exe -m arena.server --host 127.0.0.1 --port 8080
   ```

2. Create a match and note the `match_id`:

   ```
   curl -X POST http://127.0.0.1:8080/matches ^
     -H "Content-Type: application/json" ^
     -d "{\"game_id\": \"connect4\", \"players\": [{\"label\": \"alice\"}, {\"label\": \"bob\"}]}"
   ```

3. Open `index.html` in a browser, paste the `match_id`, and press **Watch**.
   You can attach before the seats do — the page will sit on `created` until the
   match starts.

4. Start the two agents, for example:

   ```
   .\.venv\Scripts\python.exe examples\run_remote_demo.py --server-url ws://127.0.0.1:8080
   ```

A spectator that attaches mid-match gets the history first (it rides in
`spectator_welcome.transcript`), then live turns.

## What it renders

- **Connect 4 / Tic-Tac-Toe** — the `board` grid from the snapshot's state
- **Nim** — the `piles` array
- anything else — the raw state as JSON, so a new game is still watchable before
  it has a renderer

## Notes

- Opening the file over `file://` is fine; the page only needs to reach the
  server's WebSocket endpoint.
- Against a deployed server use `wss://your-app.fly.dev` as the base URL.
- The page never sends an action. The server refuses one from a spectator with
  `protocol_violation` and closes the connection.
