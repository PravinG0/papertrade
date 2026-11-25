# Deployment & Production Verification Report

**Date:** 26 November 2026  
**Target Branch:** `main` (pushed directly to `origin/main`)  
**Rollback Tag:** `backup-pre-qa-repaired-52a8419` (at prior verified commit `52a8419`)

## 1. Infrastructure Mapping Observed

- **Frontend Hosting (Vercel):** `https://papertrade-ebon.vercel.app` (verified pointing to `https://papertrade-1-uv24.onrender.com`).
- **Backend Hosting (Render):**
  - Primary service referenced by Vercel & `vercel.json`: `https://papertrade-1-uv24.onrender.com` (Supabase PostgreSQL active, keep-alive active).
  - **Duplicate Render Service Notice:** `https://papertrade-s9fq.onrender.com` was also observed running against Supabase PostgreSQL (`is_postgres: true`, `total_pings: 11`). To obey the single-worker rule (`QA-20` / `QA-15`) and eliminate cross-service race risk during auto-debates or replay, disable or pause the unused duplicate Render web service if both share the same Supabase database and GitHub repo.
- **Database:** Supabase PostgreSQL via transaction pooler (port `6543`, `statement_cache_size=0`, `pool_size=3`).
- **Market Data:** Angel One SmartAPI REST + pyotp TOTP (`ANGEL_*` configured; live quote auth and NIFTY/VIX quotes verified HTTP 200).
- **AI Engine:** Gemini API (`GEMINI_MODEL=gemini-3.8-flash` default; secondary fallback updated to `gemini-3.5-flash-lite` after `gemini-3.8-flash` hit daily Free Tier `429` cap and `gemini-2.5-flash` returned `404`).

## 2. Deployment Configuration Changes

- Optional `.env` settings documented in `.env.example`:
  - `EXCHANGE_HOLIDAYS=` (comma-separated `YYYY-MM-DD` official closure dates)
  - `EXCHANGE_SPECIAL_SESSIONS=` (`YYYY-MM-DD=HH:MM-HH:MM`)
  - `ALLOW_SHORT_OPTIONS=true` (set `false` to enforce long-only trades)
- `SKIP_DB_INIT` optional toggle added in `backend/database.py` (default unset -> runs strictly additive `apply_additive_migrations()`).

## 3. Rollback Procedure

If any issue arises after deployment:
1. Revert to checkpoint tag on `main`:
   ```bash
   git revert --no-commit <new_commit>..HEAD && git commit -m "rollback: revert to 52a8419"
   ```
   Or create a revert branch from `backup-pre-qa-repaired-52a8419` (`git branch rollback backup-pre-qa-repaired-52a8419`). Never force-push `main`.
2. Database schema changes introduced in this release are strictly additive (`schema_migrations` + indexes), so code rollback requires zero destructive DB changes.
