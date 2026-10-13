-- Hard block any future English-guide quote on a Japanese One Piece reference.
-- This fixes the 13 Oct 2026 454-row cross-language fallback incident.
-- Existing invalid current quotes were quarantined without deleting audit history.
-- Only the already-used Cardmarket bulk source is affected; no RLS/access change.
ALTER TABLE tcg.reference_market_prices
  ADD CONSTRAINT reference_market_one_piece_japanese_source_language
  CHECK (
    NOT (
      system_code = 'ONE_PIECE_CARD_GAME'
      AND language = 'Japanese'
      AND quotes <> '[]'::jsonb
      AND COALESCE(quotes->0->>'source','') = 'CARDMARKET_BULK_SINGLES'
      AND COALESCE(quotes->0->>'reference_language','') <> 'Japanese'
    )
  ) NOT VALID;

ALTER TABLE tcg.reference_market_prices
  VALIDATE CONSTRAINT reference_market_one_piece_japanese_source_language;

COMMENT ON CONSTRAINT reference_market_one_piece_japanese_source_language
 ON tcg.reference_market_prices IS
'Japanese One Piece Cardmarket bulk guides require explicit Japanese reference language provenance; prevents English quote collision by provider id.';
