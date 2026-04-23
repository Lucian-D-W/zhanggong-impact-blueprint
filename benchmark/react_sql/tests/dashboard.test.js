import test from "node:test";
import assert from "node:assert/strict";
import { refreshDashboard } from "../src/dbClient.ts";

test("refreshDashboard emits the expected SQL call", () => {
  assert.match(refreshDashboard("demo"), /app_refresh_dashboard/);
});
