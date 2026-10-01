begin;

-- Exact collector-number correction must remain fast even when vision guessed
-- the wrong game/language. Existing reference-card indexes lead with
-- system_code/language, so they cannot efficiently serve a global number_key lookup.
create index if not exists reference_cards_number_key_global_idx
    on tcg.reference_cards(number_key);

commit;
