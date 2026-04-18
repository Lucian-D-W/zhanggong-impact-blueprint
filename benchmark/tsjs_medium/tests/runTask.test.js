import test from "node:test";
import assert from "node:assert/strict";
import { runTask } from "../src/commands/runTask.ts";

test("runTask returns a stable formatted task", () => {
  assert.equal(runTask(["demo"]), "task:demo:quiet");
});
