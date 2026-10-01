// Both existing hubs are served by this origin. Roles remain server-authorized.
export const HUB_ORIGIN = "https://drop-rate-api-live-production.up.railway.app";
export const HUB_ENTRY = `${HUB_ORIGIN}/owner`;
export function isHubUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.origin === HUB_ORIGIN && !url.username && !url.password;
  } catch {
    return false;
  }
}
export function isExternalHttps(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}
