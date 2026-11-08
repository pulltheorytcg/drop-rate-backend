# Magic comparable identity repair

The shared sold comparator could accept an etched-foil listing for a plain foil
target and the same name/collector number from another set. Magic now has a
category-specific identity boundary used by both manual sold pricing and the
background exact-comparable path.

Require the exact normalized set phrase and one unambiguous supported finish:
foil, nonfoil or etched. Non-foil/non foil and foil etched/etched foil aliases
are recognized. Conflicting finishes, special foil treatments, unrecognized
finishes, signed/altered items and mismatched art/frame treatments do not enter
the ordinary comparison pool. Existing name, number, grade, language, condition,
recency, duplicate and source checks still apply.

This deliberately does not guess a premium or borrow another finish's value.
An abbreviation-only set title may be excluded until a reviewed set-ID adapter
can establish it. Signed and special-treatment strategies still need dedicated
identity evidence. This is not a complete Magic pricing strategy or a claim that
all other categories are implemented.

No UI, price expiry, provider permission, estimator, SQL schema or production
record is changed. Existing stored quotes are not rewritten by this patch.
The five-sale route remains a sold-specific route; permitted guide/active-listing
estimates are separate recovery work, not relabelled by this identity correction.

Validation: 20 failures reproduced before repair; all 118 targeted tests pass
afterward. New tests exercise both pricing entry paths, the finish cross-product,
different/missing sets, aliases, signed listings and ambiguous/special finishes.
These fixtures are not real market evidence or measured pricing accuracy.

Release after CI/review. Verify a non-mutating quote preview with authorized
evidence before permitting actual writes. Rollback is a code revert/redeploy;
no data migration or deletion is required.
