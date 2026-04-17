const DEMO_TSJS_TRACK = "baseline";

function add(left, right) {
  return left + right;
}

function clampPositive(value) {
  return Math.max(0, value);
}

module.exports = {
  DEMO_TSJS_TRACK,
  add,
  clampPositive,
};
