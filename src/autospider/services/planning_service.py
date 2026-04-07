"""Planning service."""

from __future__ import annotations

from typing import Any, Callable

from ..common.browser import BrowserSession
from ..common.experience import SkillRuntime
from ..crawler.planner import TaskPlanner


class PlanningService:
    """Coordinates planner session lifecycle and skill selection."""

    def __init__(
        self,
        *,
        browser_session_cls: type = BrowserSession,
        skill_runtime_cls: type = SkillRuntime,
        planner_cls: type = TaskPlanner,
        session_options_builder: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._browser_session_cls = browser_session_cls
        self._skill_runtime_cls = skill_runtime_cls
        self._planner_cls = planner_cls
        self._session_options_builder = session_options_builder

    async def execute(self, *, params: dict[str, Any], thread_id: str) -> dict[str, Any]:
        if self._session_options_builder is None:
            session_options = {
                "headless": bool(params.get("headless", False)),
                "guard_intervention_mode": "interrupt",
                "guard_thread_id": thread_id,
            }
        else:
            session_options = self._session_options_builder({"thread_id": thread_id}, params)

        planner_session = self._browser_session_cls(**session_options)
        await planner_session.start()
        try:
            runtime = self._skill_runtime_cls()
            planner = self._planner_cls(
                page=planner_session.page,
                site_url=str(params.get("site_url") or params.get("list_url") or ""),
                user_request=str(params.get("request") or params.get("task_description") or ""),
                output_dir=str(params.get("output_dir") or "output"),
            )
            planner_url = str(params.get("site_url") or params.get("list_url") or "")
            selected_skill_meta = (
                await runtime.get_or_select(
                    phase="planner",
                    url=planner_url,
                    task_context={
                        "request": str(params.get("request") or params.get("task_description") or ""),
                        "fields": list(params.get("fields") or []),
                    },
                    llm=planner.llm,
                    preselected_skills=list(params.get("selected_skills") or []),
                )
                if planner_url
                else []
            )
            planner.selected_skills = [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill.path,
                    "domain": skill.domain,
                }
                for skill in selected_skill_meta
            ]
            planner.selected_skills_context = runtime.format_selected_skills_context(
                runtime.load_selected_bodies(selected_skill_meta)
            )
            plan = await planner.plan()
        finally:
            await planner_session.stop()

        fields = list(params.get("fields") or [])
        plan.shared_fields = fields
        plan.total_subtasks = len(plan.subtasks)
        plan_knowledge = planner.render_plan_knowledge(plan)
        return {
            "task_plan": plan,
            "plan_knowledge": plan_knowledge,
            "summary": {"total_subtasks": len(plan.subtasks)},
            "selected_skills": list(planner.selected_skills or []),
            "result": {"task_plan": plan},
        }
