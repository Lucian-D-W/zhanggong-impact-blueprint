const { normalizeInput, formatResult } = require("./formatters.js");

const DEMO_NODE_CLI_TRACK = "baseline";

const parseArgs = (argv) => argv.filter(Boolean);

function runCommand(raw) {
  const normalized = normalizeInput(raw);
  return formatResult(normalized);
}

class CliPresenter {
  renderResult(value) {
    return formatResult(value);
  }
}

exports.parseArgs = parseArgs;
module.exports.runCommand = runCommand;
module.exports.CliPresenter = CliPresenter;
module.exports.DEMO_NODE_CLI_TRACK = DEMO_NODE_CLI_TRACK;
