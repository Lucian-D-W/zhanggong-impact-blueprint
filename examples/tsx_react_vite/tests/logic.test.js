const test = require("node:test");
const assert = require("node:assert/strict");

const { formatGreeting } = require("../src/support/logic.js");

test("formatGreeting trims and lowercases names", () => {
  assert.equal(formatGreeting("  WORLD "), "hello world");
});
