# TradeLab Cloud V6 — Deployment & Render Free Compatibility Report

**Date:** 27 November 2026

## Deployment Targets
- **GitHub Branch:** `main` (Backup tag: `backup-pre-v6-308e7aa`)
- **Backend (Render Free):** `https://papertrade-1-uv24.onrender.com` (1 worker)
- **Frontend (Vercel):** `https://papertrade-ebon.vercel.app`
- **Database (Supabase PostgreSQL):** Connected via `DATABASE_URL` (`pooler.supabase.com:6543`)

## Render Free Hosting Considerations
- Render Free may spin down after inactivity; outbound Angel One WebSocket (`BrokerStream`) does not prevent Render Free from sleeping on zero inbound HTTP traffic.
- On restart/cold start, `BrokerStream.ensure_running()` re-authenticates via `angel_service.authenticate()` and resubscribes active instruments; primary `paper_trades`, `mcx-paper:<uid>`, `shadow-ledger:<uid>`, and `risk-config:<uid>` persist in Supabase PostgreSQL.
- Keep `V6_AUTO_EXECUTION_ENABLED=false` until live NSE market-hours validation passes.
