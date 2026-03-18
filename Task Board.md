# Task Board

## Today
- [ ] Push v1.2.3 + create release tag
- [ ] Investigate N+1 API calls (electricity + gas readings per update cycle) — needs API schema review

## This Week
- (clear)

## Backlog
- [ ] O(1) device lookup dict — deferred, O(N) fine at current device counts

## Done
- [x] Set up project with Claudify (`/start`)
- [x] Comprehensive code review — session 1 (refactor: tariff_scraper.py, data_processor.py, __init__.py rewrite, entity fixes)
- [x] Comprehensive code review — session 2 (15 issues fixed: critical timeout, parallel fetches, ISO8601, private attrs)
- [x] System audit — Grade B, agent-memory dirs created, knowledge base populated
- [x] Code quality pass + test coverage (+78 tests, 272 total): bug fixes, datetime standardisation, new test_data_processor.py
- [x] Commit v1.2.3 + update docs (CHANGELOG, manifest.json, both READMEs identical)
