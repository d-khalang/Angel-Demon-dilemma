---
name: python-sqlite-modern
description: Modern Python sqlite3 guidance for local app persistence. Use when creating, reviewing, or updating Python code that uses sqlite3, especially transaction control, connection lifecycle, foreign keys, WAL mode, busy timeouts, row factories, parameter binding, or SQLite integration tests.
---

# Python SQLite Modern

Use this skill when working with Python's standard `sqlite3` module in current Python versions.

## Core Rules

- Prefer explicit transaction control with `sqlite3.connect(..., autocommit=False)` on Python 3.12+ when normal DB-API transaction behavior is desired.
- If connection PRAGMAs must run outside a transaction, open with `autocommit=True`, apply PRAGMAs, then switch to `conn.autocommit = False`.
- Always close connections explicitly. The `sqlite3.Connection` context manager commits or rolls back, but it does not close the connection.
- Use a custom context manager when the code needs commit/rollback/close in one reusable pattern.
- On success, call `commit()`. On exception, call `rollback()`. In all cases, call `close()`.
- Use parameter binding with `?` placeholders. Never interpolate user values into SQL strings.
- Set `row_factory = sqlite3.Row` when callers need named-column access.
- Enable `PRAGMA foreign_keys = ON` on every connection that relies on foreign key enforcement.
- Apply `PRAGMA foreign_keys = ON` before entering an active transaction, because SQLite treats changing it inside a transaction as a no-op.
- For local file-backed app databases, consider `PRAGMA journal_mode = WAL` for better read/write behavior.
- Set either `connect(timeout=...)` or `PRAGMA busy_timeout = ...` when concurrent app actions may briefly lock the database.
- Keep SQLite usage local and modest. For multi-user production, plan a migration path to PostgreSQL or another server database.

## Preferred Connection Pattern

```python
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3


@contextmanager
def connect_db(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=10.0, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.autocommit = False

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

For `":memory:"`, skip `journal_mode = WAL`.

## Review Checklist

- Does every connection close?
- Are writes committed and failures rolled back?
- Are SQL values parameterized?
- Are foreign keys actually enforced on the connection?
- Are connection settings applied before the transaction state makes them ineffective?
- Are tests checking cascade behavior if the schema depends on `ON DELETE CASCADE`?
- Is the code explicit about Python 3.12+ `autocommit` behavior instead of depending on legacy defaults?

## Official References

- Python sqlite3 docs: https://docs.python.org/3/library/sqlite3.html
- Python transaction control: https://docs.python.org/3/library/sqlite3.html#transaction-control
- Python connection context manager: https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager
- SQLite PRAGMA foreign_keys: https://www.sqlite.org/pragma.html#pragma_foreign_keys
- SQLite PRAGMA busy_timeout: https://www.sqlite.org/pragma.html#pragma_busy_timeout
- SQLite PRAGMA journal_mode: https://www.sqlite.org/pragma.html#pragma_journal_mode
