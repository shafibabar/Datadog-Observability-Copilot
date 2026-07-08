"""The Workspace store: SQLite-backed, append-with-history persistence.

The Workspace is a *real, persisted, versioned* investigation-state model — not
something reconstructed from chat history. Every `record()` writes a new
immutable snapshot (the full Investigation, serialized), so prior reasoning is
never destroyed and the evolution of the investigation stays visible. Reasoning
objects are also flattened into a queryable table, and each hypothesis's
confidence is logged per snapshot so its movement over time is retrievable.

No secrets are ever written here (kickoff: secrets never persist to the DB).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.reasoning.models import Confidence, Investigation
from app.telemetry.models import Scope
from app.workspace.sections import hypothesis_key


@dataclass(frozen=True)
class WorkspaceMeta:
    id: str
    incident_id: str
    source_type: str
    created_at: datetime
    title: str = ""
    updated_at: datetime | None = None


class Message(BaseModel):
    id: str
    workspace_id: str
    seq: int
    role: str  # "user" | "assistant"
    content: str
    persona: str | None = None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    source_type: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class Snapshot(BaseModel):
    id: str
    workspace_id: str
    seq: int
    question: str | None
    investigation: Investigation
    created_at: datetime


class ReasoningRecord(BaseModel):
    kind: str  # fact | hypothesis | recommendation | unknown
    claim: str
    confidence: Confidence
    evidence: list[str]
    snapshot_seq: int


class ConfidencePoint(BaseModel):
    seq: int
    confidence: Confidence
    created_at: datetime


_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT '',
    scope_json  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    persona      TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, seq)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    question     TEXT,
    state_json   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, seq)
);
CREATE TABLE IF NOT EXISTS reasoning_objects (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    snapshot_seq INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    claim        TEXT NOT NULL,
    confidence   TEXT NOT NULL,
    evidence     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confidence_history (
    id             TEXT PRIMARY KEY,
    workspace_id   TEXT NOT NULL,
    hypothesis_key TEXT NOT NULL,
    snapshot_seq   INTEGER NOT NULL,
    confidence     TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        # Ensure the parent directory exists for file-backed databases.
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so the single demo process can share the
        # connection across FastAPI's threadpool. An in-memory DB lives only as
        # long as this connection, which is exactly the per-test lifetime we want.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Additive migrations for DBs created by an earlier schema. `CREATE TABLE
        IF NOT EXISTS` won't add a column to an existing table, so add any missing
        ones here (idempotent)."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(workspaces)")}
        if "scope_json" not in cols:
            self._conn.execute(
                "ALTER TABLE workspaces ADD COLUMN scope_json TEXT NOT NULL DEFAULT ''"
            )

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    # --- lifecycle ---------------------------------------------------------

    def create_workspace(
        self, incident_id: str, source_type: str, title: str = ""
    ) -> str:
        wid = uuid.uuid4().hex
        now = _now().isoformat()
        self._conn.execute(
            "INSERT INTO workspaces (id, incident_id, source_type, created_at, title, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (wid, incident_id, source_type, now, title, now),
        )
        self._conn.commit()
        return wid

    def get_workspace(self, workspace_id: str) -> WorkspaceMeta:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"No workspace {workspace_id!r}")
        return WorkspaceMeta(
            id=row["id"],
            incident_id=row["incident_id"],
            source_type=row["source_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
            title=row["title"],
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def set_title(self, workspace_id: str, title: str) -> None:
        self._conn.execute(
            "UPDATE workspaces SET title = ? WHERE id = ?", (title, workspace_id)
        )
        self._conn.commit()

    def get_scope(self, workspace_id: str) -> Scope | None:
        """The investigation lens persisted for this conversation, or None if it
        was never set."""
        row = self._conn.execute(
            "SELECT scope_json FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"No workspace {workspace_id!r}")
        raw = row["scope_json"]
        return Scope.model_validate_json(raw) if raw else None

    def set_scope(self, workspace_id: str, scope: Scope) -> None:
        self._conn.execute(
            "UPDATE workspaces SET scope_json = ? WHERE id = ?",
            (scope.model_dump_json(), workspace_id),
        )
        self._conn.commit()

    def delete_workspace(self, workspace_id: str) -> None:
        """Remove a conversation and all of its history (messages, snapshots,
        reasoning objects, confidence points). Idempotent."""
        for table in ("confidence_history", "reasoning_objects", "snapshots", "messages"):
            self._conn.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (workspace_id,))
        self._conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        self._conn.commit()

    def _touch(self, workspace_id: str, when: datetime) -> None:
        """Bump a conversation's last-activity time so listings sort by recency."""
        self._conn.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?",
            (when.isoformat(), workspace_id),
        )

    # --- conversations (workspace + messages) -----------------------------

    def add_message(
        self, workspace_id: str, role: str, content: str, persona: str | None = None
    ) -> Message:
        created = _now()
        seq = self._next_message_seq(workspace_id)
        mid = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO messages (id, workspace_id, seq, role, content, persona, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, workspace_id, seq, role, content, persona, created.isoformat()),
        )
        self._touch(workspace_id, created)
        self._conn.commit()
        return Message(
            id=mid, workspace_id=workspace_id, seq=seq, role=role,
            content=content, persona=persona, created_at=created,
        )

    def get_messages(self, workspace_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE workspace_id = ? ORDER BY seq ASC",
            (workspace_id,),
        ).fetchall()
        return [
            Message(
                id=r["id"], workspace_id=r["workspace_id"], seq=r["seq"],
                role=r["role"], content=r["content"], persona=r["persona"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def list_conversations(self) -> list[ConversationSummary]:
        rows = self._conn.execute(
            "SELECT w.*, "
            "  (SELECT COUNT(*) FROM messages m WHERE m.workspace_id = w.id) AS message_count "
            "FROM workspaces w ORDER BY w.updated_at DESC, w.created_at DESC"
        ).fetchall()
        return [
            ConversationSummary(
                id=r["id"],
                title=r["title"],
                source_type=r["source_type"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"] or r["created_at"]),
                message_count=r["message_count"],
            )
            for r in rows
        ]

    def _next_message_seq(self, workspace_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM messages WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return int(row["m"]) + 1

    # --- append-with-history ----------------------------------------------

    def record(self, workspace_id: str, investigation: Investigation) -> Snapshot:
        """Append an immutable snapshot of the investigation. Never overwrites."""
        created = _now()
        seq = self._next_seq(workspace_id)
        sid = uuid.uuid4().hex

        self._conn.execute(
            "INSERT INTO snapshots (id, workspace_id, seq, question, state_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                sid,
                workspace_id,
                seq,
                investigation.question,
                investigation.model_dump_json(),
                created.isoformat(),
            ),
        )
        self._index_reasoning(workspace_id, seq, investigation, created)
        self._touch(workspace_id, created)
        self._conn.commit()

        return Snapshot(
            id=sid,
            workspace_id=workspace_id,
            seq=seq,
            question=investigation.question,
            investigation=investigation,
            created_at=created,
        )

    def _next_seq(self, workspace_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM snapshots WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return int(row["m"]) + 1

    def _index_reasoning(
        self, workspace_id: str, seq: int, inv: Investigation, created: datetime
    ) -> None:
        ts = created.isoformat()

        def insert_obj(kind: str, claim: str, confidence: Confidence, evidence: list[str]):
            self._conn.execute(
                "INSERT INTO reasoning_objects "
                "(id, workspace_id, snapshot_seq, kind, claim, confidence, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex, workspace_id, seq, kind, claim,
                    confidence.value, json.dumps(evidence), ts,
                ),
            )

        for f in inv.facts:
            insert_obj("fact", f.claim, f.confidence, f.evidence)
        for r in inv.recommendations:
            insert_obj("recommendation", r.claim, r.confidence, r.evidence)
        for u in inv.unknowns:
            insert_obj("unknown", u.claim, u.confidence, u.evidence)
        for h in inv.hypotheses:
            insert_obj("hypothesis", h.statement, h.confidence, h.supporting_evidence)
            self._conn.execute(
                "INSERT INTO confidence_history "
                "(id, workspace_id, hypothesis_key, snapshot_seq, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex, workspace_id, hypothesis_key(h.statement),
                    seq, h.confidence.value, ts,
                ),
            )

    # --- reads -------------------------------------------------------------

    def latest(self, workspace_id: str) -> Snapshot | None:
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE workspace_id = ? ORDER BY seq DESC LIMIT 1",
            (workspace_id,),
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def history(self, workspace_id: str) -> list[Snapshot]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE workspace_id = ? ORDER BY seq ASC",
            (workspace_id,),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def reasoning_objects(
        self, workspace_id: str, snapshot_seq: int | None = None
    ) -> list[ReasoningRecord]:
        sql = "SELECT * FROM reasoning_objects WHERE workspace_id = ?"
        params: list[object] = [workspace_id]
        if snapshot_seq is not None:
            sql += " AND snapshot_seq = ?"
            params.append(snapshot_seq)
        sql += " ORDER BY snapshot_seq ASC"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            ReasoningRecord(
                kind=r["kind"],
                claim=r["claim"],
                confidence=Confidence(r["confidence"]),
                evidence=json.loads(r["evidence"]),
                snapshot_seq=r["snapshot_seq"],
            )
            for r in rows
        ]

    def confidence_history(
        self, workspace_id: str, hypothesis_key: str
    ) -> list[ConfidencePoint]:
        rows = self._conn.execute(
            "SELECT * FROM confidence_history "
            "WHERE workspace_id = ? AND hypothesis_key = ? ORDER BY snapshot_seq ASC",
            (workspace_id, hypothesis_key),
        ).fetchall()
        return [
            ConfidencePoint(
                seq=r["snapshot_seq"],
                confidence=Confidence(r["confidence"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            id=row["id"],
            workspace_id=row["workspace_id"],
            seq=row["seq"],
            question=row["question"],
            investigation=Investigation.model_validate_json(row["state_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
