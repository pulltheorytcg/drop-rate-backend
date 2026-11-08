# CBCS comic identity support

Visible CBCS labels were rejected by the book scanner, the existing comic form
offered CGC only, and exact comic comparable eligibility excluded CBCS. Permit
CBCS alongside CGC for comics, while keeping manga limited to CGC/BGS.

The same existing grader selector receives the additional option. Layout,
navigation, styling and components are unchanged. Its asset revision changes
so existing browsers receive the updated option list.

Visible labels still require human review; recognition never authenticates a
certificate, saves inventory automatically or invents a price. Unsupported or
unknown-category labels now clear orphan grades/certificate numbers. Grader
codes are normalized to uppercase. Category changes retain the existing reset
behavior when a grader is no longer eligible.

Pricing still requires the exact company, numerical grade, printing, language
and cover. Raw, CGC, other CBCS grades, signed and restored copies cannot enter a
CBCS ordinary-comic pool. No certificate lookup integration is added, and external
grading-reference images are not granted commercial publishing rights. Real slab
photography requirements remain in force.

103 targeted Python tests passed locally. The existing actual-form Chromium/WebKit
fixture test now checks CBCS submission and identical idempotent retries at phone
and desktop widths, plus manga restrictions/reset behavior. Local browser startup
was blocked by macOS sandbox Mach-port permissions; CI browser results must be
recorded before release. Fixture API tests are not physical-iPhone proof.

No database migration or historical-price rewrite. After CI/review, verify a
non-saving live comic form and authorized exact-comparable preview. Revert/redeploy
to roll back; existing valid CBCS inventory must not be deleted or relabelled.
