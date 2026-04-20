from __future__ import annotations

import pathlib
import sqlite3
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def connect_db(path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
