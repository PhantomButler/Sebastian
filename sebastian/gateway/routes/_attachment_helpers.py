"""Shared attachment validation helpers for turn and session creation endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from sebastian.store.models import AttachmentRecord


async def validate_and_write_attachment_turn(
    *,
    content: str,
    attachment_ids: list[str],
    session_id: str,
    agent_type: str,
) -> tuple[list[Any], str, int]:
    """Validate attachment IDs and write user turn + attachment timeline items atomically.

    Steps (all validation before any DB write):
    1. Validate content/attachment_ids: at least one is required.
    2. Validate attachment count ≤ 5.
    3. validate_attachable → get attachment records.
    4. Check image support if any image attachments.
    5. Check text token budget if any text_file attachments.
    6. Write turn + attachments atomically.

    Returns (attachment_records, exchange_id, exchange_index).
    Raises HTTPException on validation failure.
    """
    import sebastian.gateway.state as state

    # Step 1: at least content or attachments
    if not content.strip() and not attachment_ids:
        raise HTTPException(400, "content or attachment_ids required")

    # Step 2: max 5 attachments
    if len(attachment_ids) > 5:
        raise HTTPException(400, "max 5 attachments per turn")

    if state.attachment_store is None:
        raise HTTPException(503, "attachment service unavailable")

    attachment_store = state.attachment_store

    # Step 3: validate attachable
    from sebastian.store.attachments import AttachmentConflictError, AttachmentNotFoundError

    try:
        attachment_records: list[AttachmentRecord] = await attachment_store.validate_attachable(
            attachment_ids
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AttachmentConflictError as exc:
        raise HTTPException(409, str(exc)) from exc

    # Step 4: image support check
    has_image = any(r.kind == "image" for r in attachment_records)
    if has_image:
        try:
            resolved = await state.llm_registry.get_provider(agent_type)
        except RuntimeError:
            resolved = None
        if resolved is not None and not resolved.supports_image_input:
            raise HTTPException(400, "current model does not support image input")

    # Step 5: text token budget
    text_records = [r for r in attachment_records if r.kind == "text_file"]
    if text_records:
        from sebastian.context.estimator import TokenEstimator

        estimator = TokenEstimator()
        total_tokens = 0
        for r in text_records:
            text = await asyncio.to_thread(attachment_store.read_text_content, r)
            total_tokens += estimator.estimate_text(text)
        if total_tokens > 100_000:
            raise HTTPException(400, "text attachments exceed token budget")

    # Step 6: write atomically
    try:
        exchange_id, exchange_index = await state.session_store.append_user_turn_with_attachments(
            session_id=session_id,
            agent_type=agent_type,
            content=content,
            attachment_records=attachment_records,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return attachment_records, exchange_id, exchange_index
