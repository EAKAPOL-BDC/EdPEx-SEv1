# Anonymous survey web contract

This increment serves HTML forms. It does not advertise a new JSON API. All POST forms use Django CSRF protection. The staff login is separate from the survey cookie.

| Route | Methods | Access / purpose |
|---|---|---|
| `/survey/` | GET, POST | Enter an invitation code in the POST body. Never put a code in a query string. |
| `/survey/answer/` | GET, POST | HttpOnly anonymous session; read pinned questions, save a transient draft or submit once. `lang=th` / `lang=en` selects reviewed wording. |
| `/workspace/{scope}/surveys/` | GET | Scoped round manager, analyst, submitter or reviewer; list rounds. |
| `/workspace/{scope}/surveys/new/` | GET, POST | `round.manage`; create a draft with one context/group/unit. |
| `/workspace/{scope}/surveys/{binding}/` | GET, POST | Scoped workflow; only `round.manage` may edit/open/close. Eligibility rows additionally require `population.manage`. |
| `/workspace/{scope}/surveys/{binding}/invite/{member}/` | GET, POST | Both `round.manage` and `population.manage`; issue/reissue/revoke, with explicit confirmation. |
| `/workspace/{scope}/surveys/{binding}/calculate/` | GET, POST | `calculation.run`; preview, then commit a signed, actor-bound source snapshot. |
| `/workspace/{scope}/results/{run}/` | GET, POST | Existing permission-checked submission, aggregate review and independent approval. |

Anonymous submission fields: `revision` integer, `action=draft|submit`, published question IDs, `confirm=on` for submission, and CSRF token. Scalar choices use `value:{code}`; NA/unable states use `state:{status}`. Multiselects repeat the question ID. Text is capped at 500 characters. F02-P04 has an optional `F02-P04-month` field required when choosing `month_year`. Visibility and fixed group/context are resolved on the server. Follow-up questions are updated on save-and-continue.

Responses: 200 HTML, 302 redirect after access/draft save; 400 for unsupported insecure hosts; 403 CSRF/permission; 404 scoped object absent; 405 method; 409 expired/used/revoked session, closed window or stale draft; 422 invalid form; 429 after 20 access attempts per keyed client bucket in ten minutes; 503 generic anonymous-path failure. Anonymous failures never render DEBUG tracebacks. No scores, answer keys, eligibility IDs or submission lookup links are returned to respondents. A submitted receipt is a random response UUID without a retrieval endpoint.

The response table has no identity/token/session foreign key. Temporary draft sessions do refer to invitations and must be purged after expiry. Register rows have no per-person submission timestamp. SQL guards keep survey context frozen after draft and responses append-only. Deferred constraints enforce equality of spent invitations and responses per binding at commit. Application services lock round, invitation, then session; submission writes are atomic. Database superusers remain a privileged boundary, so do not claim absolute unlinkability.

The numeric adapter includes every applicable stored series and fixed leadership role, uses response UUIDs as anonymous units, and does not join submitted answers to PopulationMember. Free text and multichoice fields are not numeric formula sources. Review retains the existing n<5 suppression and repeated-generation restriction. Raw comments are not exposed by this increment. A public result-release policy and redacted-comment workflow remain separate work.
# Reporting-period navigation

The shared reporting-period form accepts an optional hidden `return_to` choice: `survey`, `f06`, or empty. The corresponding creation-page link supplies it in the query string, and the form retains it on POST/validation errors. Successful creation returns to the same intake type with `?period=<approved-period-id>`; a direct entry returns to the round list. No arbitrary return URL is accepted. Period choices remain restricted to approved periods in the current scope.
