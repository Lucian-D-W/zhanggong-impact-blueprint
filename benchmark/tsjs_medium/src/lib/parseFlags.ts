export function parseFlags(argv: string[]) {
  return {
    name: argv[0] || "demo",
    verbose: argv.includes("--verbose"),
  };
}
