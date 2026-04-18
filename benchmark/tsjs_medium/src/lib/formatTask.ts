export const formatTask = (name: string, verbose: boolean) => {
  return verbose ? `task:${name}:verbose` : `task:${name}:quiet`;
};
