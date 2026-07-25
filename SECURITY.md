# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security vulnerability.

Instead, use GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/faizannraza/wattage/security).
2. Click **"Report a vulnerability"**.
3. Describe the issue, including steps to reproduce and its potential impact.

This opens a private advisory visible only to you and the maintainer, so
the issue can be discussed and fixed before it's public.

## Scope

Wattage reads and analyzes trace files entirely locally — it makes no
network calls by default (the optional `wattage[judge]` LLM-judge extra
and the optional `wattage[embeddings]` extra are the only features that
touch anything beyond the local filesystem, and both are off unless
explicitly configured). Reports of particular interest:

- Anything in the OTLP/trace parsing path that could lead to arbitrary
  code execution or a denial of service from a malicious trace file.
- Supply-chain issues in the published PyPI (`wattage`) or npm
  (`wattage-cli`) packages.
- Anything in the GitHub Action (`action/`) that could leak secrets or
  execute untrusted code in a CI context.

## Supported versions

This project is pre-1.0. Security fixes land on the latest released
version; there is no separate maintenance branch yet.
