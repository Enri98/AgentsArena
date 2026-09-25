/**
 * Watching a match (docs/NETWORK_PROTOCOL.md section 8.13): the public view,
 * live. A spectator holds no seat and is never sent an observation request.
 */

import { Connection } from "./connection.ts";
import {
  CLIENT_NAME,
  CLIENT_VERSION,
  MatchAbortedError,
  ProtocolError,
  type RuntimeTranscript,
  SUPPORTED_SCHEMA_VERSIONS,
  type ServerMessage,
  type SpectatorWelcomeBody,
  WIRE_SCHEMA_VERSION,
} from "./protocol.ts";

export type SpectatorEvent = Exclude<ServerMessage, { type: "spectator_welcome" | "ping" }>;

export interface SpectateOptions {
  /** Called once with the welcome, which carries the history so far. */
  onWelcome?: (welcome: SpectatorWelcomeBody) => void;
  /** Called for each live message, in order. */
  onEvent?: (event: SpectatorEvent) => void;
}

/**
 * Watch a match (`.../matches/{id}/spectate`) until it ends. Resolves with the
 * public transcript of a finished match; rejects with `MatchAbortedError` for
 * an aborted one.
 */
export async function spectate(url: string, options: SpectateOptions = {}): Promise<RuntimeTranscript> {
  const connection = await Connection.open(url);
  try {
    connection.send({
      type: "spectator_hello",
      schema_version: WIRE_SCHEMA_VERSION,
      payload: {
        client_name: CLIENT_NAME,
        client_version: CLIENT_VERSION,
        supported_schema_versions: [...SUPPORTED_SCHEMA_VERSIONS],
      },
    });
    const first = await connection.next(10_000);
    if (first.type !== "spectator_welcome") {
      throw new ProtocolError(`expected spectator_welcome, got ${first.type}`);
    }
    options.onWelcome?.(first.payload);
    // A match already over is fully described by the welcome's transcript.
    if (first.payload.lifecycle === "finished" && first.payload.transcript) {
      return first.payload.transcript;
    }
    for (;;) {
      const message = (await connection.next()) as SpectatorEvent;
      options.onEvent?.(message);
      if (message.type === "match_finished") return message.payload.transcript;
      if (message.type === "match_aborted") throw new MatchAbortedError(message.payload);
    }
  } finally {
    connection.close();
  }
}
