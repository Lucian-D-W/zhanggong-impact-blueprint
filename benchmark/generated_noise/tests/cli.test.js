import test from "node:test";
import assert from "node:assert/strict";
import { renderLabel } from "../src/cli.ts";

test("renderLabel stays stable", () => {
  assert.equal(renderLabel("demo"), "label:demo");
});
