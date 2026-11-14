# Shared memory — firetrace + authenticated Engram Cloud

**Decision:** use project **firetrace** and Cloud transport. Keep old memory projects untouched; no migration/deletion is required. Do not export or commit memory chunks. `.engram/config.json` selects identity only: it does not deploy, configure credentials, enroll a client or authorize remote access.

Teammates connecting an enrolled client can follow the [user guide](ENGRAM_CLOUD_USER.md).

**Operational status:** this is an operator recipe, not a deployed/tested server. Remote execution requires explicit destination, operation and credential/session authorization. Never inspect ambient SSH/session access to infer permission.

## Operator: isolated server configuration

Use the official [quickstart](https://github.com/Gentleman-Programming/engram/blob/main/docs/engram-cloud/quickstart.md), [runtime reference](https://github.com/Gentleman-Programming/engram/blob/main/DOCS.md) and [production checklist](https://github.com/Gentleman-Programming/engram/blob/main/docs/engram-cloud/production-checklist.md). The verified stable release as of 2026-11-14 is **[v3.7.2](https://github.com/Gentleman-Programming/engram/releases/tag/v3.7.2)**; the upstream quickstart/Compose still show v2.0.0. Select the reviewed published image explicitly; do not blindly deploy those older defaults or `latest`.

On the authorized server, keep a Compose file and protected `.env` **outside this application repository**, for example in `/opt/engram/`. The following is documentation only; no infrastructure files are added here.

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: engram
      POSTGRES_DB: engram_cloud
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - engram-cloud-pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U engram -d engram_cloud"]
      interval: 10s
      timeout: 5s
      retries: 10
  cloud:
    image: ghcr.io/gentleman-programming/engram:v3.7.2
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    env_file: .env
    ports:
      - "127.0.0.1:18080:18080"
volumes:
  engram-cloud-pg:
```

The named PostgreSQL volume persists data; **no database port is published**. Bind Cloud only to loopback and route an existing HTTPS reverse proxy to it. Complete TLS/proxy/firewall review before use; do not expose port 18080 publicly. Never enable `ENGRAM_CLOUD_INSECURE_NO_AUTH` for this team service.

Populate the server-only `.env` from a secret manager, with independent strong secrets; these placeholders are not usable values:

```dotenv
POSTGRES_PASSWORD=REPLACE_WITH_DATABASE_SECRET
ENGRAM_DATABASE_URL=postgres://engram:REPLACE_WITH_URL_ENCODED_DATABASE_SECRET@postgres:5432/engram_cloud?sslmode=disable
ENGRAM_CLOUD_TOKEN=REPLACE_WITH_OPERATOR_ONLY_COMPATIBILITY_SECRET
ENGRAM_JWT_SECRET=REPLACE_WITH_INDEPENDENT_32_BYTE_OR_LONGER_SECRET
ENGRAM_CLOUD_TOKEN_PEPPER=REPLACE_WITH_INDEPENDENT_TOKEN_PEPPER
ENGRAM_CLOUD_ALLOWED_PROJECTS=firetrace
ENGRAM_CLOUD_HOST=0.0.0.0
ENGRAM_PORT=18080
```

`sslmode=disable` here applies only to the isolated Compose database network, not public client traffic. Keep database credentials consistent; percent-encode reserved password characters in the URL, not the literal PostgreSQL password. Changing initialization variables does not update an existing volume's database credentials. A `pg_isready` success does not prove Engram's runtime connection credentials work.

`ENGRAM_CLOUD_TOKEN` is a server-startup compatibility credential, not a shared team token. Keep it operator-only. The pepper must be present on both token issuance **and the long-lived Cloud server**, using the same secret; without it managed-token authentication is not enabled. Keep JWT, pepper and database secrets distinct. Legacy static admin credentials do not provide managed-user mutation authority.

## Operator: start and create managed users

Only after authorization, from the protected server configuration directory:

```sh
docker compose up -d
docker compose exec -T cloud engram cloud bootstrap admin --username <admin> --grant-project firetrace --issue-token admin-bootstrap
```

Replace `<admin>` before executing. Initialization runs database migrations. Bootstrap creates the first managed admin; the raw token is shown **once**, so capture it directly into a secret manager, not logs, chat or Git. A repeated bootstrap is refused once an admin exists; follow official recovery guidance rather than deleting state.

Use HTTPS `/dashboard/login` with that managed admin, then `/dashboard/admin/users` to create individual members, project grants and personal tokens. Do not invent a `cloud users` CLI or distribute the bootstrap/admin/static compatibility token to teammates.

Set the environment allowlist to `firetrace` and managed user grants to the same intended project. These are separate authorization mechanisms: **do not treat the environment allowlist as a ceiling on managed grants**. Review each principal's grants, token expiry/revocation and HTTPS access explicitly.

Verify the server health endpoint, authenticated dashboard and an authorized client's sync/status before declaring service ready. No such deployment or verification has been performed by this foundation.

## Contributor: configure and enroll explicitly

Install/configure Engram and your coding agent separately, only with permission. [Agent setup](https://github.com/Gentleman-Programming/engram/blob/main/docs/AGENT-SETUP.md) documents `engram setup opencode`, which configures the plugin/global MCP but **not Cloud**.

With an approved endpoint and **your individual project token** supplied through a secret manager/environment:

```sh
engram cloud config --server https://<domain>
# Supply your personal ENGRAM_CLOUD_TOKEN to the process; do not paste it here.
engram cloud enroll firetrace
engram sync --cloud --import --project firetrace
engram sync --cloud --status --project firetrace
```

Replace `<domain>` with the authorized HTTPS host. To publish allowed new findings and retrieve updates explicitly:

```sh
engram sync --cloud --project firetrace
engram sync --cloud --import --project firetrace
```

No bare `engram sync` Git-export workflow is selected. Do not commit `.engram/` chunks or copy older project memories. Never delete a local SQLite database to switch identities.

Autosync is opt-in: `ENGRAM_CLOUD_SERVER=https://<domain>`, `ENGRAM_CLOUD_AUTOSYNC=1` and your own `ENGRAM_CLOUD_TOKEN` must reach the **actual long-lived MCP/serve process**. New shell exports do not update an already-running Desktop/agent process; configure its launcher and restart it. Keep tokens out of committed agent settings. On PowerShell use session/launcher environment configuration, not token-bearing scripts.

## Verify teamwork and protect memory

Use a harmless, explicitly approved reusable convention: contributor A saves/syncs it; B imports and retrieves the same `firetrace` observation, then repeat in the other direction. Confirm both can run local repository checks. Until this succeeds, report synchronization as unverified; do not infer it from configuration.

Store only grounded, reusable English findings with **What / Why / Where / Learned**, source context and honest approval/implementation status. Git contracts/docs/code outrank memory. Do not upload credentials, private paths, sensitive payloads, raw data, full transcripts or speculation.

**Privacy:** an enrolled project's sync can include observations marked `scope: personal`. That scope is not a privacy boundary; keep all private notes out of `firetrace`.

## Updates, backup and fallback

Before any upgrade, record effective image/client versions, read migration notes and back up **PostgreSQL plus pepper/JWT/operator/database secrets**. Test restoration under the operator's separate authorization. Losing the pepper breaks managed-token authentication. Image rollback alone may not reverse database migrations.

For a reviewed image update, change the effective image reference, then `docker compose pull cloud` and `docker compose up -d cloud`; a restart alone does not select a changed image. Verify health, login and project sync afterward. Local SQLite upgrade rollback is not container/database rollback.

If Cloud is unavailable, continue with accepted Git docs and local memory while reporting sync unavailable. Do not silently switch to committed memory exports or expose an unauthenticated service. Any transport change needs a new explicit team decision.
