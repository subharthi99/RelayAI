# Core audit remediation — 0.5.0

The 2026-10-24 audit identified execution, policy, privacy, validation, and test
coverage issues. Version 0.5.0 implements the following remediations.

| Audit finding | Remediation | Regression coverage |
| --- | --- | --- |
| Concurrent dispatch repeats actions | Claim before awaiting; atomic persisted snapshot comparison; reject stale in-memory copies | Concurrent dispatch, stale copies, persistent competing claims |
| Confirmation cannot resume | Resume pending destinations; preserve completed/failed receipts; CLI `--resume-run` | Mixed passive/approved actions, persisted preview resume |
| String metadata bypasses policy | Validate enum metadata and bind reviewed configuration | String rejection, changed prepared content/configuration |
| File symlink race | Descriptor traversal with no-follow flags; atomic overwrite; exclusive create by default | Directory-swap escape, explicit overwrite, containment tests |
| Cancelled scripts continue | Bound I/O; kill process group and reap on cancellation/timeout | Delayed effect and descendant cancellation, timeout |
| Local providers inherit proxies | Disable proxies; canonicalize localhost to literal loopback | Real loopback request under hostile proxy configuration |
| Failed runs disappear | Persist stage intent, failure, denial, cancellation, and partial artifacts | Failed CLI transcription/context, cancelled prepare |
| Exposure record omits destinations | Record attempted/succeeded/failed/cancelled exposure for delivery too | Network delivery, failed context, cancellation |
| Secret-free claim overstates validation | Reject credential keys/URL patterns; narrow documented claim | URL user information and query credential rejection |
| Transcript permissions | Database/WAL/SHM at 0600; new immediate private directory at 0700 | Permissions under permissive umask |
| CLI masks failed delivery | Nonzero exits for failed/partial runs | Failed file-delivery CLI test |
| Loader/schema disagreement | Strict roots, duplicate keys, finite numbers, field/refinement types | Independent JSON Schema structural fixtures |
| Unbounded process output | Bound stdout/stderr during reads; monitor JSON while child runs | Noisy child, growing file, timeout |

## Trust and recovery boundaries

- Registered adapters, resolvers, binaries, and model installations are trusted
  application code. Validation does not sandbox hostile adapters or a compromised
  same-user process.
- `local_only` rejects unsandboxed executable destinations and accepts audited
  local providers. OS-level network isolation is a separate deployment control.
- HTTP transports ignore proxy configuration and reject redirects. Network
  operations already sent cannot be recalled by cancelling a task.
- Atomic dispatch claims and persisted intent do not promise exactly-once
  external delivery. Webhooks receive an idempotency key for receiver enforcement.
- Interrupted actions retain `dispatching`/`cancelled` status and `in_progress`
  destination intent where outcomes are uncertain. Automatic replay is refused;
  inspect the external destination before starting a new run.
- In-memory stale-run protection lasts for the registry lifetime. Use a
  `SQLiteStore` with the engine for protection across processes and restarts.
- Secure process groups and descriptor-based file writes require POSIX.
  Unsupported platforms fail closed for these operations.
- A filesystem operation already in progress may finish before cancellation
  returns. Root directories and ancestors must be controlled by the current user
  or a trusted administrator. No-follow traversal prevents link substitution;
  it does not sandbox another privileged process.
- SQLite is plaintext, protected by file permissions. Purge removes prepared
  snapshots too, but cannot guarantee forensic erasure of backups, filesystem
  snapshots, or WAL copies held by another connection.
- Arbitrary text can contain secrets. Review exported pipelines and receipts
  before sharing, even when validation succeeds.

## Compatibility and migration

Pipeline schema remains version 1. Structural validation is tightened; enabled
refinement requires an adapter in schema and loader. Previously accepted malformed
documents may be rejected. Repair types and move credentials to opaque references.

SQLite initialization adds `prepared_runs` without dropping existing data. Old
receipts remain readable, but runs prepared before 0.5.0 lack a safe resume
snapshot/binding; prepare a new run. Back up the database before upgrading.

Persistent adapters must implement `configuration_fingerprint()`, returning
stable JSON-serializable configuration or a digest. Include endpoint, command,
model, root, and prompt configuration as appropriate, excluding raw secrets. All
reference adapters implement it. Changing configuration or reviewed text
invalidates pending approval.

## Verification limits

The fixture suite includes real HTTP connections over loopback. A separate
workflow builds pinned whisper.cpp v1.8.3 and verifies tiny.en SHA-256 before
transcribing upstream JFK audio on Linux/macOS. A local macOS run passed on
2026-10-24. This verifies a real integration contract; broad recognition accuracy,
production latency percentiles, and desktop permissions/insertion remain unproven.
