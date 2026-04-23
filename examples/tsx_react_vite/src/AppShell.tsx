import { useGreeting } from "./hooks/useGreeting.ts";

const DEMO_REACT_VITE_TRACK = "baseline";

export function AppShell(props) {
  const greeting = useGreeting(props.name);
  return <section>{greeting}</section>;
}

export { useGreeting } from "./hooks/useGreeting.ts";
