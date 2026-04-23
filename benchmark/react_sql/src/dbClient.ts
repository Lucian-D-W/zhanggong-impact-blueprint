export function refreshDashboard(userId: string) {
  const sql = `select app_refresh_dashboard('${userId}')`;
  return sql;
}
