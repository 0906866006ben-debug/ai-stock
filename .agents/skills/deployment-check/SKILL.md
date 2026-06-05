---
name: deployment-check
description: Use before deployment, environment setup, production configuration, Telegram scheduling, API keys, Docker, hosting, build verification, or release readiness.
---

# Deployment Check Skill

You verify release readiness.

## Required Checks

1. Build command
2. Test command
3. Environment variables
4. Secrets handling
5. API keys
6. Database configuration
7. Scheduled jobs
8. Telegram bot configuration
9. Logging
10. Error monitoring
11. CORS
12. Production fallback behavior

## Environment Variables

Never print secret values.

Document required variable names only.

Examples:

- GEMINI_API_KEY
- GEMINI_ENABLED
- GEMINI_MODEL
- GEMINI_FALLBACK_MODELS
- TELEGRAM_BOT_TOKEN
- DATABASE_URL

## Release Checklist

Return:

1. Readiness verdict
2. Commands to run
3. Required env vars
4. Migration steps
5. Known risks
6. Rollback plan
7. Post-deploy smoke tests

## Hard Rules

- Do not commit secrets.
- Do not disable tests for deployment.
- Do not allow production to silently use mock data unless explicitly configured and clearly labeled.