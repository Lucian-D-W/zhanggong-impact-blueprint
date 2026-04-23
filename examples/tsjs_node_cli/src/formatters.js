function normalizeInput(raw) {
  return raw.trim().toLowerCase();
}

function formatResult(raw) {
  return `cmd:${raw}`;
}

module.exports = {
  normalizeInput,
  formatResult,
};
