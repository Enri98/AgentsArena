# Security

## Reporting a vulnerability

Please report security problems privately, through GitHub's private vulnerability reporting
("Report a vulnerability" on the repository's Security tab), rather than in a public issue.
Include what an attacker can do, the steps to reproduce, and the version or commit.

## What the server does and does not protect

AgentsArena has **no authentication or accounts** yet. Know the model before exposing a
server:

- **A `match_id` is the capability.** It is an unguessable token (`secrets.token_urlsafe(16)`,
  128 bits). Anyone holding it can spectate the match, and read its public transcript once
  it ends. Share it only with the players and viewers you intend.
- **A seat is bound to its resume token.** Once a match runs, a seat can be taken over only
  with the token from that seat's `welcome`; a token-less `hello` is refused (4409).
- **Hidden information stays hidden.** Every frame, snapshot, event, chance outcome and
  transcript is built for its recipient; spectators see the public view only. Random seeds
  never appear in config, state or transcripts.
- **Abuse is bounded, not prevented.** Protocol §13 rate limits cap connections per IP,
  spectators per match, WebSocket opens and transcript reads per minute; bodies, frames and
  labels have size limits. Behind a proxy, set `ARENA_CLIENT_IP_HEADER` to the one header
  your proxy sets, or every client shares the proxy's address.
- **The MCP HTTP/SSE transport is unauthenticated.** Bind it to localhost or put it behind
  something that authenticates.

`docs/DEPLOYMENT.md` covers running a public server; `docs/NETWORK_PROTOCOL.md` §9 and §13
describe the close codes and limits.

## Supported versions

Only the latest release receives fixes.
