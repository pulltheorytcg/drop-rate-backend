import type { Access, Session, PendingIntake, IntakeResult } from "./types";
export interface Vault {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
const SESSION_KEY = "pulltheory.session.v1";
export const DEFAULT_BASE =
  "https://drop-rate-api-live-production.up.railway.app";
export function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
function parseSession(value: Session & { expires_in?: number }): Session {
  if (!value?.access_token || !value.refresh_token || !value.user?.id)
    throw new Error("The sign-in response was incomplete.");
  return {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    expires_at: value.expires_at ?? Date.now() / 1000 + (value.expires_in ?? 0),
    user: { id: value.user.id },
  };
}
export function assertAccess(access: Access): Access {
  if (
    !access?.user_id ||
    !access.owner_id ||
    !["OWNER", "PLATFORM_ADMIN"].includes(access.access_role) ||
    access.portal !==
      (access.access_role === "OWNER" ? "OWNER_PORTAL" : "FOUNDER_HQ")
  )
    throw new Error(
      "This account does not have mobile access. Contact your administrator.",
    );
  return access;
}
export class Api {
  private session: Session | null = null;
  access: Access | null = null;
  private epoch = 0;
  private refreshing: Promise<string> | null = null;
  private vaultWrites: Promise<void> = Promise.resolve();
  private config: { supabase_url: string; publishable_key: string } | null =
    null;
  private expiredListeners = new Set<() => void>();
  subscribeExpired(listener: () => void) {
    this.expiredListeners.add(listener);
    return () => {
      this.expiredListeners.delete(listener);
    };
  }
  constructor(
    readonly vault: Vault,
    readonly base = DEFAULT_BASE,
    private transport: typeof fetch = fetch,
  ) {
    const url = new URL(base);
    if (
      url.protocol !== "https:" &&
      !["localhost", "127.0.0.1"].includes(url.hostname)
    )
      throw new Error("The app requires a secure server connection.");
  }
  private check(epoch: number) {
    if (epoch !== this.epoch)
      throw new ApiError(401, "Your session changed. Please sign in again.");
  }
  private store(session: Session | null, epoch: number) {
    const operation = this.vaultWrites
      .catch(() => {})
      .then(async () => {
        this.check(epoch);
        if (session) await this.vault.set(SESSION_KEY, JSON.stringify(session));
        else await this.vault.remove(SESSION_KEY);
        this.check(epoch);
        this.session = session;
      });
    this.vaultWrites = operation;
    return operation;
  }
  private async send<T>(
    url: string,
    method = "GET",
    body?: unknown,
    headers: Record<string, string> = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await this.transport(url, {
        method,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...headers,
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: controller.signal,
        redirect: "error",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        let message =
          typeof detail === "string"
            ? detail
            : detail?.message ||
              data.error_description ||
              data.msg ||
              `Request failed (${response.status}). Please try again.`;
        if (detail?.missing) message += ": " + detail.missing.join(", ");
        if (response.status === 409)
          message += " Refresh the item before trying again.";
        throw new ApiError(response.status, message);
      }
      return data as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new Error(
        "Connection interrupted. Check your connection and try again. Any pending save will use the same request.",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  private async configuration() {
    if (!this.config) {
      const config = await this.send<{
        supabase_url: string;
        publishable_key: string;
      }>(this.base + "/api/v1/public-config");
      const url = new URL(config.supabase_url);
      if (
        url.protocol !== "https:" ||
        !url.hostname.endsWith(".supabase.co") ||
        !config.publishable_key
      )
        throw new Error(
          "The authentication configuration could not be verified.",
        );
      this.config = config;
    }
    return this.config;
  }
  async restore(): Promise<Access | null> {
    const epoch = this.epoch;
    const raw = await this.vault.get(SESSION_KEY);
    this.check(epoch);
    if (!raw) return null;
    try {
      this.session = parseSession(JSON.parse(raw));
    } catch {
      await this.store(null, epoch);
      return null;
    }
    return this.loadAccess();
  }
  async login(identifier: string, password: string): Promise<Access> {
    const epoch = ++this.epoch;
    const value = parseSession(
      await this.send<Session>(
        this.base + "/api/v1/public/owner-session",
        "POST",
        { identifier: identifier.trim(), password },
      ),
    );
    this.check(epoch);
    await this.store(value, epoch);
    try {
      return await this.loadAccess();
    } catch (error) {
      if (epoch === this.epoch) await this.logout();
      throw error;
    }
  }
  async loadAccess() {
    const { access } = await this.request<{ access: Access }>(
      "/api/v1/access/me",
    );
    assertAccess(access);
    if (access.user_id !== this.session?.user.id)
      throw new ApiError(403, "The account could not be verified.");
    this.access = access;
    return access;
  }
  private async token(force = false): Promise<string> {
    const session = this.session;
    const epoch = this.epoch;
    if (!session) throw new ApiError(401, "Please sign in again.");
    if (!force && session.expires_at > Date.now() / 1000 + 60)
      return session.access_token;
    if (this.refreshing) return this.refreshing;
    const task = (async () => {
      try {
        const config = await this.configuration();
        this.check(epoch);
        const value = parseSession(
          await this.send<Session>(
            config.supabase_url + "/auth/v1/token?grant_type=refresh_token",
            "POST",
            { refresh_token: session.refresh_token },
            { apikey: config.publishable_key },
          ),
        );
        this.check(epoch);
        if (value.user.id !== session.user.id)
          throw new ApiError(401, "Session account changed.");
        await this.store(value, epoch);
        return value.access_token;
      } catch (error) {
        if (
          epoch === this.epoch &&
          error instanceof ApiError &&
          [400, 401, 403].includes(error.status)
        ) {
          this.access = null;
          this.session = null;
          await this.store(null, epoch);
          this.expiredListeners.forEach((listener) => listener());
        }
        throw error;
      }
    })();
    this.refreshing = task;
    try {
      return await task;
    } finally {
      if (this.refreshing === task) this.refreshing = null;
    }
  }
  async request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    key?: string,
  ): Promise<T> {
    if (!path.startsWith("/api/v1/") || path.includes(".."))
      throw new Error("Invalid API path.");
    const epoch = this.epoch;
    const token = await this.token();
    this.check(epoch);
    const headers = {
      Authorization: "Bearer " + token,
      ...(key ? { "Idempotency-Key": key } : {}),
    };
    try {
      const result = await this.send<T>(
        this.base + path,
        method,
        body,
        headers,
      );
      this.check(epoch);
      return result;
    } catch (error) {
      this.check(epoch);
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      headers.Authorization =
        "Bearer " +
        (this.session?.access_token !== token
          ? await this.token()
          : await this.token(true));
      this.check(epoch);
      const result = await this.send<T>(
        this.base + path,
        method,
        body,
        headers,
      );
      this.check(epoch);
      return result;
    }
  }
  async logout() {
    const previous = this.session;
    const epoch = ++this.epoch;
    this.session = null;
    this.access = null;
    this.refreshing = null;
    await this.store(null, epoch);
    if (previous) {
      // Revoke only this session; tokens are never passed in a browser URL.
      try {
        const c = await this.configuration();
        await this.send(
          c.supabase_url + "/auth/v1/logout?scope=local",
          "POST",
          undefined,
          {
            apikey: c.publishable_key,
            Authorization: "Bearer " + previous.access_token,
          },
        );
      } catch {
        /* Local sign-out remains effective when offline. */
      }
    }
  }
  private pendingKey() {
    if (!this.access) throw new ApiError(401, "Please sign in again.");
    return "pulltheory.intake." + this.access.user_id;
  }
  async pending(): Promise<PendingIntake | null> {
    const epoch = this.epoch;
    const access = this.access;
    const key = this.pendingKey();
    const raw = await this.vault.get(key);
    this.check(epoch);
    if (!raw) return null;
    const pending = JSON.parse(raw) as PendingIntake;
    if (
      !access ||
      this.access?.user_id !== access.user_id ||
      this.access?.owner_id !== access.owner_id ||
      this.access?.access_role !== access.access_role ||
      pending.userId !== access.user_id ||
      pending.ownerId !== access.owner_id ||
      pending.role !== access.access_role
    )
      throw new Error(
        "A previous save belongs to a different access context. Contact support to reconcile it.",
      );
    return pending;
  }
  private queueing = false;
  async queueIntake(
    payload: Record<string, unknown>,
    key: string,
    title: string,
  ) {
    if (this.queueing) throw new Error("A save is already in progress.");
    this.queueing = true;
    const epoch = this.epoch;
    try {
      const access = this.access;
      if (!access) throw new ApiError(401, "Please sign in again.");
      const storageKey = this.pendingKey();
      if (await this.pending())
        throw new Error(
          "Finish the previous pending save before starting another.",
        );
      this.check(epoch);
      const pending: PendingIntake = {
        key,
        userId: access.user_id,
        ownerId: access.owner_id,
        role: access.access_role,
        path:
          access.access_role === "OWNER"
            ? "/api/v1/owner/recognition-intake"
            : "/api/v1/inventory/intake",
        payload: JSON.parse(JSON.stringify(payload)),
        title,
      };
      await this.vault.set(storageKey, JSON.stringify(pending));
      this.check(epoch);
      return await this.resumeIntake();
    } finally {
      this.queueing = false;
    }
  }

  private saving: { epoch: number; operation: Promise<IntakeResult> } | null =
    null;
  async resumeIntake(): Promise<IntakeResult> {
    if (this.saving?.epoch === this.epoch) return this.saving.operation;
    const epoch = this.epoch;
    const operation = (async () => {
      const key = this.pendingKey();
      const pending = await this.pending();
      this.check(epoch);
      if (!pending) throw new Error("No pending save was found.");
      const expectedPath =
        pending.role === "OWNER"
          ? "/api/v1/owner/recognition-intake"
          : "/api/v1/inventory/intake";
      if (pending.path !== expectedPath)
        throw new Error("The pending save could not be verified.");
      try {
        const result = await this.request<IntakeResult>(
          pending.path,
          "POST",
          pending.payload,
          pending.key,
        );
        await this.vault.remove(key);
        this.check(epoch);
        return result;
      } catch (error) {
        this.check(epoch);
        // Explicit pre-write validation/permission rejections can be corrected. Keep
        // timeouts, conflicts and server errors immutable until replay/reconciliation.
        if (
          error instanceof ApiError &&
          [400, 403, 404, 422].includes(error.status)
        )
          await this.vault.remove(key);
        throw error;
      }
    })();
    const saving = { epoch, operation };
    this.saving = saving;
    try {
      return await operation;
    } finally {
      if (this.saving === saving) this.saving = null;
    }
  }
}
