# LocalShift Milestone 24 — Baseline Inspection

**Inspection date:** 2026-10-28  
**State:** Inspection only; no files reset, cleaned, checked out, staged, regenerated, or packaged during baseline capture.

## Worktree baseline

`git status --short` reported six unstaged modifications, no staged changes, and no untracked files:

| File | Existing change at baseline |
|---|---|
| `src/localshift/radial_menu.py` | Screen-edge popup placement retains the activation point in the target window. |
| `tests/test_radial_menu.py` | Reproduces all four screen corners and negative virtual-screen origins. |
| `CHANGELOG.md` | Records the screen-edge correction and Milestone 23 verification. |
| `docs/ARCHITECTURE.md` | Describes activation-point-aware screen placement. |
| `docs/TEST_PLAN.md` | Records the new radial geometry coverage. |
| `docs/reports/LS-BE-023-release-readiness.md` | Updated findings, focused/full test totals, and checklist. |

These are pre-existing user work for this milestone and must be preserved. No unrelated staged or untracked work was found.

## PDF fixture preservation

The three unseen-document fixture names called out in prior milestone notes currently have no Git diff. Their current SHA-256 values were recorded before any M24 tests:

| Fixture | SHA-256 |
|---|---|
| `tests/fixtures/unseen_documents/val_02_scanned_receipt.pdf` | `C039B5FC1B95D0CB0B946BB4350EEE44B9E7CB08189D48796AA397AB7F0373BD` |
| `tests/fixtures/unseen_documents/val_03_mixed_report.pdf` | `53557216A55351F2C98C62EEB711C76231494F20F1B4C39E55C7A1AC8E5EC662` |
| `tests/fixtures/unseen_documents/val_09_technical_manual_figures.pdf` | `CF3B51E874594C9BE9534603FE6FD4BC7BFA1787EF93C098F13DE33BC1F61852` |

`tests/test_unseen_validation.py` invokes `generate_unseen_validation_fixtures()` unconditionally from a module-scoped autouse fixture; that generator overwrites these files. Do not run that test module or the full suite unless the operator authorizes fixture regeneration. Other fixture-generating modules were inspected; their setup hooks generate only when their initial fixture is absent.

## Relevant implementation and release evidence

- The source-checkout autostart command has already been corrected to invoke `python -m localshift.gui --minimized`; the registry-command regression test exists. This does not constitute a clean-install or installed-app launch test.
- Global drag continues to require a validated local-file OLE URL payload. Selection-based fallback is not the active documented behavior.
- The radial screen-edge defect has a measured offscreen reproduction and a code fix in the existing uncommitted diff. It still needs physical OLE and mixed-DPI verification.
- [LS-BE-023-release-readiness.md](./LS-BE-023-release-readiness.md) records 730 passed, 3 skipped, 0 failed on the most recent full suite before this baseline. That suite result is historical for the checked-out baseline, not a new M24 run.
- [LS-BE-021-physical-verification.json](./LS-BE-021-physical-verification.json) records 0 passed, 0 failed, 10 NOT TESTED. No external drag source is certified.
- The project venv is Python 3.11.9. `pyproject.toml` permits Python `>=3.10` and uses lower bounds/ranges rather than a full dependency lock.
- `PyInstaller` is absent from the project venv. The normal `packaging/build.py` path calls `clean()`, deleting `build`, `dist/LocalShift`, and `dist/installer`. Those directories contain existing outputs and diagnostics. Do not invoke the default build path.
- The previous report verified hashes for existing installer/portable artifacts, but did not rebuild them from current source. Existing artifact verification does not prove current-source packaging.
- README setup describes editable `[dev,desktop]` installation, while package metadata does not declare PyInstaller as a build extra. A clean-environment packaging setup is therefore not currently established.
- Release metadata remains mixed: package/installer metadata is 0.14.0 while changelog/reports include 0.19.0-era features. Do not infer the intended next release version from these files.

## Missing evidence and release blockers

1. No operator-recorded Explorer/Desktop/third-party payload, cancellation, virtual-source, or output correctness results.
2. No mixed-DPI or physical monitor-boundary verification.
3. No physical keyboard-only or screen-reader assessment.
4. No current-source portable package built and smoke-tested in an isolated output directory.
5. No fresh clean-environment dependency installation was performed; the checked-in dependency ranges do not pin a fully reproducible environment.
6. No current-source installer build was performed. Inno Setup availability is not assumed.
7. No physical offline/network trace or production performance measurements were taken.

## Safety constraints for subsequent work

- Preserve the six worktree changes above and the three fixture hashes above.
- Exclude the fixture-rewriting test module unless regeneration is explicitly approved.
- Use a new, isolated output directory for any PyInstaller build; never run the default cleanup path against the existing `build` or `dist` trees.
- Keep all physical verification outcomes NOT TESTED until the operator supplies evidence.
- No stage, commit, push, release, broad cleanup, or artifact replacement is authorized.
