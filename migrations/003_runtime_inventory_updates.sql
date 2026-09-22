-- Allow the restricted API role to edit only operational inventory fields.
grant update (
    acquisition_cost_minor,
    acquisition_date,
    condition,
    grading_company,
    grade,
    certificate_number,
    language,
    location,
    store_price_minor,
    identity_confirmed,
    status,
    notes,
    version,
    updated_at
) on tcg.inventory_items to tcg_api;
