import { openSession } from "./session.ts";

export function login(userId: string) {
  return openSession(userId);
}

export const logout = (userId: string) => {
  return `logout:${userId}`;
};
