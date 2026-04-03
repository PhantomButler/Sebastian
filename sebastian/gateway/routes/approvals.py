from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from sebastian.gateway.auth import require_auth
from sebastian.store.models import ApprovalRecord

router = APIRouter(tags=["approvals"])


@router.get("/approvals")
async def list_approvals(_auth: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    import sebastian.gateway.state as state

    async with state.db_factory() as session:
        result = await session.execute(
            select(ApprovalRecord).where(ApprovalRecord.status == "pending")
        )
        records = result.scalars().all()
    return {
        "approvals": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "taskId": r.task_id,
                "session_id": r.session_id,
                "tool_name": r.tool_name,
                "tool_input": r.tool_input,
                "description": _approval_description(r.tool_name, r.tool_input),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "requestedAt": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@router.post("/approvals/{approval_id}/grant")
async def grant_approval(
    approval_id: str,
    _auth: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state

    await _resolve(approval_id, granted=True, state=state)
    return {"approval_id": approval_id, "granted": True}


@router.post("/approvals/{approval_id}/deny")
async def deny_approval(
    approval_id: str,
    _auth: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    import sebastian.gateway.state as state

    await _resolve(approval_id, granted=False, state=state)
    return {"approval_id": approval_id, "granted": False}


async def _resolve(approval_id: str, granted: bool, state: Any) -> None:
    async with state.db_factory() as session:
        result = await session.execute(
            select(ApprovalRecord).where(ApprovalRecord.id == approval_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        record.status = "granted" if granted else "denied"
        record.resolved_at = datetime.now(UTC)
        await session.commit()
    await state.conversation.resolve_approval(approval_id, granted)


def _approval_description(tool_name: str, tool_input: dict[str, Any]) -> str:
    rendered_input = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    return f"{tool_name}: {rendered_input}"
