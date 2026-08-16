"""Storage interface.

SQLite is the MVP implementation. Anything that satisfies this protocol —
Postgres, Redis — can replace it without touching the orchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.interview import InterviewState, SessionRecord, TurnRecord


class SessionStore(ABC):
    @abstractmethod
    async def init(self) -> None:
        """Create schema / open connections. Safe to call more than once."""

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def create_session(self, session_id: str) -> SessionRecord: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> SessionRecord | None: ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool: ...

    @abstractmethod
    async def append_turn(self, turn: TurnRecord) -> None: ...

    @abstractmethod
    async def list_turns(self, session_id: str) -> list[TurnRecord]: ...

    @abstractmethod
    async def get_state(self, session_id: str) -> InterviewState | None: ...

    @abstractmethod
    async def save_state(self, state: InterviewState) -> None: ...


class PersistenceError(RuntimeError):
    """Raised when a write fails.

    The orchestrator degrades to an in-memory answer and flags the response so
    the UI can say continuity may be lost, rather than pretending it is intact.
    """
