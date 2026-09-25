## Summary

<!-- What changes, and why. -->

## Checklist

- [ ] `ruff check .` and `pytest -q` pass (and `npm run typecheck && npm test` in `sdk-ts/` if touched)
- [ ] Wire changes update `docs/NETWORK_PROTOCOL.md`; incompatible ones bump `schema_version`
- [ ] Server or SDK changes were run on the real stack (`python -m arena.server` plus a demo)
- [ ] `CHANGELOG.md` updated under `[Unreleased]` if users would notice
