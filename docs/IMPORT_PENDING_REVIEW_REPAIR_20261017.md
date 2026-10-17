# Pending collection import review

The Seller Hub could choose a catalogue match and confirm language, but could
not correct an unrecognised condition, an unreadable Collectr grade, an
incomplete grading pair or a certificate without a grade. Those rows remained
in review after every confirmation. Closing the dialog also retained the file
control, column mappings and hidden result totals in the mounted DOM.

The existing owner-only confirmation route now accepts an optional, explicitly
selected card-detail correction. The review opens that section for these four
physical-data issues. A collector chooses ungraded/graded, their raw condition
(including explicitly unassessed), or the slab label's company, grade and
optional certificate. Incomplete or contradictory grading is rejected. One
certificate cannot be applied to multiple copies. The same physical-state
validator used elsewhere enforces the condition/grade separation.

Only those four physical-data issues are cleared. Quantity and purchase-cost
errors, language conflicts and Collectr quantity decreases keep their existing
review rules. A selected canonical identity is still required. Source CSV data
and Collectr snapshot keys remain unchanged; corrections apply to the pending
copy fields, not historical stock or the shared catalogue. Existing owner
checks, transaction locks, versions and duplicate protections remain in place.
Saved copies remain personal-collection Drafts without identity/media approval.
No migration, new provider/service, market-price change or Shopify action.

Closing, signing out and leaving Inventory clear upload contents, file inputs,
default selections, mappings, results and history. Account/request generations
still reject late completions. Editing a catalogue query immediately removes
its old choices; late responses or detached buttons cannot confirm old results.
Review controls have bounded mobile widths and validation failures retain a
specific actionable message where the server supplies one. The dialog declares
a light native-control palette so Safari dropdowns retain readable contrast.

Verification includes local Python and DOM checks, plus the existing CI job's
real PostgreSQL/RLS, signed HTTP and production physical-state constraints.
New cases reproduce the old dead end, correct raw/slab fields, reject foreign
owners and duplicate certificates, retain original CSV evidence, replay without
extra stock and reconcile a Collectr increase as exactly one new copy. Actual
Chromium/WebKit fixtures cover the review controls at 320–1440 px, required
grading input and file clearing after close. CI/deployment/live readback must
pass before declaring this release live. Local and CI database/browser checks
passed; initial fixture failures were corrected by isolating the Collectr
snapshot account from unrelated generic history and scoping browser label
selectors to the import dialog. Visual inspection then found Safari's dark
native-select palette, corrected explicitly without changing field behaviour.
Final verification and release receipts are tracked in
[PR #681](https://github.com/pulltheorytcg/drop-rate-backend/pull/681).
No real customer CSV or inventory is submitted as a release test.

Rollback: revert this code release to the prior successful API deployment.
No database migration or production data rewrite is needed.
