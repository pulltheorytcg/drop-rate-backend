import { describe, expect, it } from "vitest";
import { DROP_RATE_BRAND_LOGO_PATH, presentAuctionBanner } from "../src/lib/auctionLensBanner";
import type { LensView, VerifiedAuctionComparison } from "../src/lib/auctionLensStream";

const expiry = Date.now() + 120000;
const verified: LensView = {
  status: "IDENTIFIED", generation: 9,
  identityKey: "card:approved-print:English:Normal:RAW",
  title: "Rapidash · Temporal Forces · 048/162",
  value: {
    marketValueMinor: 10000, currency: "GBP",
    source: "Drop Rate eligible UK sold",
    expiresAtMs: expiry, valuationEligible: true,
  },
};

const quote = (status: VerifiedAuctionComparison["status"], allInMinor: number): VerifiedAuctionComparison => ({
  status, allInMinor, marketValueMinor: 10000,
  differenceMinor: 10000 - allInMinor,
});

describe("compact branded Auction Lens presentation", () => {
  it("uses actual project storefront logo, not a generated symbol", () => {
    expect(DROP_RATE_BRAND_LOGO_PATH).toBe("/assets/brand-assets/storefront-logo.png");
  });

  it("does not retain a prior card or price when stopped, paused or protected", () => {
    for(const status of ["STOPPED", "PAUSED", "CAPTURE_BLOCKED", "CHECK_VERSION", "WATCHING"] as const) {
      const result = presentAuctionBanner({...verified, status});
      expect(result.showCardThumbnail).toBe(false);
      expect(result.ukMarketValue).toBe("—");
      expect(result.verdictTone).toBe("neutral");
    }
  });

  it("shows exact identity but not a deal if price is missing", () => {
    const result = presentAuctionBanner({...verified, value: undefined}, 5000);
    expect(result.mode).toBe("IDENTIFIED");
    expect(result.enteredBid).toBe("£50.00");
    expect(result.ukMarketValue).toBe("—");
    expect(result.verdict).toBe("NO CURRENT VALUE");
    expect(result.allIn).toBe("—");
  });

  it("shows the three allowed states only with matching server-signed arithmetic", () => {
    const under = presentAuctionBanner({...verified, comparison: quote("UNDER_MARKET", 6500)}, 5000);
    expect(under.verdict).toBe("£35.00 BELOW");
    expect(under.verdictTone).toBe("positive");
    expect(under.allIn).toBe("£65.00");
    expect(under.ukMarketValue).toBe("£100.00");

    const over = presentAuctionBanner({...verified, comparison: quote("OVER_MARKET", 12500)}, 11000);
    expect(over.verdict).toBe("£25.00 ABOVE");
    expect(over.verdictTone).toBe("negative");

    const around = presentAuctionBanner({...verified, comparison: quote("AROUND_MARKET", 10100)}, 8500);
    expect(around.verdict).toBe("AROUND MARKET");
    expect(around.verdictTone).toBe("neutral");
  });

  it("never guesses missing fees or expired bids", () => {
    for (const status of ["CHARGES_UNKNOWN", "STALE_BID"] as const) {
      const result = presentAuctionBanner({...verified, comparison: {status}}, 5000);
      expect(result.allIn).toBe("—");
      expect(result.verdictTone).toBe("neutral");
      expect(result.verdict).toBe(status === "CHARGES_UNKNOWN" ? "FEES UNKNOWN" : "BID TOO OLD");
    }
  });

  it("rejects client-inconsistent comparison payloads", () => {
    const manipulated: LensView = {
      ...verified, comparison: {
        ...quote("UNDER_MARKET", 6500), differenceMinor: 99000,
      },
    };
    const result = presentAuctionBanner(manipulated);
    expect(result.verdict).toBe("VALUE CHECKED");
    expect(result.allIn).toBe("—");
    expect(result.verdictTone).toBe("neutral");
  });

  it("never shows an expired market price after a long auction session", () => {
    const result = presentAuctionBanner(verified, 5000, expiry + 1);
    expect(result.ukMarketValue).toBe("—");
    expect(result.verdict).toBe("NO CURRENT VALUE");
  });
});
