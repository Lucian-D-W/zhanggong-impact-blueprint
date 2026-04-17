const test = require("node:test");
const assert = require("node:assert/strict");

const { runCommand, parseArgs, CliPresenter } = require("../src/cli.js");

test("runCommand formats normalized input", () => {
  assert.equal(runCommand("  Ping  "), "cmd:ping");
  assert.deepEqual(parseArgs(["", "ping", "--help"]), ["ping", "--help"]);

  const presenter = new CliPresenter();
  assert.equal(presenter.renderResult("ready"), "cmd:ready");
});
