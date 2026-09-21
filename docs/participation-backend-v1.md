# Participation proofs — backend increment 01

Implemented locally on 18 September 2026. The accepted F01 UI (03.1) is unchanged.
This is working Django service/API code with PostgreSQL tests, **not a deployment**.

## Scope and default state

The new `apps.participation` app supports a policy on an anonymous F01–F04 survey
binding. F05/F06 need their own validation/policy review and are intentionally
not accepted by policy configuration yet. No hours are assigned and no prize
winner is chosen here. Redemption records that an authorized external service
used a participation proof; that service must apply its own approved workload
rules or check its draw results before calling redemption.

Both settings default to false:

- `NEXORA_PARTICIPATION_ENABLED`: gates all public proof endpoints and issuance.
- `NEXORA_PARTICIPATION_ALLOW_LIVE`: additionally gates live-realm credentials.

A test-realm proof cannot be verified/redeemed by a live-realm client. Synthetic
collections cannot be configured as live. No service clients, keys, policies or
migrations have been created on the running application or Supabase.

## Data boundary

- `ReceiptPolicy`: one immutable policy per collection binding, bilingual activity
  labels, version, test/live realm, expiry, workload/prize switches and kill switch.
- `ParticipationReceipt`: independent random UUID, policy FK, unique SHA-256 of a
  256-bit random bearer token, revocation flag. No answer/session/invitation/person
  FK, raw token or issuance timestamp.
- `VerifierClient`: service identity restricted to one scope and realm; only a
  key hash is stored, with active/expiry controls. Keys can be rotated or disabled.
- `VerifierGrant`: explicitly authorizes one client, policy and purpose, with a
  separate permission for redemption. Read access does not grant redemption.
- `ReceiptRedemption`: proof, consumer, purpose, random redemption reference and
  hash of the consumer's UUIDv4 idempotency key. No employee/student ID or hours.

Policies and histories are protected by PostgreSQL triggers; unique constraints
also enforce one redemption per proof/purpose and one use of a client/idempotency
key. The policy itself is the campaign boundary. A second client cannot create a
second use of the same proof and purpose.

Administrative creation/grant/disable/key-rotation actions are audited without
secrets. Revocation audit identifies the collection, not a particular bearer.
Submissions and verification do not create person-to-proof audit records.

**This is not cryptographically unlinkable issuance.** Proof and response writes
occur in a shared transaction/database and may be correlated through timing,
WAL, privileged access, or external logs. Existing survey invitations still refer
to PopulationMember and response records still contain precise submitted_at.
This increment does not remove those legacy identity/timing boundaries. Do not
claim whole-system anonymity or PDPA compliance from these new tables alone.

## Submission protocol

1. A respondent enters with the existing separate survey-session cookie. No staff
   login is required or consulted by the new respondent endpoints.
2. `prepare` validates the current open session/policy, creates a 256-bit random
   `NXR1-...` token, and signs a 2-hour issuance ticket with that token and policy
   ID. Nothing redeemable is written; there is no person/candidate mapping table.
3. The client retains this candidate **before** sending answers. It must label it
   pending, not successful. Preserve the same candidate across a network retry.
4. `submit` verifies the ticket, pinned policy and required answers, locks the
   round/policy, and calls the existing survey transaction. Response insertion,
   spending the invitation, deleting the session and inserting the independent
   proof either all commit or all roll back. The response UUID is discarded.
5. The result includes only the activity/policy metadata, realm, reporting year,
   instrument and expiry. It does not echo the bearer token or return an answer ID.
6. If acknowledgement is lost, `status` checks the candidate token. `issued` means
   the proof is committed; `not_confirmed` may mean in-flight, never submitted or
   rolled back. Do not tell the user to start over merely from `not_confirmed`.
7. A used/forged/expired ticket cannot mint another proof. Retrying a used survey
   session gives a conflict; use the holder-status endpoint, not a second submit.

All visible non-O questions must have a valid response on this new submission
path, including conditional follow-ups. Fixed context and hidden questions are
excluded. Explicit unable-to-assess/not-applicable answers remain valid where
allowed by the pinned schema. These count as participation, not positive scores.
The legacy analytics completion flag retains its existing meaning.

**Integration is still pending:** the old `/survey/answer/` HTML flow has not been
changed and still uses its original validation/receipt. The standalone 03.1 page
still uses its fixed DEMO QR. Do not enable collection policies for respondents
until the accepted interface is wired to this new submission path and tested.

## Endpoint contract

All requests use POST JSON. No bearer token goes in a URL. Responses are no-store,
no-referrer, noindex and contain no answer values. HTTPS is required except for
verified loopback development and the explicit testserver setting. Rate limits
reuse short-lived HMAC client buckets; raw IPs are not stored by this code. Proxy,
request-body, authorization-header and error logging must still be configured
separately before live use. Rejected requests never echo submitted secrets.

| Path | Authentication | Body |
|---|---|---|
| `/survey/participation/prepare/` | Survey cookie + CSRF | `{}` |
| `/survey/participation/submit/` | Survey cookie + CSRF | `answers`, integer `revision`, `issuance_ticket`, `confirmed: true` |
| `/survey/participation/status/` | Possession of receipt token + CSRF | `receipt_token` |
| `/participation/v1/verify/` | `Authorization: Bearer NXC1-...` | `policy_id`, `purpose`, `receipt_token` |
| `/participation/v1/redeem/` | Same + grant permitting redemption | Above plus UUIDv4 `idempotency_key` |

Machine endpoints do not accept a staff login/cookie as authorization and do not
use browser CSRF tokens as authorization. They require the explicit header key.
Unknown body fields, including `employee_id`, are rejected. Client keys never
belong in browser JavaScript or the respondent's QR.

Example verification request (placeholders only):

```json
{
  "policy_id": "<configured policy UUID>",
  "purpose": "workload",
  "receipt_token": "<holder's NXR1 bearer token>"
}
```

`verify` is read-only with respect to proof/redemption records. It returns `valid`,
`invalid`, `revoked`, `expired`, `unavailable`, `not_open` or `already_redeemed`.
It never spends a proof merely because someone scans a QR.

`redeem` returns `status: redeemed`, `redemption_reference`, `replayed` and
`current_status`. An exact authorized retry returns the original reference,
including after expiry/revocation, and marks `replayed: true`. This is history
reconciliation, not renewed eligibility. The caller must inspect `current_status`.
Reusing the same idempotency key for another proof/purpose is a conflict. Disabled
clients or revoked grants cannot retrieve historical results through that API.

For `prize`, both the declared closing time and formal closed state must be
reached. A manually closed early round does not start prize claims immediately.
The external reward service must independently confirm the winner before redeem;
this endpoint itself does not imply that the bearer has won a prize.

Errors: 401 unauthenticated; 403 wrong scope/realm/grant; 404 feature/policy
unavailable; 409 conflicts or unavailable state; 422 malformed answers/tickets or
unexpected fields; 429 rate limit; 503 sanitized transient failure. An incomplete
submission includes only `missing_question_ids` so the UI can locate the items.

## Operator service entry points

`configure_policy`, `create_client`, `grant_client`, `disable_client`,
`rotate_client_key`, `revoke_receipt` enforce existing scope permissions. Client
creation/rotation returns the raw key once to the authorized operator; store it
only in the consumer's secret store. Configuration has no new public admin page
in this increment. Policy terms cannot be rewritten after creation; enabling or
disabling does not change the policy's semantics.

Expiry makes a proof unusable, but does not delete data. An approved retention/
erasure workflow and consumer reconciliation process must be implemented before
live activation. Historical guards intentionally block ad hoc deletion.

## Validation and rollout

Run on the disposable PostgreSQL instance only, using `edpex.testing`; it refuses
Supabase and remote hosts. This increment uses port **55459**, cluster
`work/nexora-participation-pgdata`, and database `test_edpex_m1_participation`.
The old 55449 cluster could not recover promptly in this Windows sandbox, so a
fresh independent test cluster was initialized rather than changing live data.

Tests cover missing/optional/conditional answers, forged/expired candidates,
receipt-write rollback, lost acknowledgements, token privacy, scope/realm/grants,
expiry/revocation/key rotation, idempotency, HTTP CSRF/HTTPS/error boundaries,
and concurrent submissions/redemptions on separate PostgreSQL connections.
See workspace `outputs/participation-tests-final.log` for the final run results.

Next integration work:

1. Wire the accepted F01 design to prepare/submit/status, retaining the candidate
   only for the recovery window. Generate a real receipt/QR only after committed
   `issued`, with the new token rather than the response UUID or fixed DEMO code.
2. Add the first-party holder verification/download page, accessible Thai/English
   states for pending/failure/recovery, and physical-device QR scanning tests.
3. Complete invitation/identity separation, privacy/logging review, retention and
   operational administration. The existing roster-linked invitation flow must
   not be advertised as meeting the user's full no-identification requirement.
4. Integrate the workload/reward consumers with separate identity stores and
   approved policy; neither hours nor prize awards are decided by this service.
5. Review on an isolated staging collection before any live migration/activation.

