import { useDashboard } from "../hooks/useDashboard.ts";
import { refreshDashboard } from "../dbClient.ts";

export const Dashboard = ({ userId }: { userId: string }) => {
  const label = useDashboard(userId);
  const sql = refreshDashboard(userId);
  return <section data-sql={sql}>{label}</section>;
};
