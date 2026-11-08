/**
 * Auction Lens: bounded, client-side scene scheduler for consented image frames.
 *
 * Capture and identity recognition are separate. This code never captures the
 * screen, calls a provider, shows a speculative price or stores video frames.
 * The resolver must return a server-validated exact-print decision.
 *
 * Identical consecutive physical copies cannot be distinguished from pixels:
 * the caller must call newLot() when the auction changes lots without a visual
 * transition, or supply an authoritative changing lotToken.
 */

export type LensStatus =
  | "STOPPED"
  | "WATCHING"
  | "CHECKING"
  | "IDENTIFIED"
  | "NO_VALUE"
  | "CHECK_VERSION"
  | "NO_MATCH"
  | "PAUSED"
  | "CAPTURE_BLOCKED"
  | "ERROR";

export type CaptureFrame = {
  capturedAtMs: number; // monotonic clock, never Date.now()
  fingerprint64: string; // 64-bit dHash of locally cropped item, lowercase hex
  jpegDataUrl: string; // ephemeral, cropped item only; do not include full UI
  quality: "CLEAR" | "BLURRED" | "EMPTY" | "PROTECTED";
  lotToken?: string; // only if obtained through a permitted/authoritative source
};

export type VerifiedAuctionComparison = {
  status:
    | "UNDER_MARKET" | "OVER_MARKET" | "AROUND_MARKET"
    | "NO_CURRENT_MARKET_VALUE" | "CHARGES_UNKNOWN" | "STALE_BID"
    | "CHECK_VERSION" | "AUCTION_NOT_ACTIVE" | "UNSUPPORTED_CURRENCY";
  allInMinor?: number;
  marketValueMinor?: number;
  differenceMinor?: number;
  bidExpiresAtMs?: number;
  source?: string;
  evidenceAtMs?: number;
};

/** Only the server can create the verdict; the client may reject unsafe data. */
function eligibleComparison(
  comparison: VerifiedAuctionComparison | undefined,
  marketValueMinor: number | undefined,
  nowMs: number
): VerifiedAuctionComparison | undefined {
  if (!comparison || marketValueMinor === undefined) return undefined;
  if (["UNDER_MARKET", "OVER_MARKET", "AROUND_MARKET"].includes(comparison.status)) {
    if (!Number.isSafeInteger(comparison.allInMinor) ||
        comparison.allInMinor! < 0 ||
        comparison.marketValueMinor !== marketValueMinor ||
        !Number.isSafeInteger(comparison.differenceMinor) ||
        comparison.differenceMinor !== marketValueMinor - comparison.allInMinor! ||
        !Number.isFinite(comparison.bidExpiresAtMs) ||
        comparison.bidExpiresAtMs! <= nowMs) {
      return undefined;
    }
    return comparison;
  }
  if (["CHARGES_UNKNOWN", "STALE_BID", "CHECK_VERSION", "NO_CURRENT_MARKET_VALUE",
       "AUCTION_NOT_ACTIVE", "UNSUPPORTED_CURRENCY"].includes(comparison.status) &&
      comparison.allInMinor === undefined && comparison.marketValueMinor === undefined &&
      comparison.differenceMinor === undefined) {
    return { status: comparison.status };
  }
  return undefined;
}

export type VerifiedRecognition = {
  generation: number;
  decision: "EXACT" | "CHECK_VERSION" | "NO_MATCH";
  identityKey?: string;
  title?: string;
  /**
   * The backend may include a value ONLY after exact-identity, profile,
   * expiry, currency, market-region, source-rights and eligibility checks.
   */
  comparison?: VerifiedAuctionComparison;
  value?: {
    marketValueMinor: number;
    currency: "GBP";
    source: string;
    expiresAtMs: number;
    valuationEligible: true;
  };
};

export type LensView = {
  status: LensStatus;
  generation: number;
  identityKey?: string;
  title?: string;
  value?: VerifiedRecognition["value"];
  comparison?: VerifiedAuctionComparison;
};

export type FrameResolver = (frame: CaptureFrame, generation: number, signal: AbortSignal) =>
  Promise<VerifiedRecognition>;

export type LensSettings = {
  sampleEveryMs?: number;
  stableFrames?: number;
  maxSameItemHashDistance?: number;
  // Signal frame has changed; clear any prior card/value immediately.
  maxChangedHashDistance?: number;
};

const HASH64 = /^[0-9a-f]{16}$/;
const DEFAULTS = {
  sampleEveryMs: 250, // ~4 locally examined crops / sec. Only one remote call/lot.
  stableFrames: 3,
  maxSameItemHashDistance: 6,
  maxChangedHashDistance: 14,
} as const;

function hamming(left: string, right: string): number {
  let bits = BigInt("0x" + left) ^ BigInt("0x" + right);
  let distance = 0;
  while (bits > 0n) {
    bits &= bits - 1n;
    distance += 1;
  }
  return distance;
}

function validValue(value: VerifiedRecognition["value"], nowMs: number): boolean {
  return Boolean(
    value &&
    value.currency === "GBP" &&
    value.valuationEligible === true &&
    Number.isSafeInteger(value.marketValueMinor) &&
    value.marketValueMinor > 0 &&
    Number.isFinite(value.expiresAtMs) &&
    value.expiresAtMs > nowMs &&
    typeof value.source === "string" &&
    value.source.trim().length > 0
  );
}

/** No global singleton: each device session has its own isolated controller. */
export class AuctionLensStream {
  private view: LensView = { status: "STOPPED", generation: 0 };
  private lastFrameAt = -Infinity;
  private anchorHash: string | null = null;
  private consecutiveStable = 0;
  private lotToken: string | undefined;
  private attemptedGeneration = -1;
  private inFlight: { generation: number; controller: AbortController } | null = null;
  private readonly options: Required<LensSettings>;

  constructor(
    private readonly resolve: FrameResolver,
    private readonly onChange: (view: Readonly<LensView>) => void,
    options: LensSettings = {}
  ) {
    this.options = { ...DEFAULTS, ...options };
    if (
      !Number.isFinite(this.options.sampleEveryMs) || this.options.sampleEveryMs < 100 ||
      !Number.isSafeInteger(this.options.stableFrames) || this.options.stableFrames < 2 ||
      !Number.isSafeInteger(this.options.maxSameItemHashDistance) ||
      !Number.isSafeInteger(this.options.maxChangedHashDistance) ||
      this.options.maxSameItemHashDistance < 0 ||
      this.options.maxChangedHashDistance > 64 ||
      this.options.maxChangedHashDistance < this.options.maxSameItemHashDistance
    ) {
      throw new Error("Invalid bounded frame sampling configuration");
    }
  }

  snapshot(nowMs: number): LensView {
    // Value expiry is checked in addition to server-side eligibility.
    if (this.view.value && nowMs >= this.view.value.expiresAtMs) {
      this.publish({ status: "NO_VALUE", generation: this.view.generation,
        identityKey: this.view.identityKey, title: this.view.title });
    } else if (this.view.comparison?.bidExpiresAtMs &&
               nowMs >= this.view.comparison.bidExpiresAtMs) {
      const { comparison: _expired, ...prior } = this.view;
      this.publish({ ...prior, comparison: {status:"STALE_BID"} });
    }
    return { ...this.view };
  }

  start(): void {
    this.abort();
    this.anchorHash = null;
    this.consecutiveStable = 0;
    this.lastFrameAt = -Infinity;
    this.lotToken = undefined;
    this.attemptedGeneration = -1;
    this.publish({ status: "WATCHING", generation: this.view.generation + 1 });
  }

  pause(): void {
    if (this.view.status === "STOPPED") return;
    this.abort();
    this.anchorHash = null;
    this.consecutiveStable = 0;
    this.publish({ status: "PAUSED", generation: this.view.generation + 1 });
  }

  resume(): void {
    if (this.view.status !== "PAUSED") return;
    this.start();
  }

  stop(): void {
    this.abort();
    this.anchorHash = null;
    this.consecutiveStable = 0;
    this.lastFrameAt = -Infinity;
    this.publish({ status: "STOPPED", generation: this.view.generation + 1 });
  }

  newLot(): void {
    if (this.view.status === "STOPPED" || this.view.status === "PAUSED") return;
    this.resetScene("WATCHING");
  }

  private abort(): void {
    if (this.inFlight) {
      this.inFlight.controller.abort();
      // Only one in-flight resolution at a time. No detached new request is
      // started while an old non-cooperative resolver is still finishing.
    }
  }

  private publish(next: LensView): void {
    this.view = next;
    this.onChange({ ...next });
  }

  private resetScene(status: LensStatus): void {
    this.abort();
    this.anchorHash = null;
    this.consecutiveStable = 0;
    this.attemptedGeneration = -1;
    this.publish({ status, generation: this.view.generation + 1 });
  }

  /**
   * Consume at most 4 samples/sec, with no result until >=3 agreeing crops.
   * Call only with explicit user consent and an authorised content source.
   * Returns false when a frame was intentionally discarded.
   */
  ingest(frame: CaptureFrame): boolean {
    if (this.view.status === "STOPPED" || this.view.status === "PAUSED") return false;
    if (!Number.isFinite(frame.capturedAtMs) ||
        frame.capturedAtMs < this.lastFrameAt ||
        frame.capturedAtMs - this.lastFrameAt < this.options.sampleEveryMs) {
      return false;
    }
    this.lastFrameAt = frame.capturedAtMs;
    if (frame.quality === "PROTECTED" || frame.quality === "EMPTY") {
      this.resetScene("CAPTURE_BLOCKED");
      return true;
    }
    if (frame.quality === "BLURRED" || !HASH64.test(frame.fingerprint64) ||
        !frame.jpegDataUrl.startsWith("data:image/jpeg;base64,")) {
      this.resetScene("CHECK_VERSION");
      return true;
    }
    if (frame.lotToken !== undefined && frame.lotToken !== this.lotToken) {
      // A permitted, trusted lot change overrides pixel similarity.
      this.resetScene("WATCHING");
      this.lotToken = frame.lotToken;
    }
    if (this.anchorHash !== null) {
      const distance = hamming(this.anchorHash, frame.fingerprint64);
      if (distance > this.options.maxSameItemHashDistance) {
        // Even a possibly glare-induced transition invalidates the prior
        // valuation. Large changes mean a new scene; intermediate changes
        // remain uncertain until clear frames arrive.
        this.resetScene(
          distance > this.options.maxChangedHashDistance ? "WATCHING" : "CHECK_VERSION"
        );
      }
    }
    if (this.anchorHash === null) {
      this.anchorHash = frame.fingerprint64;
      this.consecutiveStable = 1;
    } else {
      this.consecutiveStable += 1;
    }
    const generation = this.view.generation;
    if (this.consecutiveStable < this.options.stableFrames ||
        this.attemptedGeneration === generation ||
        this.inFlight !== null) {
      return true;
    }
    this.attemptedGeneration = generation;
    this.publish({ status: "CHECKING", generation });
    const controller = new AbortController();
    this.inFlight = { generation, controller };
    // Never retain frame bytes in controller state or log them.
    void this.resolve(frame, generation, controller.signal).then((result) => {
      if (controller.signal.aborted || generation !== this.view.generation ||
          this.view.status === "PAUSED" || this.view.status === "STOPPED") return;
      if (result.generation !== generation || result.decision !== "EXACT" ||
          !result.identityKey || !result.title?.trim()) {
        this.publish({ status: result.decision === "NO_MATCH" ? "NO_MATCH" : "CHECK_VERSION",
          generation });
        return;
      }
      // The remote endpoint is still required to verify exact printing and
      // market evidence. Client-side display gate is defence-in-depth.
      const valueIsCurrent = validValue(result.value, Date.now());
      const comparison = valueIsCurrent
        ? eligibleComparison(result.comparison, result.value?.marketValueMinor, Date.now())
        : undefined;
      this.publish({
        status: valueIsCurrent ? "IDENTIFIED" : "NO_VALUE",
        generation, identityKey: result.identityKey, title: result.title,
        ...(valueIsCurrent ? { value: result.value } : {}),
        ...(comparison ? {comparison} : {}),
      });
    }).catch(() => {
      if (!controller.signal.aborted && generation === this.view.generation) {
        this.publish({ status: "ERROR", generation });
      }
    }).finally(() => {
      if (this.inFlight?.controller === controller) this.inFlight = null;
    });
    return true;
  }
}
