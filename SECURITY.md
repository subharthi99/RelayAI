# Security Policy

RelayAI processes audio, transcripts, credentials, local files, network
requests, and executable actions. Please report security problems privately and
responsibly.

## Supported versions

RelayAI is pre-alpha. Security fixes are applied to the latest code on the
default branch and, when practical, the latest published minor release. Older
pre-alpha versions should not be assumed to receive fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:

1. Open the repository's **Security** tab.
2. Select **Advisories**.
3. Select **Report a vulnerability**.

If private reporting is not enabled, contact the maintainer privately using the
contact information on their GitHub profile. Do not disclose the issue in a
public issue, discussion, pull request, or commit.

Include:

- affected version or commit;
- reproduction steps or a minimal proof of concept;
- expected and observed behavior;
- security and privacy impact;
- affected platforms or configurations; and
- a suggested fix, if known.

Do not access data that is not yours, disrupt services, or retain sensitive data
while researching a report. Use synthetic audio, transcripts, credentials, and
endpoints.

You should receive an acknowledgement within seven days. The maintainer will
work with you on validation, remediation, and coordinated disclosure. Timelines
depend on severity and project capacity.

## Security-sensitive areas

Reports are especially helpful for:

- bypassing `local_only` or exposure policies;
- executing an unapproved script, webhook, or MCP tool;
- escaping allowlisted filesystem roots or command definitions;
- importing embedded credentials or unsafe pipeline defaults;
- authentication or information disclosure in the loopback API;
- leaking transcripts, audio, context, or credentials; and
- dependency or packaging behavior that changes the trusted release artifact.
