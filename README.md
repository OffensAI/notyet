# notyet

AWS IAM eventual consistency persistence tool. Exploits the ~4 second IAM propagation window to maintain access after defenders revoke credentials or modify policies.

**By OFFENSAI Inc. | Eduard Agavriloae (saw_your_packet)**

**For authorized security testing only. Unauthorized use may violate applicable laws.**

## What it does

When running, notyet monitors the compromised identity and reacts to defender actions in real-time:

- **Credential rotation** -- detects deleted/disabled access keys and rotates to new credentials before the consistency window closes
- **User recreation** -- if the IAM user is deleted, recreates it with the same name and fresh access keys
- **Role rotation** -- for temporary (ASIA) credentials, creates and assumes new roles on revocation
- **Policy persistence** -- attaches an admin inline policy and continuously restores it if removed
- **Policy stripping** -- removes managed policies, other inline policies, and permission boundaries added by defenders

Health checks run every 5 seconds (S3 ListBuckets). Policy monitoring runs every 1 second.

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
