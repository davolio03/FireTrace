# Connect to Engram Cloud

Use this guide after the administrator has created your managed user, granted
access to `firetrace`, and issued your **individual** token. Never use an
administrator's token or put a token in chat, Git, shell history, or logs.

## 1. Check access

You need Tailscale access to `tail8ddc4a.ts.net`, the Engram CLI, Python 3 and a
local FireTrace checkout. Engram 3.6.0 supports manual sync; 3.7.2 or newer is
recommended for current autosync behavior.

```sh
tailscale status
curl -4 -sS https://andriudevserver.tail8ddc4a.ts.net/health
engram --version
```

The health endpoint should return `{"service":"engram-cloud","status":"ok"}`.
It is available only on the tailnet. A successful health check does not prove
that your token or project access works.

## 2. Configure your personal client

Run these commands as the same operating-system user and with the same
`ENGRAM_DATA_DIR` used by your agent. The default is `~/.engram`.

```sh
engram cloud config --server https://andriudevserver.tail8ddc4a.ts.net
python3 - <<'PY'
import getpass
import json
import os
from pathlib import Path

directory = Path(os.environ.get("ENGRAM_DATA_DIR") or Path.home() / ".engram")
path = directory / "cloud.json"
config = json.loads(path.read_text()) if path.exists() else {}
token = getpass.getpass("Personal Engram token: ").strip()
if not token:
    raise SystemExit("No token provided; nothing changed.")
config["server_url"] = "https://andriudevserver.tail8ddc4a.ts.net"
config["token"] = token
directory.mkdir(parents=True, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w") as file:
    file.write(json.dumps(config, indent=2) + "\n")
print("Cloud client configuration saved with mode 600.")
PY
engram cloud status
```

The token prompt does not echo input. Confirm that the server source is
`cloud.json` and authentication is ready. An `ENGRAM_CLOUD_TOKEN` environment
variable takes precedence over the file; remove unintended overrides from the
agent's environment. A local daemon status alone does not prove cloud sync.

## 3. Enroll and synchronize

In the FireTrace checkout, enroll the project and inspect synchronization:

```sh
engram cloud enroll firetrace
engram sync --cloud --status --project firetrace
```

When you intend to exchange the project's shared memories, import first, then
push local changes and check the result:

```sh
engram sync --cloud --import --project firetrace
engram sync --cloud --project firetrace
engram sync --cloud --status --project firetrace
```

Import and push change local or remote state; inspect the project and obtain
appropriate authorization before running them. Check `Pending import` rather
than assuming a successful connection means data is synchronized. Do not use
`--all`, Git memory exports, or commit `.engram` memory chunks.

## 4. Enable and verify autosync

Autosync runs in the **long-lived Engram MCP or serve process**, not in the
shell where you happen to set a variable. For OpenCode, add this environment
entry to the existing `engram` MCP configuration without replacing its command
or other settings:

```json
{
  "mcp": {
    "engram": {
      "environment": {
        "ENGRAM_CLOUD_AUTOSYNC": "1"
      }
    }
  }
}
```

Restart the agent or its MCP process to apply the change. Keep the token in
`cloud.json`, not in the agent configuration. The value must be exactly `1`.
The MCP/server logs should show `[autosync] started`; that line alone does not
prove end-to-end replication.

To verify replication, agree on a harmless shared observation, save it from one
enrolled client, and confirm another enrolled client can import and retrieve it.
Allow about 30 seconds for autosync. Perform the import and test write only
with authorization, and never use a private note as the test.

## Troubleshooting and privacy

| Symptom | Next check |
| --- | --- |
| Health endpoint unreachable | Check Tailscale and use `curl -4`. |
| `401` / `auth_required` | Ask the administrator to check or rotate your personal token. |
| `403` / `policy_forbidden` | Ask for the `firetrace` project grant. |
| Autosync does not start | Check the actual MCP process environment and restart it. |
| Sync remains degraded | Check the MCP logs for transport or backoff errors and verify the server. |
| Wrong configuration | Check the agent's user and `ENGRAM_DATA_DIR`. |

All `firetrace` observations can be shared, including those marked personal.
Do not store credentials, private notes, raw data, or sensitive payloads there.
For server administration and the project's operating boundaries, see
[ENGRAM_CLOUD.md](ENGRAM_CLOUD.md).
