# F01 connected test interface

The approved revision 03.1 layout is shared by the standalone preview and the
connected F01 C1 page. `/survey/participation/form/` reads both languages from the
binding's reviewed, published translation bundle. It never uses the standalone
builder's draft wording as a publication fallback. The public adapter exposes
only question text, choices, answer statuses and supported visibility rules;
fixed context remains server-owned. This increment is **test-realm only**.

When the feature is enabled, entry through the existing invitation page redirects
eligible F01 C1 invitations with a test receipt policy to the connected page.
Other forms retain their existing route. A live policy cannot open this new page.
The existing invitation-to-roster relationship is unchanged; this is not a claim
of complete anonymity or completed PDPA compliance.

## Submit and recovery

The browser validates every visible question except optional suggestions, then
converts choices into the backend's status/value envelopes. The server performs
its own validation. Prepare delivers a random candidate; the browser retains only
the candidate token and retention timestamp in sessionStorage (up to 24 hours).
It does not store answers, tickets, invitation IDs or session secrets there.
If browser storage is unavailable, submission is not attempted.

Only a committed `issued` result displays a receipt. Duplicate clicks are blocked.
After an uncertain acknowledgement, the interface disables editing and resubmission
and offers an explicit status check. `not_confirmed` is deliberately inconclusive:
it never triggers a replacement submission. Known pre-commit validation failures
allow correction. Closing the tab can lose the recovery token; retain/download the
receipt once available. Recovery across browsers/devices requires possession of
the saved token. A fresh invitation in the same tab first requires resolving the
old recovery token or explicitly clearing it on the holder page.

`/survey/participation/receipt/` accepts a pasted token or a QR URL fragment. It
scrubs the fragment from the address bar before a user-initiated POST, displays
status without answers or scores, and offers PNG download for an issued test proof.
Checking never redeems a proof. It does not assert prize eligibility or credits.
No verifier API keys are embedded in the page.

QR generation is local: POST `/survey/participation/qr/`, CSRF protected, requires
an issued test proof. A vendored, MIT-licensed ReportLab QR encoder creates the SVG
with four-module quiet zones and M error correction. No QR service receives tokens.
The QR contains a first-party verification URL with the bearer token in its fragment.
Loopback development URLs work only on the machine running the service, not a phone.

Pages have nonce-based CSP, no-store/private caching, same-origin referrers and noindex.
Cross-origin referrers are suppressed; same-origin form origins are preserved for
CSRF-protected attachment downloads. URL fragments never enter referrers.
API responses retain their stricter CSP and rate limits. A CSRF-protected ordinary
POST to `/survey/participation/download/` provides a real SVG attachment as an
alternative for browsers that do not save canvas/Blob PNG downloads. Recovery tokens are
bearer credentials; anyone holding one can inspect its limited public metadata.

## Isolated local demonstration

`edpex.participation_demo` refuses anything except database `edpex_m1_f01_ui` on
loopback PostgreSQL port 55469. It extends guarded testing settings, enables only
test participation, and uses separate cookie names to avoid the user's application
cookies on port 8000. Never deploy these settings. `/demo/` exists only in this
development URLconf and permits only loopback clients to request one of five
synthetic invitations. It does not appear in normal application URLs.

Initialize a fresh empty database, migrate **that database only**, then run
`python -B scripts/seed_f01_ui_demo.py`. This script rejects non-empty user tables,
creates synthetic collection data through the test fixture, and does not export
raw invitation secrets. Fixture-approved translations are for synthetic development
verification, not an institutional or professional approval for real use.

Start with `python -B manage.py runserver 127.0.0.1:8767 --noreload
--settings=edpex.participation_demo` using the documented dedicated database env.
The development cluster and app must be running for the demo or its receipts.
Do not re-run seed, refresh the user's workspace, or migrate any live database.

Production invitation/identity separation, retention, operator controls, workload
and reward consumers, approved real wording, and mobile-device QR verification
remain separate rollout work.
