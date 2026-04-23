import { parseFlags } from "../lib/parseFlags.ts";
import { formatTask } from "../lib/formatTask.ts";

export function runTask(argv: string[]) {
  const flags = parseFlags(argv);
  return formatTask(flags.name, flags.verbose);
}
