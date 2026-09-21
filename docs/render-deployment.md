# Deploy NEXORA from GitHub to Render

Status: prepared configuration, not a deployed or release-approved service.

The root `render.yaml` uses the existing Dockerfile and Supabase database. It
selects the release branch explicitly, Singapore, and a free web service. Automatic
deploys are disabled so a later branch push cannot silently change the running
application. Applying a Blueprint still starts its initial deployment. Do not apply
it against the existing database until the migration and data review is complete.

## Account and service

1. Sign in at <https://dashboard.render.com/> using the owner's account. The owner
   completes any new account terms and authorizes only the intended repository if
   GitHub access is requested.
2. Create a Blueprint from `EAKAPOL-BDC/EdPEx-SEv1`, select
   `codex/release-2026-09-21`, and use the root `render.yaml`.
3. Review the resource plan before applying. No paid resource, Render database or
   disk is required by this configuration. A free service sleeps when idle and has
   cold starts; choose an approved paid plan separately for continuous availability.
4. Set the prompted variables through Render's private Environment settings:

   | Variable | Value |
   | --- | --- |
   | `DJANGO_SECRET_KEY` | A private random secret of at least 50 characters; generate locally or in a password manager. |
   | `SUPABASE_DEV_DB_HOST` | Session pooler host from the selected project's Connect panel. |
   | `SUPABASE_DEV_DB_USER` | Session pooler username from that panel. |
   | `SUPABASE_DEV_DB_PASSWORD` | The database password, entered privately; never a Supabase API key. |

   The Blueprint supplies session port `5432` and database `postgres`; verify both
   against the connection panel. The legacy `SUPABASE_DEV_` variable names also
   serve production. Do not paste secrets into GitHub, issue comments or chat.
   Render's Blueprint `generateValue` creates a 44-character base64 value, shorter
   than this application's minimum, so this configuration prompts for the secret.

5. `DJANGO_SETTINGS_MODULE=edpex.render` uses Render's own assigned hostname and
   HTTPS URL, validates that they match, and retains all production security checks.
   For a custom domain, set both `DJANGO_ALLOWED_HOSTS` and `NEXORA_PUBLIC_ORIGIN`
   explicitly. Verify Render's assigned service hostname before the first working deployment;
   a name such as `nexora-edpex` does not guarantee a particular available URL.
   Render terminates HTTPS and passes the scheme to Gunicorn. The trusted proxy
   setting is specific to this hosted deployment, not a development server.

## Database and release gates

The existing Supabase project contains earlier data and an older schema. Preserve
it and its backup. Startup deliberately does not run `migrate`, `flush`, `seed` or
an import. Review and rehearse forward migrations and the approved 61-configuration
import separately. No deletion or overwrite is authorized by this configuration.

The complete regression suite has not passed. The local run completed with
34 failures and 37 errors; the GitHub run for commit `3aeff38f` also failed at the
full Django test step. Dependency installation, static collection, system checks,
schema creation and migration checks passed in that GitHub run. Seven focused
REAL/LIVE collection tests passed locally. These results do not certify release.

Keep the four participation flags disabled until the full release checks,
selected data import and endpoint tests pass. The owner has confirmed F01 academic
year 2568, 1 June 2025 through 31 May 2026 inclusive; collection windows stay unchanged.
Enable the flags deliberately in Render after those gates are resolved. Review
Blueprint values at the same time so a later Blueprint sync does not revert them.

## Verify the actual website

- Render build and deployment are successful at the intended commit.
- HTTPS `/health/live/` and `/health/ready/` return 200 without redirect loops.
- The homepage, login, versioned static assets and protected workspace load.
- Authorized login, permissions, all six survey workflows, conditional questions,
  submission and receipt verification pass against approved isolated test fixtures.
- Only the approved data is presented for real collection; previous test data and
  responses remain preserved and excluded.

The ready endpoint only checks basic database availability. It does not certify
that migrations or the business workflows are ready. Record the tested HTTPS URL
and deployed commit before telling users that the site is live.

References: [Django deployment](https://render.com/docs/deploy-django),
[Blueprint configuration](https://render.com/docs/blueprint-spec), and
[free service limits](https://render.com/docs/free).
