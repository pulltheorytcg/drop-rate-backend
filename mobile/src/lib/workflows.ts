import type { Api } from "./api";
import type { Access, Card, Candidate, Recognition, Selection } from "./types";
export const inventoryPath = (access: Access) =>
  access.access_role === "OWNER"
    ? "/api/v1/owner/inventory"
    : "/api/v1/inventory";
export const cataloguePath = (
  access: Access,
  query: string,
  run?: Recognition,
) => {
  const q = encodeURIComponent(query.trim());
  return access.access_role === "OWNER"
    ? `/api/v1/owner/catalogue-search?q=${q}&limit=24${run ? "&include_reference=true&run_id=" + encodeURIComponent(run.run.id) : ""}`
    : `/api/v1/catalogue/search?q=${q}&limit=24`;
};
export async function selectCandidate(
  api: Api,
  result: Recognition,
  candidate: Candidate,
): Promise<Selection> {
  if (candidate.hard_rejected || result.run.status === "FAILED")
    throw new Error(
      "This result cannot be confirmed. Search for the exact printing instead.",
    );
  let id = candidate.catalogue_id;
  if (!id) {
    if (candidate.source_kind !== "PROVIDER")
      throw new Error(
        "This candidate needs catalogue review. Search for a confirmed printing.",
      );
    const materialized = await api.request<Recognition>(
      `/api/v1/recognition/runs/${result.run.id}/candidates/${candidate.id}/materialize`,
      "POST",
    );
    id =
      materialized.materialized_catalogue_id ??
      materialized.candidates.find((c) => c.id === candidate.id)
        ?.catalogue_id ??
      null;
    if (!id) throw new Error("This printing still needs catalogue review.");
    // Provider mapping does not rewrite immutable candidate rows; use the human
    // correction outcome supported by owner intake after materialization.
    return {
      card: candidate.candidate_snapshot,
      catalogueId: id,
      outcome: "CORRECTED_BY_SEARCH",
    };
  }
  return {
    card: candidate.candidate_snapshot,
    catalogueId: id,
    outcome:
      id === result.run.top_catalogue_id
        ? "CONFIRMED_TOP"
        : "CORRECTED_TO_CANDIDATE",
  };
}
export async function selectSearch(
  api: Api,
  result: Recognition,
  card: Card,
): Promise<Selection> {
  let id = card.id;
  if (card.requires_materialization) {
    const selected = await api.request<{ catalogue_id: string }>(
      `/api/v1/recognition/runs/${result.run.id}/references/select`,
      "POST",
      {
        provider: card.provider,
        system_code: card.system_code,
        language: card.language,
        provider_id: card.provider_id,
      },
    );
    id = selected.catalogue_id;
  }
  if (!id) throw new Error("Choose an exact catalogue printing.");
  return { card, catalogueId: id, outcome: "CORRECTED_BY_SEARCH" };
}
export const CONDITIONS: Record<string, string> = {
  NM: "Near Mint",
  LP: "Lightly Played",
  MP: "Moderately Played",
  HP: "Heavily Played",
  DMG: "Damaged",
};
export function intakePayload(
  access: Access,
  result: Recognition,
  selected: Selection,
  condition: string,
  sealStatus: string,
) {
  const sealed = selected.card.product_type === "SEALED";
  if (sealed && !["SEALED", "UNSEALED"].includes(sealStatus))
    throw new Error("Choose the seal status.");
  if (!sealed && !CONDITIONS[condition])
    throw new Error("Choose a valid card condition.");
  const physical = sealed
    ? { seal_status: sealStatus }
    : { condition: CONDITIONS[condition] };
  if (access.access_role === "OWNER")
    return {
      recognition_run_id: result.run.id,
      selected_catalogue_id: selected.catalogueId,
      ...physical,
      language: selected.card.language || null,
    };
  return {
    catalogue_id: selected.catalogueId,
    ...physical,
    language: selected.card.language || null,
    identity_confirmed: false,
    notes: `Mobile intake; human-reviewed recognition ${result.run.id}. Pending operational approval.`,
  };
}
