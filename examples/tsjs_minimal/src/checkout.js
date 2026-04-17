const { add, clampPositive } = require("./math.js");

function totalWithFee(amount, fee) {
  return clampPositive(add(amount, fee));
}

module.exports = {
  totalWithFee,
};
