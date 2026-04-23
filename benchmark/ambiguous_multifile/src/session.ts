export function openSession(userId: string) {
  return `session:${userId}`;
}

export function auditSession(userId: string) {
  return `audit:${userId}`;
}
