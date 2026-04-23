export async function queryOne(sqlText) {
  return {
    sql: sqlText,
    label: "demo-session",
  };
}
