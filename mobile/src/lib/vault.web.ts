import type { Vault } from "./api";
// Browser previews intentionally keep credentials out of localStorage/sessionStorage.
const values = new Map<string, string>();
export const vault: Vault = {
  get: async (key) => values.get(key) ?? null,
  set: async (key, value) => {
    values.set(key, value);
  },
  remove: async (key) => {
    values.delete(key);
  },
};
