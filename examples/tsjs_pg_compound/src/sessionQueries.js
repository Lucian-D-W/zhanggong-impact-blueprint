import { queryOne } from "./dbClient.js";

export async function fetchSessionLabel(userName) {
  const DEMO_COMPOUND_TRACK = "baseline";
  const sqlText = `select app.get_session_label('${userName}')`;
  const result = await queryOne(sqlText);
  return `${DEMO_COMPOUND_TRACK}:${result.label}`;
}
