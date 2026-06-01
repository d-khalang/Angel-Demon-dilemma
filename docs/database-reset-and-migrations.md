# Database Reset And Migration Notes

This prototype uses a local SQLite database at `data/state.db`.

## Current Prototype Policy

- Local data is disposable during active development.
- Schema changes can reset users, sessions, rounds, messages, and model-run logs.
- The app creates a fresh database automatically on next startup when `data/state.db`
  is missing.

## Resetting Local Data

Stop the Streamlit server first, then delete:

```powershell
Remove-Item -LiteralPath data/state.db -Force
Remove-Item -LiteralPath data/state.db-wal -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath data/state.db-shm -Force -ErrorAction SilentlyContinue
```

Then restart:

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.port 8501 --server.headless true
```

## Migration Story For Production

If this moves beyond local prototype data, switch from ad hoc schema creation to explicit
migrations:

- Use versioned migration files, one schema change per file.
- Keep destructive resets out of app startup.
- Add forward-only migrations for new columns/tables and explicit backfills for JSON fields.
- Store durable data in PostgreSQL with JSONB for round snapshots and indexed tables for
  users, sessions, messages, and model runs.
- Test migrations against a copied production-like database before deploy.

