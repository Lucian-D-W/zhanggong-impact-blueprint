import test from "node:test";
import assert from "node:assert/strict";
import { login } from "../src/auth.ts";

test("login opens a session", () => {
  assert.equal(login("demo"), "session:demo");
});
