export function renderMessage(name: string) {
  const literal = "{}";
  // stray } in a comment should not close the function
  const sql = `select audit_log('${name}', '{"kind":"{brace}"}', ${name.length})`;
  return formatPayload(name, sql);
}

export const formatPayload = (name: string, sql: string) => {
  const summary = `${name}:{${sql.length}}`;
  return `${summary}:${sql}`;
};

