import assert from "node:assert/strict";
import { test } from "node:test";

import { ProtocolError, WIRE_SCHEMA_VERSION, parseMessage } from "../src/index.ts";

test("the client speaks wire schema_version 4", () => {
  assert.equal(WIRE_SCHEMA_VERSION, 4);
});

test("known messages parse, unknown types are ignored (section 7)", () => {
  const ping = parseMessage('{"type":"ping","schema_version":4,"payload":{"nonce":"n"}}');
  assert.equal(ping?.type, "ping");
  assert.equal(parseMessage('{"type":"from_the_future","schema_version":9,"payload":{}}'), null);
});

test("a frame that is not an object with a type is a protocol error", () => {
  assert.throws(() => parseMessage("[1,2,3]"), ProtocolError);
  assert.throws(() => parseMessage('{"payload":{}}'), ProtocolError);
});
