import test from "node:test";
import assert from "node:assert/strict";

import { fetchSessionLabel } from "../src/sessionQueries.js";

test("fetchSessionLabel returns a stable label", async () => {
  const label = await fetchSessionLabel("Demo User");
  assert.match(label, /^(baseline|edited):demo-session$/);
});
