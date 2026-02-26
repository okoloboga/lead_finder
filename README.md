# LeadSense

LeadSense is a Telegram bot for finding and qualifying B2B leads from Telegram chats.
It is designed for agencies/freelancers who sell automation services (Telegram bots, AI assistants, workflow integrations).

## What It Does

- Creates "programs" (niche + source chats + settings).
- Parses chat activity and identifies potential lead candidates.
- Qualifies candidates with LLM.
- Stores and shows lead cards in Telegram.
- Extracts pains from saved/qualified leads.
- Clusters pains and generates draft posts for your content workflow.
- Supports scheduled runs per program (daily time), with in-bot on/off toggle.

## Current Architecture

- `aiogram` bot UI and handlers
- `Telethon` for Telegram parsing/auth session
- `SQLAlchemy + PostgreSQL` for storage
- `APScheduler` for scheduled jobs
- `CometAPI` (OpenAI-compatible) for LLM calls
- `Google Custom Search API` for web enrichment/best-practice context

Main entrypoint: `run_bot.py`

## Repository Structure

- `bot/` — bot app, handlers, scheduler, DB models
- `modules/` — parsing, qualification, pain clustering, content generation
- `prompts/` — prompt templates
- `docs/` — product specs and implementation notes
- `run_bot.py` — bot launcher
- `docker-compose.yml` — app + postgres services

## Prerequisites

- Docker + Docker Compose
- Telegram app credentials (`api_id`, `api_hash`, phone)
- Telegram Bot token
- CometAPI key
- Google Custom Search credentials

## Environment Variables

Create `.env` from `.env.example` and fill required values.

Core:

- `COMET_API_KEY`
- `COMET_API_BASE_URL` (default: `https://api.cometapi.com/v1`)
- `COMET_API_MODEL` (general model for qualification, etc.)
- `COMET_API_POST_MODEL` (dedicated model for post generation)
- `GOOGLE_API_KEY`
- `GOOGLE_CSE_ID`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_PHONE`
- `TELEGRAM_BOT_TOKEN`

Database (used by Docker Compose service `db`):

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

Useful runtime settings:

- `MESSAGES_LIMIT`
- `MESSAGE_MAX_AGE_DAYS`
- `SAFETY_MODE` (`fast`, `normal`, `careful`)

## Quick Start (Docker)

1. Create and fill `.env`:

```bash
cp .env.example .env
```

2. Build and start services:

```bash
docker compose up -d --build
```

3. Watch logs:

```bash
docker compose logs -f app
```

## Telegram Session Authentication (Telethon)

The bot needs a valid Telethon user session to parse chats.

Option A (recommended in-bot flow):

- Start a program run.
- If auth is required, bot asks for code/password.
- Complete steps directly in Telegram.

Option B (manual one-time local session generation):

```bash
python generate_session.py
```

This creates/updates Telethon session file, then Dockerized app can reuse it.

## Typical In-Bot Workflow

1. Open bot and go to `My Programs`.
2. Create a program (name, niche, source chats).
3. Run manually (`Run`) or keep scheduled auto-collection enabled.
4. Review lead cards.
5. Open `Pains & Content` to inspect clusters and generate drafts.

## Notes on Content Generation

- Post generation uses `COMET_API_POST_MODEL`.
- Before generation, system fetches web best practices for AI/business integration and injects them into prompt context.
- Current UX uses one unified post mode (no scenario/insight/trend selection).

## Troubleshooting

- `TELEGRAM_BOT_TOKEN not found`: check `.env`.
- No pains/clusters shown: ensure program has qualified leads and run completed successfully.
- Callback timeout errors (`query is too old`): update to latest code (callback ack is handled early).
- DB errors about schema/constraints: restart app after pulling latest updates so startup migrations run.

## Development

Install dependencies locally if needed:

```bash
pip install -r requirements.txt
```

Run bot locally:

```bash
python run_bot.py
```

For production-like usage, Docker Compose is recommended.

## CI/CD Auto Deploy (GitHub Actions -> Server)

This repository includes an auto-deploy workflow:
- File: `.github/workflows/deploy.yml`
- Trigger: every push to `main` (and manual `workflow_dispatch`)
- Action: SSH to server -> `git pull` -> `docker compose up -d --build`

Required GitHub repository secrets:
- `DEPLOY_HOST` (server IP/domain)
- `DEPLOY_USER` (SSH user)
- `DEPLOY_SSH_KEY` (private key in PEM/OpenSSH format)
- `DEPLOY_PATH` (absolute path to project on server, e.g. `/opt/leadsense`)

Optional secrets:
- `DEPLOY_PORT` (default `22`)
- `DEPLOY_BRANCH` (default `main`)

Server prerequisites:
- Repository cloned at `DEPLOY_PATH`
- Docker + Docker Compose installed
- SSH user has permissions to run `docker compose`
- Server can run `git pull` for this repository (deploy key or machine user configured)
