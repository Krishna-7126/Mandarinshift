---
description: "Use when reviewing LocalShift changes for correctness, security, reliability, tests, or compatibility."
---

# LocalShift Code Review

Use this instruction only for code reviews. Read the relevant diff, root `AGENTS.md`, and related implementation and tests. Treat the existing adapter, planner, and conversion boundaries as authoritative; do not propose architecture changes for style alone.

Report only verified, actionable findings. Include the file and line, impact, severity, and a minimal fix direction. Prioritize security, data loss or corruption, functional regressions, concurrency and cleanup failures, and public API or route compatibility. Avoid speculative issues and style-only suggestions.

For conversion, adapter, and file-format changes, consult the security and reliability notes in `README.md` and relevant tests. Check applicable input path and size validation, content-based format detection, preflight and execution validation, cancellation, output ownership, atomic commit and temporary-file cleanup, and the offline/no-network invariant. For new untrusted decoders, also check that format-specific resource use is bounded.

Check that critical behavior and failure paths have focused tests. Use the repository's existing pytest setup; do not impose a blanket line-coverage target.

Do not edit files while reviewing. Group related findings and return the highest-severity findings first.

Adapted from [Awesome Copilot's generic code-review instructions](https://github.com/github/awesome-copilot/blob/d85f762d6e521abf5fe16703946e9b38adc42da7/instructions/code-review-generic.instructions.md).
