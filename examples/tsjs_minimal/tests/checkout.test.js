const test = require("node:test");
const assert = require("node:assert/strict");

const { totalWithFee } = require("../src/checkout.js");

test("totalWithFee adds fee and clamps positive", () => {
  assert.equal(totalWithFee(10, 2), 12);
  assert.equal(totalWithFee(-5, 1), 0);
});
