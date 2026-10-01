-- A grading certificate identifies one physical encapsulated card.
-- Prevent duplicate physical inventory from being created by retries, QR scans,
-- or a second owner account using the same grader + certificate.
create unique index if not exists inventory_items_grader_certificate_unique
on tcg.inventory_items (
    upper(btrim(grading_company)),
    regexp_replace(btrim(certificate_number), '[[:space:]-]+', '', 'g')
)
where grading_company is not null
  and certificate_number is not null
  and btrim(certificate_number) <> '';
