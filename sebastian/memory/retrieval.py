from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# Keywords that trigger episode lane
EPISODE_LANE_KEYWORDS = ["上次", "讨论", "之前", "记得", "last time", "remember", "we discussed"]
MAX_TOTAL_ITEMS = 8
DO_NOT_AUTO_INJECT_TAG = "do_not_auto_inject"


class RetrievalContext(BaseModel):
    subject_id: str
    session_id: str
    agent_type: str
    user_message: str
    access_purpose: str = "context_injection"


class RetrievalPlan(BaseModel):
    profile_lane: bool = True
    episode_lane: bool = False
    profile_limit: int = 5
    episode_limit: int = 3


class MemoryRetrievalPlanner:
    def plan(self, context: RetrievalContext) -> RetrievalPlan:
        """Determine which retrieval lanes to activate."""
        msg = context.user_message.lower()
        episode_lane = any(kw in msg for kw in EPISODE_LANE_KEYWORDS)
        return RetrievalPlan(
            profile_lane=True,
            episode_lane=episode_lane,
            profile_limit=5,
            episode_limit=3,
        )


class MemorySectionAssembler:
    def assemble(
        self,
        *,
        profile_records: list[Any],
        episode_records: list[Any],
        plan: RetrievalPlan,
    ) -> str:
        """Build memory context string for system prompt injection."""
        # 1. Filter out do_not_auto_inject records from both lists
        filtered_profiles = [
            r for r in profile_records if DO_NOT_AUTO_INJECT_TAG not in r.policy_tags
        ]
        filtered_episodes = [
            r for r in episode_records if DO_NOT_AUTO_INJECT_TAG not in r.policy_tags
        ]

        # 2. Apply per-lane limits
        filtered_profiles = filtered_profiles[: plan.profile_limit]
        filtered_episodes = filtered_episodes[: plan.episode_limit]

        # 3. Cap total to MAX_TOTAL_ITEMS
        total = len(filtered_profiles) + len(filtered_episodes)
        if total > MAX_TOTAL_ITEMS:
            overflow = total - MAX_TOTAL_ITEMS
            # Trim episodes first, then profiles
            episode_trim = min(overflow, len(filtered_episodes))
            filtered_episodes = filtered_episodes[: len(filtered_episodes) - episode_trim]
            overflow -= episode_trim
            if overflow > 0:
                filtered_profiles = filtered_profiles[: len(filtered_profiles) - overflow]

        # 4. Build sections
        sections: list[str] = []

        if filtered_profiles:
            lines = "\n".join(
                f"- [{r.kind}] {r.content}" for r in filtered_profiles
            )
            sections.append(f"## What I know about the user\n{lines}")

        if filtered_episodes:
            lines = "\n".join(f"- {r.content}" for r in filtered_episodes)
            sections.append(f"## Relevant past episodes\n{lines}")

        # 5. Join non-empty sections; return "" if none
        return "\n\n".join(sections)


async def retrieve_memory_section(
    context: RetrievalContext,
    *,
    db_session: AsyncSession,
) -> str:
    """Full retrieval pipeline: plan → fetch → assemble → return string."""
    from sebastian.memory.episode_store import EpisodeMemoryStore
    from sebastian.memory.profile_store import ProfileMemoryStore

    planner = MemoryRetrievalPlanner()
    plan = planner.plan(context)

    profile_store = ProfileMemoryStore(db_session)
    episode_store = EpisodeMemoryStore(db_session)

    profile_records: list[Any] = []
    if plan.profile_lane:
        profile_records = await profile_store.search_active(
            subject_id=context.subject_id,
            limit=plan.profile_limit,
        )

    episode_records: list[Any] = []
    if plan.episode_lane:
        episode_records = await episode_store.search(
            query=context.user_message,
            subject_id=context.subject_id,
            limit=plan.episode_limit,
        )

    assembler = MemorySectionAssembler()
    return assembler.assemble(
        profile_records=profile_records,
        episode_records=episode_records,
        plan=plan,
    )
