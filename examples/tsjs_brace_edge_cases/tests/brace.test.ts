import test from "node:test";
import assert from "node:assert/strict";

import { renderMessage } from "../src/brace.ts";

test("renderMessage returns a stable formatted string", () => {
  assert.match(renderMessage("demo"), /^demo/);
  assert.match(renderMessage("demo"), /audit_log/);
});

