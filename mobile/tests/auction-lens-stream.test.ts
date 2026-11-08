import { describe, expect, it, vi } from "vitest";
import { AuctionLensStream, type CaptureFrame, type VerifiedRecognition } from "../src/lib/auctionLensStream";

const HASH_A = "1111111111111111";
const HASH_B = "eeeeeeeeeeeeeeee";
const frame = (capturedAtMs: number, fingerprint64 = HASH_A, lotToken?: string): CaptureFrame => ({
  capturedAtMs, fingerprint64, quality: "CLEAR",
  jpegDataUrl: "data:image/jpeg;base64,ZmFrZS1jcm9w",
  ...(lotToken ? { lotToken } : {}),
});
const result = (generation: number): VerifiedRecognition => ({
  generation, decision: "EXACT", identityKey: "TEF/001/EN/NORMAL/RAW",
  title: "Example verified card",
  value: {
    marketValueMinor: 12000, currency: "GBP", source: "Trusted UK valuation",
    valuationEligible: true, expiresAtMs: Date.now() + 60000,
  },
});
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

describe("bounded live auction frame coordinator", () => {
  it("waits for three agreeing frames, scans only once per unchanged scene", async () => {
    const resolve = vi.fn(async (_f: CaptureFrame, g: number) => result(g));
    const changes: string[] = [];
    const loop = new AuctionLensStream(resolve, v => changes.push(v.status));
    loop.start();
    loop.ingest(frame(0)); loop.ingest(frame(250));
    expect(resolve).toHaveBeenCalledTimes(0);
    loop.ingest(frame(500)); await tick();
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(loop.snapshot(Date.now()).status).toBe("IDENTIFIED");
    for (let t = 750; t < 10000; t += 250) loop.ingest(frame(t));
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(changes).toContain("CHECKING");
  });

  it("abstains if backend knows identity but cannot prove an eligible UK value", async () => {
    const loop = new AuctionLensStream(async (_frame, g) => ({ ...result(g), value: undefined }), () => {});
    loop.start();
    for (let t of [0, 250, 500]) loop.ingest(frame(t));
    await tick();
    expect(loop.snapshot(Date.now()).status).toBe("NO_VALUE");
    expect(loop.snapshot(Date.now()).value).toBeUndefined();
  });

  it("immediately clears the old card when footage switches lots", async () => {
    const calls: { resolve: (v: VerifiedRecognition) => void; generation: number }[] = [];
    const resolve = vi.fn((_frame: CaptureFrame, generation: number) =>
      new Promise<VerifiedRecognition>(fn => calls.push({ resolve: fn, generation })));
    const loop = new AuctionLensStream(resolve, () => {});
    loop.start();
    for (let t of [0, 250, 500]) loop.ingest(frame(t));
    expect(calls).toHaveLength(1);
    loop.ingest(frame(750, HASH_B));
    expect(loop.snapshot(Date.now()).status).toBe("WATCHING");
    calls[0].resolve(result(calls[0].generation)); await tick();
    expect(loop.snapshot(Date.now()).value).toBeUndefined();
    loop.ingest(frame(1000, HASH_B)); loop.ingest(frame(1250, HASH_B)); await tick();
    expect(calls).toHaveLength(2);
  });

  it("explicit lot tokens invalidate identical-looking consecutive cards", async () => {
    const resolve = vi.fn(async (_frame: CaptureFrame, generation: number) => result(generation));
    const loop = new AuctionLensStream(resolve, () => {});
    loop.start();
    for (let t of [0,250,500]) loop.ingest(frame(t,HASH_A,"lot-1"));
    await tick(); expect(loop.snapshot(Date.now()).status).toBe("IDENTIFIED");
    loop.ingest(frame(750,HASH_A,"lot-2"));
    expect(loop.snapshot(Date.now()).value).toBeUndefined();
    loop.ingest(frame(1000,HASH_A,"lot-2"));
    loop.ingest(frame(1250,HASH_A,"lot-2"));
    await tick();
    expect(resolve).toHaveBeenCalledTimes(2);
  });

  it("no new work while paused/stopped; late provider answers cannot repaint", async () => {
    let finish!: (v: VerifiedRecognition) => void;
    const loop = new AuctionLensStream((_f,g) =>
      new Promise<VerifiedRecognition>(resolve => {finish=resolve}), () => {});
    loop.start();
    for(let t of [0,250,500])loop.ingest(frame(t));
    const old = loop.snapshot(0).generation;
    loop.stop(); expect(loop.ingest(frame(750))).toBe(false);
    finish(result(old)); await tick();
    expect(loop.snapshot(Date.now()).status).toBe("STOPPED");
    expect(loop.snapshot(Date.now()).value).toBeUndefined();
  });

  it("blank/protected frame and blurry crop immediately hide the old price", async () => {
    const loop = new AuctionLensStream(async (_f,g) => result(g), () => {});
    loop.start(); [0,250,500].forEach(t=>loop.ingest(frame(t))); await tick();
    const blank = {...frame(750), quality: "PROTECTED" as const };
    loop.ingest(blank);
    expect(loop.snapshot(Date.now()).status).toBe("CAPTURE_BLOCKED");
    expect(loop.snapshot(Date.now()).value).toBeUndefined();
    loop.ingest({ ...frame(1000), quality: "BLURRED" });
    expect(loop.snapshot(Date.now()).status).toBe("CHECK_VERSION");
  });

  it("does not collapse 1000 high-frequency frames into 1000 cloud calls", async () => {
    const resolve = vi.fn(async (_f:CaptureFrame,g:number) => result(g));
    const loop = new AuctionLensStream(resolve, () => {});
    loop.start();
    for (let t=0; t<1000; t++) loop.ingest(frame(t));
    await tick();
    expect(resolve).toHaveBeenCalledTimes(1);
  });

  it("clears expired market values even if an otherwise identical card remains visible", async () => {
    const value = { ...result(1), value: { ...result(1).value!, expiresAtMs: Date.now() + 100 } };
    const loop = new AuctionLensStream(async (_f,g) => ({...value, generation:g}), () => {});
    loop.start();[0,250,500].forEach(t=>loop.ingest(frame(t))); await tick();
    expect(loop.snapshot(Date.now()).status).toBe("IDENTIFIED");
    expect(loop.snapshot(Date.now()+200).status).toBe("NO_VALUE");
  });

  it("expires an observed bid verdict without hiding still-eligible market evidence", async () => {
    const bidExpiry = Date.now() + 100;
    const loop = new AuctionLensStream(async (_f,g) => ({
      ...result(g), generation:g,
      comparison:{status:"UNDER_MARKET",allInMinor:6500,marketValueMinor:12000,
        differenceMinor:5500,bidExpiresAtMs:bidExpiry},
    }), () => {});
    loop.start();[0,250,500].forEach(t=>loop.ingest(frame(t)));await tick();
    expect(loop.snapshot(Date.now()).comparison?.status).toBe("UNDER_MARKET");
    const expired=loop.snapshot(bidExpiry+1);
    expect(expired.comparison?.status).toBe("STALE_BID");
    expect(expired.value?.marketValueMinor).toBe(12000);
  });

  it("rejects a generation mismatch from a delayed/invalid backend response", async () => {
    const loop = new AuctionLensStream(async (_f,g) => result(g+100), () => {});
    loop.start();[0,250,500].forEach(t=>loop.ingest(frame(t)));await tick();
    expect(loop.snapshot(Date.now()).status).toBe("CHECK_VERSION");
  });

  it("rejects invalid cadence and non-positive stable budget", () => {
    expect(() => new AuctionLensStream(async (_f,g) => result(g), () => {}, {stableFrames:1})).toThrow();
    expect(() => new AuctionLensStream(async (_f,g) => result(g), () => {}, {sampleEveryMs:0})).toThrow();
  });
});
