# LeadCore Test Plan (Actual)

## 1. Goal
Maintain stable automated verification for bot handlers and core services with deterministic unit tests in CI.

## 2. Current State (Fact)
- Test stack is configured and active (`pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`).
- `tests/` is tracked in git and used in CI.
- `pytest.ini` is configured (`testpaths = tests`, `asyncio_mode = auto`, markers).
- Unit suite is green locally: `185 passed`.
- CI unit command uses explicit module path: `PYTHONPATH=. pytest -m unit --cov=bot.services.subscription --cov-report=term-missing`.

## 3. Scope

### In Scope
- `bot/services/*`
- `modules/*`
- Critical handlers in `bot/handlers/*`
- UI builders/formatters in `bot/ui/*`

### Out of Scope
- Real network calls to Telegram/CometAPI/Google CSE in unit tests.
- Full e2e against real Telegram infrastructure.

## 4. Test Layers

### Unit Tests
- Pure logic and mocked boundaries.
- Primary marker: `unit`.

### Handler Tests
- Callback/message flows with fake sessions and stubs.
- Included in unit run via marker usage.

### Integration Tests
- Marker exists (`integration`) for future DB-backed suites.
- Not required in the current CI gate.

## 5. Running Tests

### Local
```bash
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest
PYTHONPATH=. pytest -m unit
PYTHONPATH=. pytest -m unit --cov=bot.services.subscription --cov-report=term-missing
```

### Docker (optional)
```bash
docker compose exec app bash -lc 'PYTHONPATH=. pytest -m unit'
```

## 6. CI (GitHub Actions)
Workflow: `.github/workflows/tests.yml`

Current steps:
1. Setup Python 3.10
2. Install runtime + dev requirements
3. Run unit tests with coverage:
   - `PYTHONPATH=. pytest -m unit --cov=bot.services.subscription --cov-report=term-missing`

## 7. Coverage Focus
Current explicit gate target in CI:
- `bot/services/subscription.py`

Recommended next expansion:
- `--cov=bot --cov=modules --cov-report=term-missing`
- Minimum threshold after stabilization: `--cov-fail-under=70`

## 8. Known Pitfalls and Fixes
- Symptom: `ModuleNotFoundError: No module named 'bot'` in CI.
  - Cause: missing `PYTHONPATH` in workflow command.
  - Fix: run pytest with `PYTHONPATH=.`.

- Symptom: `collected 0 items` in CI.
  - Cause: `tests/` ignored/not tracked previously.
  - Fix: remove `tests/` from `.gitignore` and track tests in repository.

## 9. Change Policy
Any change that touches:
- `bot/services/*`
- `modules/*`
- `bot/handlers/*`

must include:
1. Updated unit tests for changed behavior.
2. Green run of `PYTHONPATH=. pytest -m unit`.

## 10. Short Checklist
- [x] `requirements-dev.txt` configured
- [x] `pytest.ini` configured
- [x] `tests/` tracked in git
- [x] Unit suite green locally
- [x] CI unit workflow green configuration (`PYTHONPATH=.`)
- [ ] Integration marker suite extended
- [ ] Global coverage gate enabled
