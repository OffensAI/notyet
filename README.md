# notyet

AWS IAM eventual consistency persistence tool. Exploits the ~4 second IAM propagation window to maintain access after defenders revoke credentials or modify policies.

**By Eduard Agavriloae (saw_your_packet)**

**For authorized security testing only. Unauthorized use may violate applicable laws.**

## What it does

When running, notyet monitors the compromised identity and reacts to defender actions in real-time:

- **Credential rotation** -- detects deleted/disabled access keys and rotates to a new user with a random name before the consistency window closes
- **User deletion recovery** -- if the IAM user is deleted, detects via `GetUser` and creates a fresh user with new credentials
- **Role deletion recovery** -- if the IAM role is deleted, detects via `GetRole` and creates a new role with fresh session credentials
- **Role session refresh** -- proactively rotates role sessions before expiry (5 min buffer), and reactively handles `ExpiredToken` errors
- **Policy persistence** -- attaches an admin inline policy and continuously restores it if removed or modified (validates policy content, not just name)
- **Policy stripping** -- removes managed policies, other inline policies, and permission boundaries added by defenders
- **Group membership removal** -- detects when the user is added to IAM groups (e.g., with deny policies) and removes the membership

Health checks run every 5 seconds (S3 ListBuckets). Policy monitoring runs every 0.5 seconds.

### Persistence matrix

| Defender Action | Access Key (AKIA) | Role Session (ASIA) |
|---|:---:|:---:|
| Disable access key | Survives | N/A |
| Delete access key | Survives | N/A |
| Delete user | Survives | N/A |
| Delete role | N/A | Survives |
| Session expiry | N/A | Survives (proactive refresh) |
| Add inline deny policy | Survives | Survives |
| Attach managed deny policy | Survives | Survives |
| Add permission boundary | Survives | Survives |
| Modify notyet policy (Allow→Deny) | Survives | Survives |
| Add user to group with deny | Survives | N/A |
| Delete notyet inline policy | Survives | Survives |
| Service Control Policy (SCP) | **Blocked** | **Blocked** |

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd notyet
uv sync
```

## CLI Usage

```bash
# Using an AWS profile
uv run notyet --profile <source-profile> --output-profile <output-profile>

# Using explicit credentials
uv run notyet --access-key-id AKIA... --secret-access-key ... --output-profile <output-profile>

# With temporary credentials
uv run notyet --access-key-id ASIA... --secret-access-key ... --session-token ... --output-profile <output-profile>
```

### Flags

| Flag | Description |
|------|-------------|
| `--profile` | AWS profile to use for initial credentials |
| `--access-key-id` | AWS access key ID (alternative to `--profile`) |
| `--secret-access-key` | AWS secret access key |
| `--session-token` | AWS session token (for temporary credentials) |
| `--output-profile` | Profile name where rotated credentials are written (required) |
| `--exit-on-access-denied` | Stop when access is fully revoked (default: keep running) |
| `--json-output` | Output structured JSON events (used by the web UI) |
| `--confirm-run` | Skip the interactive confirmation prompt |
| `--debug` | Enable debug logging |

### Cleanup

Remove all `notyet-*` IAM resources from the account:

```bash
uv run notyet cleanup --profile <profile>
```

## MCP Server (WIP)

notyet can run as an MCP server, exposing persistence techniques as callable tools:

```bash
uv run notyet --mcp-server
```

This mode is a work in progress.

## Web UI

A web interface is included in `backend/` and `frontend/`. It wraps the CLI tool via subprocess and provides real-time monitoring through WebSockets.

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your browser.

## License

MIT -- see [LICENSE](LICENSE).
