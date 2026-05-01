from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sebastian.memory.resident.resident_dedupe import (
    canonical_bullet,
    canonical_json,
    normalize_memory_text,
    sha256_text,
    slot_value_dedupe_key,
)
from sebastian.store.models import ProfileMemoryRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESIDENT_PROFILE_ALLOWLIST = (
    "user.profile.name",
    "user.profile.location",
    "user.profile.occupation",
    "user.preference.language",
    "user.preference.response_style",
    "user.preference.addressing",
)

RESIDENT_MIN_CONFIDENCE = 0.8
MAX_CORE_PROFILE = 8
MAX_PINNED_NOTES = 10

_SCHEMA_VERSION = 1

# Instruction-injection patterns (raw content check)
_INJECTION_ROLE_PREFIX = re.compile(
    r"\b(system|developer|assistant|user)\s*:",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pydantic metadata model
# ---------------------------------------------------------------------------

SnapshotState = Literal["ready", "dirty", "rebuilding", "error"]


class ResidentSnapshotMetadata(BaseModel):
    schema_version: int = _SCHEMA_VERSION
    generated_at: str
    snapshot_state: SnapshotState
    generation_id: str
    source_max_updated_at: str | None
    markdown_hash: str
    record_hash: str
    source_record_ids: list[str]
    rendered_record_ids: list[str]
    rendered_dedupe_keys: list[str]
    rendered_canonical_bullets: list[str]
    record_count: int = 0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ResidentSnapshotReadResult:
    content: str
    rendered_record_ids: set[str] = field(default_factory=set)
    rendered_dedupe_keys: set[str] = field(default_factory=set)
    rendered_canonical_bullets: set[str] = field(default_factory=set)


_EMPTY_READ_RESULT = ResidentSnapshotReadResult(content="")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResidentSnapshotPaths:
    directory: Path
    markdown: Path
    metadata: Path

    @classmethod
    def from_user_data_dir(cls, user_data_dir: Path) -> ResidentSnapshotPaths:
        directory = user_data_dir / "memory"
        return cls(
            directory=directory,
            markdown=directory / "resident_snapshot.md",
            metadata=directory / "resident_snapshot.meta.json",
        )


# ---------------------------------------------------------------------------
# Async RW lock
# ---------------------------------------------------------------------------


class AsyncRWLock:
    """Async read/write lock.

    Multiple concurrent readers are allowed; a writer gets exclusive access.
    New readers that arrive while a writer holds the lock are blocked until
    the write side is released — the lock itself enforces this, not external flags.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers: int = 0
        self._writer: bool = False

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[None, None]:
        async with self._condition:
            while self._writer:
                await self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[None, None]:
        async with self._condition:
            while self._readers > 0 or self._writer:
                await self._condition.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()


# ---------------------------------------------------------------------------
# Pinned eligibility
# ---------------------------------------------------------------------------


def is_pinned_eligible(record: ProfileMemoryRecord) -> bool:
    """Check raw content (before normalization) for pinned safety criteria."""
    content = record.content

    # Source must be explicit or system_derived
    if record.source not in ("explicit", "system_derived"):
        return False

    # Content length check (raw)
    if len(content) > 300:
        return False

    # No Markdown heading marker
    if "#" in content:
        return False

    # No fenced code block
    if "```" in content:
        return False

    # No instruction language (role-prefixed or bare "ignore" directive)
    lower = content.lower().strip()
    if _INJECTION_ROLE_PREFIX.search(lower):
        return False
    if lower.startswith("ignore ") or lower == "ignore":
        return False

    return True


# ---------------------------------------------------------------------------
# Rendered snapshot result (internal)
# ---------------------------------------------------------------------------


@dataclass
class _RenderedSnapshot:
    markdown: str
    markdown_hash: str
    record_hash: str
    source_record_ids: list[str]
    rendered_record_ids: list[str]
    rendered_dedupe_keys: list[str]
    rendered_canonical_bullets: list[str]
    source_max_updated_at: str | None
    record_count: int


# ---------------------------------------------------------------------------
# Refresher
# ---------------------------------------------------------------------------


class ResidentMemorySnapshotRefresher:
    """Builds, caches, and serves the resident memory snapshot."""

    def __init__(
        self,
        paths: ResidentSnapshotPaths,
        db_factory: Any = None,
    ) -> None:
        self._paths = paths
        self._db_factory = db_factory
        self._lock = AsyncRWLock()
        self._snapshot_state: SnapshotState = "dirty"
        self._dirty_generation: int = 0
        self._writer_active: bool = False
        self._cached_metadata: ResidentSnapshotMetadata | None = None
        self._pending_refresh: asyncio.Task[None] | None = None

        # Test-only hooks
        self._before_publish_for_test: Callable[[], Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def read(self) -> ResidentSnapshotReadResult:
        """Return snapshot content if state is ready and hash matches; otherwise empty.

        Checks _writer_active BEFORE acquiring the read lock.  In asyncio's
        single-threaded model this is safe: if the flag is True the writer is
        still inside mutation_scope() (between DB commit and mark_dirty_locked),
        so serving the cached snapshot would be stale.
        """
        if self._writer_active:
            return _EMPTY_READ_RESULT

        async with self._lock.read():
            if self._snapshot_state != "ready":
                return _EMPTY_READ_RESULT

            meta = self._cached_metadata
            if meta is None:
                return _EMPTY_READ_RESULT

            # Check markdown file exists
            if not self._paths.markdown.exists():
                return _EMPTY_READ_RESULT

            # Validate hash
            try:
                md_bytes = self._paths.markdown.read_bytes()
            except OSError:
                return _EMPTY_READ_RESULT

            actual_hash = sha256_text(md_bytes.decode("utf-8"))
            if actual_hash != meta.markdown_hash:
                self.schedule_refresh()
                return _EMPTY_READ_RESULT

            return ResidentSnapshotReadResult(
                content=md_bytes.decode("utf-8"),
                rendered_record_ids=set(meta.rendered_record_ids),
                rendered_dedupe_keys=set(meta.rendered_dedupe_keys),
                rendered_canonical_bullets=set(meta.rendered_canonical_bullets),
            )

    async def rebuild(self, db_session: AsyncSession) -> None:
        """Query DB, filter, render, atomic write. Discards if generation changes."""
        observed_generation = self._dirty_generation

        rendered = await self._query_and_render(db_session)

        # Test hook: called just before the generation comparison
        if self._before_publish_for_test is not None:
            result = self._before_publish_for_test()
            if asyncio.iscoroutine(result):
                await result

        async with self._lock.write():
            if self._dirty_generation != observed_generation:
                # A mutation happened while we were rendering; schedule a fresh rebuild
                self.schedule_refresh()
                return
            await self._publish_ready(rendered)
            self._snapshot_state = "ready"

    @asynccontextmanager
    async def mutation_scope(self) -> AsyncGenerator[None, None]:
        """Write-lock scope for DB mutations. Required before mark_dirty_locked()."""
        async with self._lock.write():
            self._writer_active = True
            try:
                yield
            finally:
                self._writer_active = False

    async def mark_dirty_locked(self) -> None:
        """Increment dirty generation and write dirty state. Requires mutation_scope()."""
        if not self._writer_active:
            raise RuntimeError("mark_dirty_locked() requires mutation_scope()")
        self._dirty_generation += 1
        self._snapshot_state = "dirty"
        try:
            await self._write_empty_state("dirty")
        except OSError:
            logger.warning("resident_snapshot: failed to write dirty state to disk", exc_info=True)
        self.schedule_refresh()

    def schedule_refresh(self) -> None:
        """Schedule a background rebuild task (debounced: cancels pending)."""
        if self._pending_refresh is not None and not self._pending_refresh.done():
            self._pending_refresh.cancel()
        if self._db_factory is None:
            return
        self._pending_refresh = asyncio.create_task(self._background_rebuild())

    async def aclose(self) -> None:
        """Cancel any pending background task."""
        if self._pending_refresh is not None and not self._pending_refresh.done():
            self._pending_refresh.cancel()
            try:
                await self._pending_refresh
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Test backdoor
    # ------------------------------------------------------------------

    async def _publish_ready_for_test(
        self,
        markdown_text: str,
        rendered_record_ids: set[str],
    ) -> None:
        """Set snapshot to 'ready' state with given content. For test setup only."""
        md_bytes = markdown_text.encode("utf-8")
        md_hash = sha256_text(markdown_text)
        self._paths.directory.mkdir(parents=True, exist_ok=True)
        self._paths.markdown.write_bytes(md_bytes)

        meta = ResidentSnapshotMetadata(
            schema_version=_SCHEMA_VERSION,
            generated_at=datetime.now(UTC).isoformat(),
            snapshot_state="ready",
            generation_id="test-ready",
            source_max_updated_at=None,
            markdown_hash=md_hash,
            record_hash="sha256:test",
            source_record_ids=list(rendered_record_ids),
            rendered_record_ids=list(rendered_record_ids),
            rendered_dedupe_keys=[],
            rendered_canonical_bullets=[],
            record_count=len(rendered_record_ids),
        )
        self._cached_metadata = meta
        self._snapshot_state = "ready"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _query_and_render(self, db_session: AsyncSession) -> _RenderedSnapshot:
        """Query DB and produce rendered snapshot data."""
        now = datetime.now(UTC)

        stmt = (
            select(ProfileMemoryRecord)
            .where(
                ProfileMemoryRecord.scope == "user",
                ProfileMemoryRecord.subject_id == "owner",
                ProfileMemoryRecord.status == "active",
                ProfileMemoryRecord.confidence >= RESIDENT_MIN_CONFIDENCE,
            )
            .order_by(ProfileMemoryRecord.updated_at.desc())
        )
        result = await db_session.execute(stmt)
        all_records: list[ProfileMemoryRecord] = list(result.scalars().all())

        # Apply temporal and policy_tags filters
        def _passes_base_filters(rec: ProfileMemoryRecord) -> bool:
            tags = set(rec.policy_tags or [])
            if "do_not_auto_inject" in tags:
                return False
            if "needs_review" in tags:
                return False
            if "sensitive" in tags:
                return False
            if rec.valid_from is not None:
                valid_from = rec.valid_from
                if valid_from.tzinfo is None:
                    valid_from = valid_from.replace(tzinfo=UTC)
                if valid_from > now:
                    return False
            if rec.valid_until is not None:
                valid_until = rec.valid_until
                if valid_until.tzinfo is None:
                    valid_until = valid_until.replace(tzinfo=UTC)
                if valid_until <= now:
                    return False
            return True

        eligible = [r for r in all_records if _passes_base_filters(r)]

        # Separate into allowlisted and pinned candidates
        allowlist_set = set(RESIDENT_PROFILE_ALLOWLIST)
        allowlisted: list[ProfileMemoryRecord] = []
        pinned_only: list[ProfileMemoryRecord] = []

        for rec in eligible:
            in_allowlist = rec.slot_id in allowlist_set
            is_pinned = "pinned" in (rec.policy_tags or []) and is_pinned_eligible(rec)

            if in_allowlist:
                allowlisted.append(rec)
            elif is_pinned:
                pinned_only.append(rec)

        # Sort allowlisted: by allowlist order then updated_at DESC
        allowlist_order = {slot: i for i, slot in enumerate(RESIDENT_PROFILE_ALLOWLIST)}

        def _allowlist_sort_key(rec: ProfileMemoryRecord) -> tuple[int, timedelta]:
            order = allowlist_order.get(rec.slot_id, len(RESIDENT_PROFILE_ALLOWLIST))
            updated = rec.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            return (order, datetime(9999, 12, 31, tzinfo=UTC) - updated)

        allowlisted.sort(key=_allowlist_sort_key)

        # Sort pinned: confidence DESC then updated_at DESC
        def _pinned_sort_key(rec: ProfileMemoryRecord) -> tuple[float, timedelta]:
            updated = rec.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            return (-rec.confidence, datetime(9999, 12, 31, tzinfo=UTC) - updated)

        pinned_only.sort(key=_pinned_sort_key)

        # Global dedup state
        seen_ids: set[str] = set()
        seen_dedupe_keys: set[str] = set()
        seen_bullets: set[str] = set()

        def _try_add(rec: ProfileMemoryRecord) -> str | None:
            """Attempt to add a record, respecting dedup. Returns bullet text or None.

            Dedup order per spec (Section 8): record id → canonical bullet → slot_value key.
            """
            if rec.id in seen_ids:
                return None

            # Canonical bullet dedup (before slot_value per spec)
            normalized = normalize_memory_text(rec.content)
            bullet = canonical_bullet(normalized)
            if bullet in seen_bullets:
                return None

            # Slot-value dedupe key
            sv_key = slot_value_dedupe_key(
                subject_id=rec.subject_id,
                slot_id=rec.slot_id,
                structured_payload=rec.structured_payload,
            )
            if sv_key is not None and sv_key in seen_dedupe_keys:
                return None

            # Accept
            seen_ids.add(rec.id)
            if sv_key is not None:
                seen_dedupe_keys.add(sv_key)
            seen_bullets.add(bullet)
            return normalized

        # Build Core Profile (max 8)
        core_bullets: list[str] = []
        for rec in allowlisted:
            if len(core_bullets) >= MAX_CORE_PROFILE:
                break
            text = _try_add(rec)
            if text is not None:
                core_bullets.append(f"- Profile memory: {text}")

        # Build Pinned Notes (max 10)
        pinned_bullets: list[str] = []
        for rec in pinned_only:
            if len(pinned_bullets) >= MAX_PINNED_NOTES:
                break
            text = _try_add(rec)
            if text is not None:
                pinned_bullets.append(f"- Pinned memory: {text}")

        # Render markdown
        sections: list[str] = []
        if core_bullets:
            sections.append("### Core Profile\n" + "\n".join(core_bullets))
        if pinned_bullets:
            sections.append("### Pinned Notes\n" + "\n".join(pinned_bullets))

        if sections:
            markdown = "## Resident Memory\n\n" + "\n\n".join(sections) + "\n"
        else:
            markdown = ""

        # Compute hashes
        md_hash = sha256_text(markdown)
        source_ids = [r.id for r in all_records]

        def _record_fields(rec: ProfileMemoryRecord) -> dict[str, Any]:
            def _dt(d: datetime | None) -> str | None:
                if d is None:
                    return None
                return (d.replace(tzinfo=UTC) if d.tzinfo is None else d).isoformat()

            return {
                "id": rec.id,
                "content": rec.content,
                "slot_id": rec.slot_id,
                "kind": (
                    str(rec.kind.value)
                    if hasattr(rec.kind, "value")
                    else str(rec.kind)
                    if rec.kind
                    else None
                ),
                "confidence": float(rec.confidence) if rec.confidence is not None else None,
                "status": rec.status,
                "valid_from": _dt(rec.valid_from),
                "valid_until": _dt(rec.valid_until),
                "policy_tags": sorted(rec.policy_tags or []),
                "updated_at": _dt(rec.updated_at),
            }

        record_hash = sha256_text(
            canonical_json([_record_fields(r) for r in sorted(all_records, key=lambda r: r.id)])
        )

        # Source max updated_at
        source_max_updated_at: str | None = None
        if all_records:
            max_ts = max(
                (r.updated_at.replace(tzinfo=UTC) if r.updated_at.tzinfo is None else r.updated_at)
                for r in all_records
            )
            source_max_updated_at = max_ts.isoformat()

        return _RenderedSnapshot(
            markdown=markdown,
            markdown_hash=md_hash,
            record_hash=record_hash,
            source_record_ids=source_ids,
            rendered_record_ids=list(seen_ids),
            rendered_dedupe_keys=list(seen_dedupe_keys),
            rendered_canonical_bullets=list(seen_bullets),
            source_max_updated_at=source_max_updated_at,
            record_count=len(seen_ids),
        )

    async def _publish_ready(self, rendered: _RenderedSnapshot) -> None:
        """Atomic write: markdown → metadata. Must be called under write lock."""
        self._paths.directory.mkdir(parents=True, exist_ok=True)

        md_bytes = rendered.markdown.encode("utf-8")
        self._atomic_write(self._paths.markdown, md_bytes)

        meta = ResidentSnapshotMetadata(
            schema_version=_SCHEMA_VERSION,
            generated_at=datetime.now(UTC).isoformat(),
            snapshot_state="ready",
            generation_id=_make_id(),
            source_max_updated_at=rendered.source_max_updated_at,
            markdown_hash=rendered.markdown_hash,
            record_hash=rendered.record_hash,
            source_record_ids=rendered.source_record_ids,
            rendered_record_ids=rendered.rendered_record_ids,
            rendered_dedupe_keys=rendered.rendered_dedupe_keys,
            rendered_canonical_bullets=rendered.rendered_canonical_bullets,
            record_count=rendered.record_count,
        )
        meta_bytes = meta.model_dump_json(indent=2).encode("utf-8")
        self._atomic_write(self._paths.metadata, meta_bytes)
        self._cached_metadata = meta

    async def _write_empty_state(self, state: SnapshotState) -> None:
        """Write empty markdown and a minimal metadata file with the given state."""
        self._paths.directory.mkdir(parents=True, exist_ok=True)
        # Empty the markdown file first (atomic); metadata written after.
        # If this crashes before metadata is written the hash mismatch guard catches it.
        self._atomic_write(self._paths.markdown, b"")
        meta = ResidentSnapshotMetadata(
            schema_version=_SCHEMA_VERSION,
            generated_at=datetime.now(UTC).isoformat(),
            snapshot_state=state,
            generation_id=_make_id(),
            source_max_updated_at=None,
            markdown_hash=sha256_text(""),
            record_hash=sha256_text(""),
            source_record_ids=[],
            rendered_record_ids=[],
            rendered_dedupe_keys=[],
            rendered_canonical_bullets=[],
            record_count=0,
        )
        meta_bytes = meta.model_dump_json(indent=2).encode("utf-8")
        self._atomic_write(self._paths.metadata, meta_bytes)
        self._cached_metadata = meta

    @staticmethod
    def _atomic_write(dest: Path, data: bytes) -> None:
        """Write data to dest atomically via tmp file + rename."""
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    async def _background_rebuild(self) -> None:
        """Background task: open DB session and call rebuild()."""
        if self._db_factory is None:
            return
        try:
            async with self._db_factory() as session:
                await self.rebuild(session)
        except Exception as exc:
            logger.warning("resident_snapshot: background rebuild failed: %s", exc, exc_info=True)
            await self._write_error_state()

    async def _write_error_state(self) -> None:
        """Best-effort: write error state to disk and update in-memory state."""
        try:
            async with self._lock.write():
                await self._write_empty_state("error")
                self._snapshot_state = "error"
        except Exception:
            pass  # best-effort; in-memory state is already non-ready after rebuild failure


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _make_id() -> str:
    """Generate a simple unique ID (UUID4 hex)."""
    import uuid

    return uuid.uuid4().hex
