/** Shared read-only presentation contract for the approved single-line Auction Lens.
 *
 * Uses the existing exact Shopify/Seller Hub logo and a locally captured crop.
 * No image is fetched here, and no price is calculated from scraped listings.
 * Only FastAPI's validated GBP comparison can produce a BELOW/ABOVE verdict.
 */
import type { LensView } from "./auctionLensStream";

export const DROP_RATE_BRAND_LOGO_PATH = "/assets/brand-assets/storefront-logo.png";

export type AuctionBannerPresentation = {
  mode: "HIDDEN" | "SCANNING" | "CHECK_VERSION" | "IDENTIFIED";
  title: string;
  subtitle: string;
  enteredBid: string;
  allIn: string;
  ukMarketValue: string;
  verdict: string;
  verdictTone: "neutral" | "positive" | "negative";
  showCardThumbnail: boolean;
};

const pounds = new Intl.NumberFormat("en-GB", {
  style: "currency", currency: "GBP", minimumFractionDigits: 2,
});

function money(value: number): string {
  return pounds.format(value / 100);
}

const blank = (mode: AuctionBannerPresentation["mode"], label: string): AuctionBannerPresentation => ({
  mode,
  title: label,
  subtitle: "Checking exact printing and UK Market Value",
  enteredBid: "—", allIn: "—", ukMarketValue: "—",
  verdict: "CHECKING", verdictTone: "neutral", showCardThumbnail: false,
});

/** No unverified result, unknown charges or expired evidence may show a deal. */
export function presentAuctionBanner(
  view: LensView,
  // Intentionally no implicit price values or image source in this contract.
  enteredBidMinor?: number | null,
  nowMs?: number,
): AuctionBannerPresentation {
  const now = nowMs ?? Date.now();
  if (view.status === "STOPPED" || view.status === "PAUSED") {
    return blank("HIDDEN", "Auction Lens off");
  }
  if (view.status === "WATCHING" || view.status === "CHECKING") {
    return blank("SCANNING", "Scanning card…");
  }
  if (view.status === "CAPTURE_BLOCKED" || view.status === "CHECK_VERSION" ||
      view.status === "NO_MATCH" || view.status === "ERROR") {
    return blank("CHECK_VERSION", "Check card version");
  }

  const result = blank("IDENTIFIED", view.title?.trim() || "Exact card");
  result.subtitle = "Exact printing · UK sold evidence required";
  result.showCardThumbnail = Boolean(view.identityKey && view.title?.trim());
  if (enteredBidMinor !== null && enteredBidMinor !== undefined &&
      Number.isSafeInteger(enteredBidMinor) && enteredBidMinor >= 0) {
    result.enteredBid = money(enteredBidMinor);
  }

  const value = view.value;
  if (!value || value.currency !== "GBP" || value.valuationEligible !== true ||
      !Number.isSafeInteger(value.marketValueMinor) || value.marketValueMinor <= 0 ||
      value.expiresAtMs <= now || !value.source?.trim()) {
    result.verdict = "NO CURRENT VALUE";
    return result;
  }
  result.ukMarketValue = money(value.marketValueMinor);
  result.verdict = "VALUE CHECKED";

  const quote = view.comparison;
  if (quote?.bidExpiresAtMs && quote.bidExpiresAtMs <= now) {
    result.verdict = "BID TOO OLD";
    return result;
  }
  if (quote?.status === "CHARGES_UNKNOWN") {
    result.verdict = "FEES UNKNOWN";
    return result;
  }
  if (quote?.status === "STALE_BID") {
    result.verdict = "BID TOO OLD";
    return result;
  }
  if (!quote || !["UNDER_MARKET", "OVER_MARKET", "AROUND_MARKET"].includes(quote.status) ||
      !Number.isSafeInteger(quote.allInMinor) || quote.allInMinor! < 0 ||
      quote.marketValueMinor !== value.marketValueMinor ||
      !Number.isSafeInteger(quote.differenceMinor) ||
      quote.differenceMinor !== value.marketValueMinor - quote.allInMinor! ||
      !Number.isFinite(quote.bidExpiresAtMs) || quote.bidExpiresAtMs! <= now) {
    return result;
  }
  result.allIn = money(quote.allInMinor!);
  if (quote.status === "UNDER_MARKET" && quote.differenceMinor! > 0) {
    result.verdict = money(quote.differenceMinor!) + " BELOW";
    result.verdictTone = "positive";
  } else if (quote.status === "OVER_MARKET" && quote.differenceMinor! < 0) {
    result.verdict = money(-quote.differenceMinor!) + " ABOVE";
    result.verdictTone = "negative";
  } else if (quote.status === "AROUND_MARKET") {
    result.verdict = "AROUND MARKET";
  }
  return result;
}
