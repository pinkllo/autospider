"""Planning service."""

from __future__ import annotations

from typing import Any, Callable

from ..contracts import ExecutionRequest
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

    async def execute(self, *, request: ExecutionRequest) -> dict[str, Any]:
        if self._session_options_builder is None:
            session_options = {
                "headless": request.headless,
                "guard_intervention_mode": request.guard_intervention_mode,
                "guard_thread_id": request.guard_thread_id,
                "budget_key": request.execution_id or request.guard_thread_id,
                "global_browser_budget": request.global_browser_budget,
            }
        else:
            session_options = self._session_options_builder(
                {"thread_id": request.guard_thread_id},
                request.model_dump(mode="python"),
            )

        planner_session = self._browser_session_cls(**session_options)
        await planner_session.start()
        try:
            runtime = self._skill_runtime_cls()
            planner = self._planner_cls(
                page=planner_session.page,
                site_url=request.site_url or request.list_url,
                user_request=request.request or request.task_description,
                output_dir=request.output_dir,
            )
            planner_url = request.site_url or request.list_url
            selected_skill_meta = (
                await runtime.get_or_select(
                    phase="planner",
                    url=planner_url,
                    task_context={
                        "request": request.request or request.task_description,
                        "fields": list(request.fields or []),
                    },
                    llm=planner.llm,
                    preselected_skills=list(request.selected_skills or []),
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

        fields = list(request.fields or [])
        plan.shared_fields = fields
        plan.total_subtasks = len(plan.subtasks)
        plan_knowledge = planner.render_plan_knowledge(plan)
        return {
            "task_plan": plan,
            "plan_knowledge": plan_knowledge,
            "summary": {"total_subtasks": len(plan.subtasks)},
            "planner_status": str(getattr(planner, "planner_status", "success") or "success"),
            "terminal_reason": str(getattr(planner, "terminal_reason", "") or ""),
            "selected_skills": list(planner.selected_skills or []),
            "result": {"task_plan": plan},
        }
