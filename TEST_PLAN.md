# LeadCore Test Plan

## 1. Goal
Establish reliable automated tests for backend services and bot flows before production, with fast feedback in CI and clear quality gates.

## 2. Current State (Fact)
- No test framework configured in repository yet.
- No `tests/` directory exists.
- Core runtime is Python (`aiogram`, SQLAlchemy async, APScheduler, Telethon, LLM integrations).
- There is no separate frontend/client app in this repository right now.

## 3. Scope

### In Scope (this repo)
- `bot/services/*` business logic.
- `modules/*` core processing logic.
- Critical bot handlers (`bot/handlers/*`) for user-facing flows.
- UI formatters/builders (`bot/ui/*`) where logic exists.

### Out of Scope (for now)
- Real external API calls in tests (Telegram, CometAPI, Google CSE).
- End-to-end tests against real Telegram network.

### Client Testing Note
A separate “client/front” codebase is not present here. If client exists in another repo, create a mirrored test plan there (unit + integration + e2e) and keep release gates synchronized.

## 4. Test Strategy (Pyramid)

### 4.1 Unit Tests (largest layer)
Focus on pure logic and deterministic outputs.

Targets:
- `bot/services/subscription.py`
- `modules/input_handler.py`
- `modules/output.py` (formatters/serialization)
- `modules/qualifier.py` helper functions (`_extract_json_payload`, parsing helpers)
- `modules/pain_collector.py` normalization helpers
- `modules/pain_clusterer.py` parsing/render helpers
- `modules/content_generator.py` quote anonymization and parser helpers
- `bot/ui/*.py` formatting and keyboard composition

### 4.2 Service Integration Tests (middle layer)
Run async DB-backed tests with isolated database schema.

Targets:
- `bot/services/program_runner.py`
  - lead creation/update
  - free-tier weekly limit behavior
  - pain extraction persistence path
  - safe handling of qualification failures
- `modules/pain_clusterer.py`
  - cluster assignment behavior from mocked LLM response
  - stats updates (`pain_count`, `avg_intensity`, `trend`)

### 4.3 Handler/Flow Tests (thin layer)
Test key bot flows with mocked Bot/Callback/Message and mocked services.

Priority flows:
- `start` onboarding (new user vs existing user)
- `program_create` happy path + invalid chat input
- `program_view` run/delete/clear actions
- `subscription` invoice + successful payment update
- `pains_handler` list/detail/generate/menu navigation

### 4.4 Contract/Boundary Tests
Enforce robust handling of unstable boundaries.

Targets:
- LLM JSON parsing tolerance (invalid/incomplete payloads)
- Web search wrappers with empty or malformed responses
- Telegram parsing functions for missing fields (`username`, `bio`, `message_id`)

## 5. Tooling and Project Setup

## 5.1 Dependencies
Add to `requirements-dev.txt` (new file):
- `pytest`
- `pytest-asyncio`
- `pytest-cov`
- `pytest-mock`
- `freezegun`
- `factory-boy` (optional)

## 5.2 Pytest Config
Create `pytest.ini`:
- `testpaths = tests`
- `asyncio_mode = auto`
- markers: `unit`, `integration`, `handler`, `slow`

## 5.3 Test Layout
Create structure:
- `tests/unit/...`
- `tests/integration/...`
- `tests/handlers/...`
- `tests/fixtures/...`
- `tests/conftest.py`

## 5.4 Test Helpers
Implement reusable fixtures:
- async DB session fixture with transaction rollback
- fake `User/Program/Lead/Pain` factories
- mocked LLM client fixture
- mocked Telegram client fixture
- frozen-time fixture for subscription logic

## 6. Detailed Coverage Plan by Module

### 6.1 `bot/services/subscription.py` (P0)
Test cases:
- free user limits (`program_count`, `weekly_analysis`)
- paid expiry normalization
- `activate_paid_subscription` date math (`1m/3m/6m/12m`)
- edge dates (month ends, leap years)

### 6.2 `bot/services/program_runner.py` (P0)
Test cases:
- skips candidates without username
- score filtering respects `min_score`
- updates existing lead, creates new lead
- handles qualification errors without crash
- saves pains with dedup keys
- returns expected summary fields

### 6.3 `modules/members_parser.py` (P1)
Test cases:
- message link generation for public/private chats
- freshness categorization
- age formatting boundaries
- channel extraction from bios

### 6.4 `modules/pain_*` and `modules/content_generator.py` (P1)
Test cases:
- normalization/category/intensity defaults
- cluster assignment application from mocked LLM output
- trend computation from date windows
- quote anonymization (`@username`, links)

### 6.5 `bot/handlers/*` critical paths (P1)
Test cases:
- `/start` onboarding and language branch
- create program flow with valid/invalid input
- run program permission checks
- payment success updates user subscription

### 6.6 `bot/ui/*` and `modules/output.py` (P2)
Test cases:
- keyboard callbacks present and stable
- formatted lead cards include required fields
- markdown/json output handles missing optional fields

## 7. Mocking Policy
- Never call real Telegram, CometAPI, Google CSE in CI tests.
- Patch network adapters at module boundary (not deep internals).
- Validate only data contracts and state changes.

## 8. Quality Gates (Production Readiness)

### Gate A (minimum to merge)
- all tests pass
- no skipped P0 tests
- coverage >= 55% overall
- coverage >= 80% for `bot/services/subscription.py`

### Gate B (before production)
- coverage >= 70% overall
- coverage >= 85% for `bot/services/*`
- coverage >= 75% for `modules/pain_*` and `program_runner.py`
- smoke integration suite green

## 9. CI Plan
Create GitHub Actions workflow `.github/workflows/tests.yml`:
1. Setup Python 3.10
2. Install `requirements.txt` + `requirements-dev.txt`
3. Run lint/static checks (optional next step)
4. Run:
   - `pytest -m unit`
   - `pytest -m "integration or handler"`
   - `pytest --cov=bot --cov=modules --cov-report=xml --cov-report=term`
5. Upload coverage artifact and fail if below threshold

## 10. Phased Execution Plan

### Phase 1 (1-2 days) - Foundation
- Add pytest stack and config
- Add fixtures/factories
- Add first P0 tests for subscription service

### Phase 2 (2-3 days) - Core Reliability
- Add P0 tests for `program_runner.py`
- Add parser and output unit tests
- Add LLM parsing contract tests

### Phase 3 (2-3 days) - Bot Flows
- Add handler tests for start/program/subscription/pains flows
- Stabilize callback/keyboard assertions

### Phase 4 (1 day) - CI + Hardening
- Add CI workflow
- Enable coverage thresholds
- Remove flaky tests and finalize docs

## 11. Deliverables Checklist
- [ ] `requirements-dev.txt`
- [ ] `pytest.ini`
- [ ] `tests/` scaffold with shared fixtures
- [ ] P0 service tests (subscription + program_runner)
- [ ] P1 tests (pain modules + handlers)
- [ ] CI workflow for tests + coverage
- [ ] Updated `README.md` section: “How to run tests”

## 12. Commands (target)
- `pip install -r requirements.txt -r requirements-dev.txt`
- `pytest`
- `pytest -m unit`
- `pytest -m integration`
- `pytest --cov=bot --cov=modules --cov-report=term-missing`

## 13. Risks and Mitigations
- Risk: Async DB tests become flaky.
  - Mitigation: single transaction per test, deterministic fixtures, no shared mutable global state.
- Risk: Over-mocking hides integration bugs.
  - Mitigation: keep a small integration suite that executes real DB logic with mocked external APIs.
- Risk: Slow test runtime.
  - Mitigation: strict markers (`unit` fast, integration targeted), parallelization later.

## 14. Recommended First PR (small and safe)
1. Add testing infrastructure files (`requirements-dev.txt`, `pytest.ini`, `tests/conftest.py`).
2. Add tests only for `bot/services/subscription.py`.
3. Add CI job running unit tests only.

Then expand coverage iteratively.
