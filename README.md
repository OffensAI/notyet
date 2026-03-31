# notyet

AWS IAM eventual consistency persistence tool.

notyet exploits the eventual consistency model in AWS IAM to maintain persistent access after defenders revoke credentials or modify policies. IAM changes -- key deletion, policy detachment, role removal -- take up to several seconds to propagate globally. notyet uses this propagation window to automatically rotate credentials and restore permissions faster than AWS can enforce revocation.

Designed for authorized penetration testers, red teamers, and security researchers who need to demonstrate the real-world impact of IAM eventual consistency weaknesses.

**By Eduard Agavriloae (saw_your_packet)**

## How it works

1. notyet accepts compromised AWS credentials (via an AWS CLI profile or passed directly as flags).
2. It identifies the credential type -- persistent access keys (`AKIA*`) or temporary session credentials (`ASIA*`) -- and selects the appropriate persistence strategy.
3. An administrative inline policy (`notyet-*`) is attached to the compromised identity.
4. Two concurrent monitoring loops start:
   - **Health check loop** (every 5 seconds) -- calls `S3:ListBuckets` to detect access revocation.
   - **Policy monitor loop** (every 0.5 seconds) -- ensures the `notyet-*` admin policy remains attached and strips any competing policies applied by defenders.
5. When the health check detects that access has been revoked, notyet triggers automatic credential rotation using the selected persistence strategy.
6. New credentials are written to the configured output AWS CLI profile, and monitoring resumes.

All IAM resources created during a session are tracked in a local state file (`~/.notyet/resources.json`) for reliable cleanup and audit trails.

### What it survives

When running, notyet monitors the compromised identity and reacts to defender actions in real time:

- **Access key disabled/deleted** -- Creates a temporary IAM user with admin privileges, assumes a bridging role, recreates the original user with fresh access keys, and resumes operations within the consistency window.
- **User deleted** -- Detects via `GetUser` and creates a fresh user with new credentials.
- **Role deleted** -- Creates new IAM roles with same-account trust policies and assumes them before the revocation propagates.
- **Session expiry** -- Proactively rotates role sessions before expiry (5 min buffer) and reactively handles `ExpiredToken` errors.
- **Inline/managed deny policies added** -- The policy monitor detects and removes competing managed policies, inline policies, and permission boundaries.
- **notyet policy modified or deleted** -- Validates policy content (not just name) and restores it if tampered with.
- **User added to group with deny** -- Detects group membership changes and removes the membership.

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
| Modify notyet policy (Allow to Deny) | Survives | Survives |
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

Verify the installation:

```bash
uv run notyet --help
```

## Usage

### Providing credentials

There are two ways to provide the compromised AWS credentials:

**Using an AWS CLI profile:**

```bash
uv run notyet --profile <source-profile> --output-profile <output-profile>
```

**Using explicit credentials (long-lived):**

```bash
uv run notyet \
  --access-key-id AKIAIOSFODNN7EXAMPLE \
  --secret-access-key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY \
  --output-profile notyet-output
```

**Using explicit credentials (temporary/session):**

```bash
uv run notyet \
  --access-key-id ASIAIEXAMPLE \
  --secret-access-key wJalrXUtnFEMI/EXAMPLEKEY \
  --session-token FwoGZXIvYXdzEBAaDH... \
  --output-profile notyet-output
```

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--profile` | No* | AWS CLI profile to use for initial credentials |
| `--access-key-id` | No* | AWS access key ID (alternative to `--profile`) |
| `--secret-access-key` | No* | AWS secret access key (used with `--access-key-id`) |
| `--session-token` | No | AWS session token (required for temporary `ASIA*` credentials) |
| `--output-profile` | **Yes** | AWS CLI profile name where rotated credentials are written |
| `--exit-on-access-denied` | No | Stop when access is fully and permanently revoked (default: keep retrying) |
| `--json-output` | No | Output structured JSON events instead of human-readable text |
| `--confirm-run` | No | Skip the interactive confirmation prompt |
| `--debug` | No | Enable debug-level logging |

\*Either `--profile` or `--access-key-id`/`--secret-access-key` must be provided.

### Examples

Basic persistence test with a named profile:

```bash
uv run notyet --profile compromised --output-profile notyet-output

# In another terminal, use the rotated credentials
aws s3 ls --profile notyet-output
```

Automated run (no confirmation prompt), exit when access is permanently revoked:

```bash
uv run notyet \
  --profile compromised \
  --output-profile notyet-output \
  --exit-on-access-denied \
  --confirm-run
```

JSON output for integration with other tools:

```bash
uv run notyet \
  --profile compromised \
  --output-profile notyet-output \
  --json-output \
  --confirm-run > session.json
```

### Cleanup

After testing, remove all `notyet-*` IAM resources (users, roles, policies) from the account:

```bash
uv run notyet cleanup --profile <profile>
```

The cleanup command scans for all `notyet-*` prefixed resources and prompts for confirmation before deleting them. Resources are also tracked in `~/.notyet/resources.json` during sessions for reliable cleanup.

### Graceful shutdown

Pressing Ctrl+C stops the tool cleanly: monitoring loops are halted, in-progress operations complete, state is saved, and a session summary with statistics is displayed.

## Web UI

notyet includes a web interface designed primarily as a training and awareness tool for blue teams and incident responders. It wraps the CLI tool via subprocess and streams events over WebSocket, giving defenders an interactive view of how eventual consistency abuse plays out in practice.

The dashboard provides a split-view layout:

- **Defender Actions** (red) -- credential revocations, policy changes, permission boundary attachments as they are detected.
- **Attacker Responses** (green) -- credential rotations, new user/role creation, policy restoration as they execute.
- **Event Log** -- full real-time log with filtering and search.
- **Control Panel** -- start, stop, and restart sessions from the browser.
- **Session Selector** -- switch between and replay past sessions for comparison.

To run the web UI:

```bash
uv run --with-requirements backend/requirements.txt uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` in your browser.

## Acknowledgements

This tool was hardened through red-vs-blue collaboration with [Nigel Sood](https://www.linkedin.com/in/nigel-sood/), Cloud Privilege Threat Researcher at [Sonrai Security](http://sonraisecurity.com/). Nigel tested notyet from the perspective of an incident responder attempting to contain a compromised identity, providing detailed feedback on persistence gaps and edge cases that directly shaped the tool's monitoring and rotation capabilities.

## License

MIT -- see [LICENSE](LICENSE).

## Legal disclaimer

notyet is intended for **authorized security testing only**. Unauthorized access to computer systems is illegal. Always obtain written authorization before testing against any AWS account you do not own. The authors are not responsible for misuse of this tool.
