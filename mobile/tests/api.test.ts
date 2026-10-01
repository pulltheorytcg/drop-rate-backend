import { describe, it, expect, vi } from "vitest";
import { Api, ApiError, assertAccess, type Vault } from "../src/lib/api";
import {
  inventoryPath,
  cataloguePath,
  intakePayload,
  selectCandidate,
} from "../src/lib/workflows";
import {
  minorUnits,
  money,
  type Access,
  type Recognition,
  type Selection,
} from "../src/lib/types";
const access: Access = {
  user_id: "user-a",
  owner_id: "owner-a",
  access_role: "OWNER",
  portal: "OWNER_PORTAL",
  display_name: "Alex",
};
const admin: Access = {
  ...access,
  access_role: "PLATFORM_ADMIN",
  portal: "FOUNDER_HQ",
};
const session = {
  access_token: "token",
  refresh_token: "refresh",
  expires_at: Date.now() / 1000 + 3600,
  user: { id: "user-a" },
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function memory() {
  const data = new Map<string, string>();
  const vault: Vault = {
    get: async (key) => data.get(key) ?? null,
    set: async (k, v) => {
      data.set(k, v);
    },
    remove: async (key) => {
      data.delete(key);
    },
  };
  return { data, vault };
}
function setup(
  handler?: (path: string, init?: RequestInit) => Response | Promise<Response>,
  vault = memory().vault,
) {
  const transport = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("owner-session")) return response(session);
      if (path.endsWith("/access/me")) return response({ access });
      if (path.endsWith("public-config"))
        return response({
          supabase_url: "https://test.supabase.co",
          publishable_key: "public",
        });
      if (path.endsWith("/logout")) return response({});
      return handler ? handler(path, init) : response({ ok: true });
    },
  );
  return {
    api: new Api(vault, "https://test.invalid", transport),
    transport,
    vault,
  };
}
const result: Recognition = {
  run: { id: "run-a", status: "NEEDS_REVIEW", top_catalogue_id: "card-a" },
  candidates: [],
};
const selected: Selection = {
  catalogueId: "card-a",
  card: {
    id: "card-a",
    name: "Test card",
    product_type: "CARD",
    language: "Japanese",
  },
  outcome: "CONFIRMED_TOP",
};
describe("backend contracts", () => {
  it("uses distinct endpoints and never infers role from metadata", () => {
    expect(inventoryPath(access)).toBe("/api/v1/owner/inventory");
    expect(inventoryPath(admin)).toBe("/api/v1/inventory");
    expect(() =>
      assertAccess({ ...access, access_role: "PLATFORM_ADMIN" }),
    ).toThrow();
  });
  it("includes run-scoped references for sellers, keeps admin searches out of owner APIs", () => {
    expect(cataloguePath(access, "OP05-069", result)).toContain(
      "include_reference=true&run_id=run-a",
    );
    expect(cataloguePath(admin, "test", result)).toBe(
      "/api/v1/catalogue/search?q=test&limit=24",
    );
  });
  it("uses canonical condition names and review-gated admin intake", () => {
    expect(intakePayload(access, result, selected, "NM", "")).toEqual({
      recognition_run_id: "run-a",
      selected_catalogue_id: "card-a",
      condition: "Near Mint",
      language: "Japanese",
    });
    expect(intakePayload(admin, result, selected, "LP", "")).toMatchObject({
      catalogue_id: "card-a",
      condition: "Lightly Played",
      identity_confirmed: false,
    });
    expect(() =>
      intakePayload(access, result, selected, "unknown", ""),
    ).toThrow();
  });
  it("keeps sealed and raw physical state separate", () => {
    const payload = intakePayload(
      access,
      result,
      { ...selected, card: { ...selected.card, product_type: "SEALED" } },
      "NM",
      "SEALED",
    );
    expect(payload).toHaveProperty("seal_status", "SEALED");
    expect(payload).not.toHaveProperty("condition");
  });
  it("preserves unknown amounts and uses exact minor units", () => {
    expect(minorUnits("")).toBeNull();
    expect(minorUnits("0")).toBe(0);
    expect(minorUnits("12.35")).toBe(1235);
    expect(money(null)).toBe("Not valued");
    expect(() => minorUnits("1.234")).toThrow();
    expect(() => minorUnits("-2")).toThrow();
  });
  it("keeps unmapped provider candidates selectable through server validation", async () => {
    const { api, transport } = setup(() =>
      response({ ...result, materialized_catalogue_id: "new-card" }),
    );
    await api.login("alex", "secret");
    const selection = await selectCandidate(api, result, {
      id: "candidate",
      catalogue_id: null,
      source_kind: "PROVIDER",
      hard_rejected: false,
      score: 0.9,
      candidate_snapshot: selected.card,
    });
    expect(selection.catalogueId).toBe("new-card");
    expect(selection.outcome).toBe("CORRECTED_BY_SEARCH");
    expect(
      transport.mock.calls.some(([url]) =>
        String(url).endsWith("/candidate/materialize"),
      ),
    ).toBe(true);
  });
  it("does not confirm hard-rejected or failed candidates", async () => {
    const { api } = setup();
    const candidate = {
      id: "x",
      catalogue_id: "x",
      source_kind: "CATALOGUE",
      hard_rejected: true,
      score: 0.9,
      candidate_snapshot: selected.card,
    };
    await expect(selectCandidate(api, result, candidate)).rejects.toThrow(
      "cannot be confirmed",
    );
    await expect(
      selectCandidate(
        api,
        { ...result, run: { ...result.run, status: "FAILED" } },
        { ...candidate, hard_rejected: false },
      ),
    ).rejects.toThrow();
  });
});
describe("session security", () => {
  it("persists only minimal tokens and user identity, never password", async () => {
    const storage = memory();
    const { api } = setup(undefined, storage.vault);
    await api.login("alex", "secret-password");
    const raw = storage.data.get("pulltheory.session.v1")!;
    expect(raw).not.toContain("secret-password");
    expect(JSON.parse(raw)).toEqual(session);
  });
  it("rejects mismatched access identity", async () => {
    const storage = memory();
    const transport = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("owner-session")
        ? response(session)
        : String(input).endsWith("/access/me")
          ? response({ access: { ...access, user_id: "other" } })
          : response({}),
    );
    const api = new Api(storage.vault, "https://test.invalid", transport);
    await expect(api.login("alex", "pw")).rejects.toThrow(
      "could not be verified",
    );
    expect(storage.data.has("pulltheory.session.v1")).toBe(false);
  });
  it("does not authenticate if secure storage fails", async () => {
    const storage = memory();
    storage.vault.set = async () => {
      throw new Error("secure storage unavailable");
    };
    const { api } = setup(undefined, storage.vault);
    await expect(api.login("alex", "pw")).rejects.toThrow("secure storage");
    expect(api.access).toBeNull();
  });
  it("serializes simultaneous refresh requests", async () => {
    const storage = memory();
    await storage.vault.set(
      "pulltheory.session.v1",
      JSON.stringify({ ...session, expires_at: 0 }),
    );
    let refreshes = 0;
    const { api } = setup(async (path) => {
      if (path.endsWith("/token")) {
        refreshes++;
        await new Promise((r) => setTimeout(r, 10));
        return response({ ...session, access_token: "new-token" });
      }
      return response({ ok: true });
    }, storage.vault);
    await api.restore();
    await Promise.all([api.request("/api/v1/a"), api.request("/api/v1/b")]);
    expect(refreshes).toBe(1);
  });
  it("retries an unauthorized request once using a refreshed token", async () => {
    let calls = 0;
    const { api } = setup((path) => {
      if (path.endsWith("/token"))
        return response({ ...session, access_token: "new" });
      calls++;
      return calls === 1
        ? response({ detail: "expired" }, 401)
        : response({ ok: true });
    });
    await api.login("a", "pw");
    await expect(api.request("/api/v1/resource")).resolves.toEqual({
      ok: true,
    });
    expect(calls).toBe(2);
  });
  it("invalid refresh clears credentials", async () => {
    const storage = memory();
    await storage.vault.set(
      "pulltheory.session.v1",
      JSON.stringify({ ...session, expires_at: 0 }),
    );
    const { api } = setup(
      () => response({ detail: "invalid" }, 400),
      storage.vault,
    );
    const expired = vi.fn();
    api.subscribeExpired(expired);
    await expect(api.restore()).rejects.toBeInstanceOf(ApiError);
    expect(storage.data.has("pulltheory.session.v1")).toBe(false);
    expect(expired).toHaveBeenCalledOnce();
  });
  it("does not resurrect a refresh after logout", async () => {
    const storage = memory();
    let release!: (v: Response) => void;
    let notify!: () => void;
    const reached = new Promise<void>((r) => {
      notify = r;
    });
    const { api } = setup((path) => {
      if (path.endsWith("/token")) {
        notify();
        return new Promise<Response>((r) => {
          release = r;
        });
      }
      return response({ detail: "expired" }, 401);
    }, storage.vault);
    await api.login("a", "pw");
    const pending = api.request("/api/v1/resource");
    const expectation = expect(pending).rejects.toThrow("session changed");
    await reached;
    await api.logout();
    release(response({ ...session, access_token: "rotated" }));
    await expectation;
    expect(storage.data.has("pulltheory.session.v1")).toBe(false);
    expect(api.access).toBeNull();
  });
  it("rejects insecure API hosts", () => {
    expect(() => new Api(memory().vault, "http://outside.invalid")).toThrow(
      "secure",
    );
  });
});
describe("durable idempotent intake", () => {
  it("does not expose a completed save to a session that signed in during cleanup", async () => {
    const storage = memory();
    const remove = storage.vault.remove;
    let release!: () => void;
    let reached!: () => void;
    const cleaning = new Promise<void>((resolve) => {
      reached = resolve;
    });
    storage.vault.remove = async (key) => {
      await remove(key);
      if (key.startsWith("pulltheory.intake.")) {
        reached();
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      }
    };
    const { api } = setup(
      () => response({ inventory: { inventory_code: "OLD" } }),
      storage.vault,
    );
    await api.login("a", "pw");
    const saving = api.queueIntake({}, "old-key", "Old card");
    const rejected = expect(saving).rejects.toThrow("session changed");
    await cleaning;
    await api.logout();
    await api.login("a", "pw");
    // The new session has no pending save; it must not inherit the old promise.
    const retry = api.resumeIntake();
    const noPending = expect(retry).rejects.toThrow("No pending save");
    release();
    await Promise.all([rejected, noPending]);
  });
  it("rejects a pending read that finishes after sign-out and re-login", async () => {
    const storage = memory();
    const get = storage.vault.get;
    let release!: () => void;
    let reached!: () => void;
    const reading = new Promise<void>((resolve) => {
      reached = resolve;
    });
    storage.vault.get = async (key) => {
      const value = await get(key);
      if (key.startsWith("pulltheory.intake.")) {
        reached();
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      }
      return value;
    };
    const { api } = setup(undefined, storage.vault);
    await api.login("a", "pw");
    const pending = api.pending();
    const rejected = expect(pending).rejects.toThrow("session changed");
    await reading;
    await api.logout();
    await api.login("a", "pw");
    release();
    await rejected;
  });
  it("coalesces simultaneous retries within the same session", async () => {
    let release!: (value: Response) => void;
    let reached!: () => void;
    const started = new Promise<void>((resolve) => {
      reached = resolve;
    });
    const { api, transport } = setup(() => {
      reached();
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    });
    await api.login("a", "pw");
    const saving = api.queueIntake({}, "stable", "Card");
    await started;
    const retries = [api.resumeIntake(), api.resumeIntake()];
    release(response({ inventory: { inventory_code: "ONCE" } }));
    const results = await Promise.all([saving, ...retries]);
    expect(
      results.every((result) => result.inventory?.inventory_code === "ONCE"),
    ).toBe(true);
    expect(
      transport.mock.calls.filter(([url]) =>
        String(url).endsWith("recognition-intake"),
      ),
    ).toHaveLength(1);
  });
  it("persists before network, and replays exactly after uncertain failure and restart", async () => {
    const storage = memory();
    let first = true;
    const bodies: string[] = [];
    const keys: string[] = [];
    const handler = (_path: string, init?: RequestInit) => {
      expect(storage.data.has("pulltheory.intake.user-a")).toBe(true);
      bodies.push(String(init?.body));
      keys.push(new Headers(init?.headers).get("Idempotency-Key")!);
      if (first) {
        first = false;
        throw new Error("connection lost");
      }
      return response({ inventory: { inventory_code: "INV-A" } });
    };
    const one = setup(handler, storage.vault);
    await one.api.login("a", "pw");
    await expect(
      one.api.queueIntake({ catalogue_id: "card-a" }, "stable-key", "Card"),
    ).rejects.toThrow("Connection interrupted");
    const two = setup(handler, storage.vault);
    await two.api.restore();
    await two.api.resumeIntake();
    expect(keys).toEqual(["stable-key", "stable-key"]);
    expect(bodies[0]).toBe(bodies[1]);
    expect(await two.api.pending()).toBeNull();
  });
  it("does not transmit when saving pending data fails", async () => {
    const storage = memory();
    const { api, transport } = setup(undefined, storage.vault);
    await api.login("a", "pw");
    const before = transport.mock.calls.length;
    storage.vault.set = async () => {
      throw new Error("disk error");
    };
    await expect(api.queueIntake({}, "k", "Card")).rejects.toThrow("disk");
    expect(transport.mock.calls.length).toBe(before);
  });
  it("retains conflicts but clears explicit validation rejections", async () => {
    let status = 409;
    const { api } = setup(() => response({ detail: "rejected" }, status));
    await api.login("a", "pw");
    await expect(api.queueIntake({}, "key", "Card")).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(await api.pending()).not.toBeNull();
    status = 422;
    await expect(api.resumeIntake()).rejects.toBeInstanceOf(ApiError);
    expect(await api.pending()).toBeNull();
  });
  it("blocks replacing an uncertain request with new details", async () => {
    const { api } = setup(() => response({ detail: "upstream failed" }, 500));
    await api.login("a", "pw");
    await expect(api.queueIntake({ a: 1 }, "first", "A")).rejects.toThrow();
    await expect(api.queueIntake({ a: 2 }, "second", "B")).rejects.toThrow(
      "previous pending save",
    );
    expect((await api.pending())?.payload).toEqual({ a: 1 });
  });
  it("refuses pending data for a changed owner or role", async () => {
    const { api, vault } = setup();
    await api.login("a", "pw");
    await vault.set(
      "pulltheory.intake.user-a",
      JSON.stringify({ userId: "user-a", ownerId: "other", role: "OWNER" }),
    );
    await expect(api.pending()).rejects.toThrow("different access context");
  });
  it("prevents concurrent new saves creating separate requests", async () => {
    let release!: (v: Response) => void;
    const { api } = setup(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    );
    await api.login("a", "pw");
    const first = api.queueIntake({}, "one", "A");
    await expect(api.queueIntake({}, "two", "B")).rejects.toThrow(
      "already in progress",
    );
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    release(response({ inventory: {} }));
    await first;
  });
});
