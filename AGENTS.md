# Project continuity contract

## Start every conversation
1. Read this file, applicable directory instructions, README.md, docs/PROJECT_STATE.md and docs/DECISIONS.md. Read recent entries in docs/CHANGELOG.md; search older entries when relevant.
2. Check the repository root, current branch, HEAD, `git status --short`, and recent Git history. If Git is unavailable, state that limitation. Inspect relevant source, configuration, manifests and tests before making claims. Do not print secrets or read credential files for context gathering.
3. Treat memory documents as navigation, not proof. If code and documentation disagree, inspect the source, explain the discrepancy and correct the documentation. Distinguish intended requirements, implemented behavior and tested behavior.
4. Briefly state the understood goal, actual current state and next action. Ask only for missing information that prevents safe progress. Do not ask the user to repeat facts already verified in the repository.

## Work step by step
- Define the requested outcome and a short ordered plan; track completed, pending and blocked work.
- Inspect before editing. Make focused, reversible changes. Preserve unrelated user edits. Do not reset, overwrite, clean or stash them without authorization.
- Use existing project commands and conventions; do not invent APIs, paths, results or dependencies. Consult current official documentation when uncertain. Label assumptions and verify them before relying on them.
- Preserve existing business logic unless the task authorizes changing it. Record significant behavior changes with their reasons.
- Run checks appropriate to the changes. Record the exact command, result and relevant limitation. A planned test is not a passed test. A passing unit test is not evidence of deployment or live operation.
- Stay within the user's requested scope. Never place secrets, tokens, customer data or private environment values in memory, logs or README. Use variable names and placeholder examples.

## Finish every task, including partial or blocked work
1. Inspect the final diff, including staged and unstaged changes and relevant untracked files. Separate your changes from pre-existing edits; do not infer authorship from a dirty working tree alone.
2. Update README.md in place: verified purpose, setup/run commands, main features, relevant architecture links, limitations and a concise Latest changes section. Preserve useful existing sections. Do not replace the README with a session transcript. Link the memory files below.
3. Update docs/PROJECT_STATE.md: objective, verified architecture with real paths, completed work, current task, remaining steps in order, blockers, checks, and exact next action. Keep this compact. Include date, branch and inspected HEAD when available; note that uncommitted edits may follow that HEAD.
4. Append a dated entry to docs/CHANGELOG.md: goal, changes and paths, behavior impact, checks actually run, failures/skips, unresolved issues, and commit reference if known. Never fabricate a commit hash. Do not retroactively rewrite history; append corrections.
5. Append significant choices to docs/DECISIONS.md with rationale and tradeoffs. Label proposed decisions separately from accepted ones; link superseding decisions rather than erasing old ones.
6. Review documentation against the final code. If interrupted, leave an explicitly partial checkpoint; never mark unfinished work complete. Documentation-only changes need no invented runtime tests.
7. Report outcome, validation, remaining issues and next step briefly. Commit or push only when authorized. Keep memory updates with the related code changes when committing.

## First use in an existing project
Create missing memory documents only after inspecting the repository. Mark unknowns explicitly. Reconstruct only what source and Git history support; do not invent past conversation details or claim full historical coverage. Verify any user-provided history before labeling it implemented. Never treat template placeholders as project facts.

## Resume rule
A fresh chat must read these files again. Never claim personal recall of a conversation that is not available. If the client does not load instructions automatically, ask it explicitly to read AGENTS.md and the memory files. These files do not run a background monitor; the active coding agent maintains them during tasks. If documentation is stale after manual edits, reconcile it from the actual changes before continuing.
