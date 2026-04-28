# Prompt Library

Reusable prompts for future AI sessions. Do not read all docs automatically; open only the files relevant to the task.

## Start A Targeted Task

Read `CLAUDE.md`, then open only the AI docs relevant to this task: `<area>`. Do not load the full `docs/ai` directory unless the task explicitly requires a cross-system audit.

## Security Center AI Change

Work on the safety/compliance workflow for `<module>`. Preserve ACL, audit logging, source-of-truth boundaries, privacy, and synthetic-only examples. Start with `docs/ai/05_SECURITY_BOUNDARIES.md`, then open module context from `docs/ai/03_BACKEND_MODULES.md` only if needed.

## Frontend Change

Update the UI for `<module/page>`. Start with `docs/ai/04_FRONTEND_DIRECTION.md`. Keep SSR/Django templates and HTMX patterns consistent with the existing shell and avoid duplicating domain workflow pages in `dashboard`.

## Backend Module Change

Implement `<feature>` in `<app>`. Start with `docs/ai/03_BACKEND_MODULES.md` for module rules and `docs/ai/02_ARCHITECTURE.md` for ACL/routing if permissions or URLs change.

## Release / Setup Wizard Change

Modify release or setup behavior for `<area>`. Start with `docs/ai/06_TESTING_AND_QUALITY_GATES.md` and confirm version, release guard, Setup Wizard bundle, and sensitive-file exclusions before finishing.
