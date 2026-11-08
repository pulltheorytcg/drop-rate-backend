/** Consented owned/test video -> authenticated read-only Auction Lens API.
 * Capture and OCR are separate. No WebView credential extraction or live feeds.
 */
import { HUB_ORIGIN } from "./hub";
import type { CaptureFrame, FrameResolver, VerifiedRecognition, VerifiedAuctionComparison } from "./auctionLensStream";

export type PilotCardObservation = {
  game: "Pokemon";
  language: "English";
  name: string;
  set_name: string;
  card_number: string;
  finish: "Normal" | "Holofoil" | "Reverse Holofoil";
  object_type: "RAW_CARD";
};
/** Explicit, observed GBP inputs only; NEVER client-supplied Market Value. */
export type ObservedAuctionQuote = {
  lot_ref: string;
  status: "ACTIVE" | "ENDED";
  currency: "GBP";
  bid_minor: number;
  shipping_minor: number | null;
  buyer_fees_minor: number | null;
  import_tax_minor: number | null;
  additional_costs_minor: number | null;
  bid_observed_at: string;
};

export type PilotInput = {
  source: "OWN_VIDEO" | "EXPLICITLY_AUTHORISED_VIDEO";
  observed: PilotCardObservation;
  confirmed_raw_condition?: "Near Mint";
  quote?: ObservedAuctionQuote;
};
export type PilotContext = {
  accessToken: () => Promise<string | null>;
  currentInput: () => PilotInput | null;
  transport?: typeof fetch;
};
const PILOT_ENDPOINT = HUB_ORIGIN + "/api/v1/auction-lens/pilot/resolve";

function safeResult(value: unknown, generation: number): VerifiedRecognition {
  if (!value || typeof value !== "object") return {generation,decision:"CHECK_VERSION"};
  const response = value as Record<string, unknown>;
  if (response.generation !== generation) return {generation,decision:"CHECK_VERSION"};
  if (response.decision !== "EXACT" || typeof response.identityKey !== "string" ||
      !response.identityKey.startsWith("card:") ||
      typeof response.title !== "string" || !response.title.trim()) {
    return {generation,decision:"CHECK_VERSION"};
  }
  const result: VerifiedRecognition = {
    generation, decision:"EXACT", identityKey: response.identityKey, title: response.title,
  };
  const raw = response.value;
  if (raw && typeof raw === "object") {
    const price = raw as Record<string,unknown>;
    if (price.currency === "GBP" && price.valuationEligible === true &&
        typeof price.source === "string" && price.source.trim() &&
        typeof price.marketValueMinor === "number" && Number.isSafeInteger(price.marketValueMinor) &&
        price.marketValueMinor > 0 &&
        typeof price.expiresAtMs === "number" && Number.isFinite(price.expiresAtMs) &&
        price.expiresAtMs > Date.now()) {
      result.value = {
        marketValueMinor:price.marketValueMinor, currency:"GBP", source:price.source,
        expiresAtMs:price.expiresAtMs, valuationEligible:true,
      };
    }
  }
  const rawComparison=response.comparison;
  if (rawComparison && typeof rawComparison === "object" && result.value) {
    const cmp=rawComparison as Record<string,unknown>;
    const status=cmp.status;
    const comparable=["UNDER_MARKET","OVER_MARKET","AROUND_MARKET"];
    const abstain=["CHARGES_UNKNOWN","STALE_BID","CHECK_VERSION",
      "NO_CURRENT_MARKET_VALUE","AUCTION_NOT_ACTIVE","UNSUPPORTED_CURRENCY"];
    if (typeof status==="string" && comparable.includes(status) &&
        Number.isSafeInteger(cmp.allInMinor) && (cmp.allInMinor as number)>=0 &&
        cmp.marketValueMinor===result.value.marketValueMinor &&
        Number.isSafeInteger(cmp.differenceMinor) &&
        cmp.differenceMinor===result.value.marketValueMinor-(cmp.allInMinor as number) &&
        Number.isFinite(cmp.bidExpiresAtMs) &&
        (cmp.bidExpiresAtMs as number)>Date.now()) {
      result.comparison={
        status:status as VerifiedAuctionComparison["status"],
        allInMinor:cmp.allInMinor as number,
        marketValueMinor:cmp.marketValueMinor as number,
        differenceMinor:cmp.differenceMinor as number,
        bidExpiresAtMs:cmp.bidExpiresAtMs as number,
      };
    } else if(typeof status==="string" && abstain.includes(status) &&
              cmp.allInMinor===undefined && cmp.marketValueMinor===undefined &&
              cmp.differenceMinor===undefined) {
      result.comparison={status:status as VerifiedAuctionComparison["status"]};
    }
  }
  return result;
}

export function createAuthorisedAuctionResolver(context: PilotContext): FrameResolver {
  const network = context.transport ?? fetch;
  return async function resolve(frame: CaptureFrame, generation: number,
                                signal: AbortSignal): Promise<VerifiedRecognition> {
    const input = context.currentInput();
    const token = await context.accessToken();
    if (!input || !token || signal.aborted || frame.quality !== "CLEAR") {
      return {generation,decision:"CHECK_VERSION"};
    }
    const response = await network(PILOT_ENDPOINT, {
      method:"POST", signal, credentials:"omit", cache:"no-store",
      headers:{"Content-Type":"application/json", Authorization:"Bearer " + token},
      body:JSON.stringify({
        generation, image_data_url:frame.jpegDataUrl,
        observed:input.observed, source:input.source,
        ...(input.confirmed_raw_condition
          ? {confirmed_raw_condition:input.confirmed_raw_condition} : {}),
        ...(input.quote ? {quote:input.quote} : {}),
      }),
    });
    if (!response.ok) {
      if ([403,404,422,429].includes(response.status)) {
        return {generation,decision:"CHECK_VERSION"};
      }
      throw new Error("Auction recognition service unavailable");
    }
    return safeResult(await response.json(),generation);
  };
}
