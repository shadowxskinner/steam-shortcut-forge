# Shared Agent Protocol

## Evidence

- Prefer direct executed behavior for runtime claims.
- Use relevant tests, source code, Git history, and verified context as supporting evidence appropriate to the claim.
- A stale or unexecuted test is not proof that current behavior works.
- Never claim reproduced, tested, fixed, working, supported, broken, or safe unless evidence supports that exact statement.
- Use labels when useful: REPRODUCED, VERIFIED FROM TEST, VERIFIED FROM CODE, INFERRED FROM CODE, USER REPORTED.
- Attribute another agent's evidence, for example: `REPRODUCED (by local Codex): ...`. Never present another agent's run as your own.
- Do not infer capability, success, failure, ownership, compatibility, or correctness from the presence or absence of an artifact alone. Verify behavior directly and distinguish observation from inference.

## SHOULD and DOES

- The current human task and acceptance criteria define what SHOULD happen.
- Executed behavior and source evidence define what DOES happen.
- Do not blur SHOULD and DOES. If a material requirement is ambiguous, ask the human instead of inventing behavior.

## Roles

- **IMPLEMENTER:** May edit only within the requested scope and must not silently change roles.
- **IMPLEMENTER:** Uses a task branch for meaningful changes and does not work directly on `main`.
- **IMPLEMENTER:** Performs relevant verification and reports exact changed files plus what was and was not tested.
- **REVIEWER:** Starts read-only and does not silently repair findings.
- **REVIEWER:** Reports evidence-based issues, distinguishes blocking from non-blocking, and suppresses style noise unless requested.
- **HUMAN:** Resolves unclear requirements and evidence-based disputes the agents cannot close.

## Review severity

- **BLOCKING:** A concrete correctness defect, security issue, data-loss risk, requirement violation, or meaningful regression.
- A blocking finding states location, triggering condition, expected behavior, actual behavior, and evidence.
- **NON-BLOCKING:** A concrete maintainability or testability issue.
- **STYLE:** Suppress unless explicitly requested.

## Scope discipline

- Do not broaden a task merely because adjacent improvements are visible.
- Report useful unrelated findings separately; do not silently turn a focused change into a multi-component refactor.

## Git safety

- Use one branch per meaningful task; do not work directly on `main`.
- Do not force-push or rewrite shared history.
- Stage intended paths deliberately and prefer small, coherent commits.
- The human controls merge.
- Do not create worktrees by default; use them only when real concurrent work justifies them.

## Shared durable context

- Read `.ai/context.md` before making project claims.
- It contains only stable, verified project facts: no secrets, transient Git/task state, or agent chatter.
- Keep it small.
- If a code change makes it false, update it in the same change. A contradiction between code and durable context is BLOCKING.

## Handoffs

- Do not create a permanent handoff file in Phase 1.
- Pass work with four fields: TASK + ACCEPTANCE; SUMMARY; VERIFICATION; RISK / REVIEW FOCUS.

## Disagreement

- A reviewer reports evidence; an implementer may reject a finding with equal or stronger evidence.
- If evidence does not resolve the dispute, ask the human and stop looping. Propose `decisions.md` later only if durable decisions accumulate.

## Secrets

- Never commit API keys, bot tokens, auth tokens, credentials, private keys, or secret environment contents.
- Never paste secrets into shared context, handoffs, or review reports.
