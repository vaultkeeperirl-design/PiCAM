# Conductor Journal

## 2026-02-22 - Initial Release v0.1.0

**Observation:** Project is functional but lacks formal release infrastructure (versioning, changelog, automated releases).
**Action:**
- Established baseline version `v0.1.0`.
- Implemented Semantic Versioning.
- Created `CHANGELOG.md` to track changes.
- Created GitHub Release workflow (`.github/workflows/release.yml`) to automate artifact generation.

## 2026-02-22 - CI/CD Gap Identified

**Observation:** The `ci.yml` workflow only executed linter checks, while unit tests were restricted to the release workflow. This created a risk of merging broken code that passes linting but fails logic tests.
**Action:** Updated `.github/workflows/ci.yml` to execute unit tests on every push and pull request.
