# Backup Object Time-Travel - Implementation Plan

Related design: `docs/superpowers/specs/2026-04-14-backup-object-time-travel-design.md`

## Goal

Ship object-level historical diff and restore workflows for backups in incremental, testable phases.

## Scope for This PR Series

- Add backend primitives needed to retrieve historical object snapshots.
- Add service-level APIs for object-level history and point-in-time compare.
- Add restore preview contracts for single object rollback.
- Add API endpoint coverage and unit tests for each phase.

## Phase Plan

### Phase 1 - Data and service primitives

- Define query helpers for object versions by object key and time range.
- Add deterministic version ordering and pagination contract.
- Add unit tests for empty history, sparse history, and duplicate timestamp edge cases.

### Phase 2 - Diff and comparison API surface

- Add service methods to compare two object versions.
- Reuse existing deep diff utilities where possible.
- Normalize response shape for UI consumption.
- Add tests for added, removed, and modified fields.

### Phase 3 - Restore preview and validation

- Add restore-preview service method for object rollback candidate.
- Validate object type support and block unsupported resource classes.
- Add tests for permission checks and invalid version references.

### Phase 4 - Endpoint integration

- Add/extend backup API routes for history, compare, and restore preview.
- Add route-level tests for happy path and validation failures.
- Verify role enforcement and sanitized error handling.

### Phase 5 - UI integration follow-up

- Add endpoint contracts and examples for frontend implementation.
- Document expected loading/error states for history and compare views.

## Definition of Done

- Unit + endpoint tests for all new service and route behavior.
- No regressions in existing backup test suites.
- Documentation updates in `backend/CLAUDE.md` and relevant module docs if architecture changes.
