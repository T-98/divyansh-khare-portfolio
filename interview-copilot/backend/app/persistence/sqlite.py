"""SQLite-backed session store (aiosqlite, one shared connection).

A live interview is a single user on a single laptop, so one connection behind
an asyncio lock is the right amount of machinery. No ORM.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..models.interview import InterviewResponse, InterviewState, SessionRecord, TurnRecord
from .base import PersistenceError, SessionStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    session_id       TEXT NOT NULL,
    turn_number      INTEGER NOT NULL,
    interviewer_text TEXT NOT NULL,
    response_json    TEXT NOT NULL,
    mode             TEXT NOT NULL DEFAULT '',
    domains_json     TEXT NOT NULL DEFAULT '[]',
    specialists_json TEXT NOT NULL DEFAULT '[]',
    latency_ms       INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_number),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS interview_state (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
"""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SQLiteSessionStore(SessionStore):
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        if self._conn is not None:
            return
        if self._path not in (":memory:", ""):
            parent = Path(self._path).expanduser().resolve().parent
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path or ":memory:")
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise PersistenceError("store not initialised")
        return self._conn

    async def create_session(self, session_id: str) -> SessionRecord:
        record = SessionRecord(session_id=session_id)
        async with self._lock:
            await self._db.execute(
                "INSERT INTO sessions (session_id, created_at) VALUES (?, ?)",
                (record.session_id, _iso(record.created_at)),
            )
            await self._db.execute(
                "INSERT INTO interview_state (session_id, state_json, updated_at) VALUES (?, ?, ?)",
                (
                    record.session_id,
                    InterviewState(session_id=record.session_id).model_dump_json(),
                    _iso(record.created_at),
                ),
            )
            await self._db.commit()
        return record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        async with self._db.execute(
            "SELECT session_id, created_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        async with self._db.execute(
            "SELECT COUNT(*) AS c FROM turns WHERE session_id = ?", (session_id,)
        ) as cursor:
            count_row = await cursor.fetchone()
        return SessionRecord(
            session_id=row["session_id"],
            created_at=_parse_dt(row["created_at"]),
            turn_count=int(count_row["c"]) if count_row else 0,
        )

    async def delete_session(self, session_id: str) -> bool:
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            await self._db.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            await self._db.execute(
                "DELETE FROM interview_state WHERE session_id = ?", (session_id,)
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def append_turn(self, turn: TurnRecord) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO turns (
                    session_id, turn_number, interviewer_text, response_json,
                    mode, domains_json, specialists_json, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.session_id,
                    turn.turn_number,
                    turn.interviewer_text,
                    turn.response.model_dump_json(),
                    turn.mode,
                    json.dumps(turn.domains),
                    json.dumps(turn.specialists),
                    turn.latency_ms,
                    _iso(turn.created_at),
                ),
            )
            await self._db.commit()

    async def list_turns(self, session_id: str) -> list[TurnRecord]:
        async with self._db.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_number ASC",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            TurnRecord(
                session_id=row["session_id"],
                turn_number=row["turn_number"],
                interviewer_text=row["interviewer_text"],
                response=InterviewResponse.model_validate_json(row["response_json"]),
                mode=row["mode"],
                domains=json.loads(row["domains_json"]),
                specialists=json.loads(row["specialists_json"]),
                latency_ms=row["latency_ms"],
                created_at=_parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    async def get_state(self, session_id: str) -> InterviewState | None:
        async with self._db.execute(
            "SELECT state_json FROM interview_state WHERE session_id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return InterviewState.model_validate_json(row["state_json"])

    async def save_state(self, state: InterviewState) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO interview_state (session_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (state.session_id, state.model_dump_json(), _iso(datetime.now(timezone.utc))),
            )
            await self._db.commit()
