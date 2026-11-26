# TradeLab V5 Hybrid — Deployment Report

**Date:** 26 November 2026

## Deployment Targets
- **GitHub Branch:** `main` (Backup tag created before merge: `backup-pre-v5-hybrid-56ddbfb`)
- **Backend (Render):** `https://papertrade-1-uv24.onrender.com`
- **Frontend (Vercel):** `https://papertrade-ebon.vercel.app`
- **Database (Supabase PostgreSQL):** Connected via `DATABASE_URL` (no V5 migration required)

## Operator Recommendations
1. Set `EXCHANGE_HOLIDAYS` in Render environment variables (comma-separated `YYYY-MM-DD` NSE holidays, e.g. `2026-11-24,...`) so `1h`/`1d` completed-bar checks remain accurate across holidays.
2. Keep a single Render backend worker active so in-process SmartAPI rate limiting and scheduler slot locks remain serialized.
3. Keep `auto_execute` disabled in the Debate Scheduler until live market-hours (`09:15–15:30 IST`) validation is completed.
