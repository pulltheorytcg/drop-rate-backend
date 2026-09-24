-- Keep raw condition, grading and seal state as separate physical concepts.
-- Existing rows were checked before this migration: graded rows have no condition,
-- and non-card rows have no condition/grading overlap.

alter table tcg.inventory_items
add constraint inventory_items_physical_state_separation_check
check (
    (
        nullif(btrim(condition), '') is null
        or (
            grading_company is null
            and grade is null
            and certificate_number is null
            and seal_status is null
        )
    )
    and (
        seal_status is null
        or (
            nullif(btrim(condition), '') is null
            and grading_company is null
            and grade is null
            and certificate_number is null
        )
    )
);
