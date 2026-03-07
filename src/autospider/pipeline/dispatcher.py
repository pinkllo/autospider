"""多子任务并行调度器。

协调多个子任务的并行执行，提供：
- 信号量并发控制
- 进度持久化与中断恢复
- 失败重试与熔断
- 执行阶段模型主动申请升级为 Planner 并动态追加子任务
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..common.browser import BrowserSession
from ..common.config import config
from ..common.logger import get_logger
from ..common.protocol import coerce_bool, parse_json_dict_from_llm
from ..common.types import SubTask, SubTaskStatus, TaskPlan
from ..common.utils.paths import get_prompt_path
from ..common.utils.prompt_template import render_template
from ..crawler.planner import TaskPlanner
from .worker import SubTaskWorker

logger = get_logger(__name__)

_DISPATCH_LOOP_GUARD = 100
_PLANNER_PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")


class TaskDispatcher:
    """多子任务并行调度器。"""

    def __init__(
        self,
        plan: TaskPlan,
        fields: list[dict],
        output_dir: str = "output",
        headless: bool = False,
        max_concurrent: int | None = None,
        enable_runtime_subtasks: bool | None = None,
        runtime_subtask_max_depth: int | None = None,
        runtime_subtask_max_children: int | None = None,
        runtime_subtasks_use_main_model: bool | None = None,
    ):
        """初始化多子任务并行调度器。
        
        Args:
            plan (TaskPlan): 任务执行计划，包含初始子任务列表。
            fields (list[dict]): 需要从目标资源页面提取并保存的字段定义组合。
            output_dir (str): 爬取结果及中间态文件的保存目录。
            headless (bool): 运行时是否启用无头浏览器模式。
            max_concurrent (int | None): 最大并行子任务数如果未传将使用 Config 配置。
            enable_runtime_subtasks (bool | None): 是否允许在执行时临时派生出新的子任务进行扩展。
            runtime_subtask_max_depth (int | None): 运行时扩充分支任务时允许的最大深度。
            runtime_subtask_max_children (int | None): 每个需扩充任务允许生成的最多子任务数量。
            runtime_subtasks_use_main_model (bool | None): 运行时扩充时是否强制使用主模型进行任务推断。
        """
        self.plan = plan
        self.fields = fields
        self.output_dir = output_dir
        self.headless = headless

        max_conc = max_concurrent or config.planner.max_concurrent_subtasks
        self.semaphore = asyncio.Semaphore(max_conc)
        self.progress_path = Path(output_dir) / config.planner.progress_file

        self.max_subtask_retries = config.planner.max_subtask_retries
        self.runtime_subtasks_enabled = (
            config.planner.runtime_subtasks_enabled
            if enable_runtime_subtasks is None
            else bool(enable_runtime_subtasks)
        )
        self.runtime_subtasks_max_depth = int(
            runtime_subtask_max_depth
            if runtime_subtask_max_depth is not None
            else config.planner.runtime_subtasks_max_depth
        )
        self.runtime_subtasks_max_children = int(
            runtime_subtask_max_children
            if runtime_subtask_max_children is not None
            else config.planner.runtime_subtasks_max_children
        )
        self.runtime_subtasks_use_main_model = (
            config.planner.runtime_subtasks_use_main_model
            if runtime_subtasks_use_main_model is None
            else bool(runtime_subtasks_use_main_model)
        )

        self._lock = asyncio.Lock()
        self._plan_lock = asyncio.Lock()
        self._started_at = datetime.now()
        self._plan_agent_llm: ChatOpenAI | None = None
        self._known_signatures: set[tuple[str, str, str]] = {
            self._task_signature(st) for st in self.plan.subtasks
        }

    async def run(self) -> dict:
        """开始执行所有计划中的子任务（支持执行中动态追加）。
        
        Returns:
            dict: 包含了所有任务成功、失败、跳过、总计数的运行摘要字典。
        """
        # 读取本地进度，支持断点续传
        self._load_progress()

        loop_count = 0
        while True:
            # 扫描队列里可以运行的任务（处于等待状态且未超重试上限）
            runnable = self._get_runnable_subtasks()
            if not runnable:
                break

            loop_count += 1
            # 设置保护阈值，强制中断可能出现的异常循环
            if loop_count > _DISPATCH_LOOP_GUARD:
                logger.warning("[Dispatcher] 达到循环保护上限 %d，提前结束", _DISPATCH_LOOP_GUARD)
                break

            logger.info(
                "[Dispatcher] 第 %d 轮：%d 个子任务待执行（并发上限 %d）",
                loop_count,
                len(runnable),
                self.semaphore._value,
            )

            tasks = [self._run_subtask(st) for st in runnable]
            await asyncio.gather(*tasks, return_exceptions=True)

        summary = self._build_summary()
        logger.info(
            "[Dispatcher] 全部完成: 成功 %d / 失败 %d / 跳过 %d / 总计 %d",
            summary["completed"],
            summary["failed"],
            summary["skipped"],
            summary["total"],
        )
        return summary

    def _get_runnable_subtasks(self) -> list[SubTask]:
        """获取并根据优先级和 id 对可执行任务进行排序过滤。"""
        return sorted(
            [st for st in self.plan.subtasks if self._is_runnable(st)],
            key=lambda st: (st.priority, st.id),
        )

    def _is_runnable(self, subtask: SubTask) -> bool:
        """判断单个子任务是否还允许发起运行调度。"""
        if subtask.status == SubTaskStatus.PENDING:
            return True
        if subtask.status == SubTaskStatus.FAILED and subtask.retry_count < self.max_subtask_retries:
            return True
        return False

    async def _run_subtask(self, subtask: SubTask) -> None:
        """执行具体的子任务操作：封装限流与容错机制。"""
        # 利用信号量进行并发数量控制
        async with self.semaphore:
            logger.info("[Dispatcher] 开始子任务: %s (%s)", subtask.name, subtask.id)

            subtask.status = SubTaskStatus.RUNNING
            subtask.error = None
            # 标记运行中状态，存盘
            await self._save_progress()

            worker = SubTaskWorker(
                subtask=subtask,
                fields=self.fields,
                output_dir=self.output_dir,
                headless=self.headless,
            )

            try:
                # 设置 Worker 级别的整体超时避免死滞
                timeout = config.planner.subtask_timeout_minutes * 60
                result = await asyncio.wait_for(worker.execute(), timeout=timeout)

                # 更新从 Worker 获取的最新数据状态
                subtask.collected_count = int(result.get("total_urls", 0) or 0)
                subtask.result_file = result.get("items_file", "")
                pipeline_error = str(result.get("error") or "").strip()
                plan_upgrade_request = result.get("plan_upgrade_request")

                # 如果执行过程 Worker(大模型) 认为任务难度偏高并主动请求重新规划和指派升级为 Planner
                if isinstance(plan_upgrade_request, dict) and bool(plan_upgrade_request.get("requested")):
                    reason = str(plan_upgrade_request.get("reason") or "").strip()
                    if not self.runtime_subtasks_enabled:
                        # 如未允许运行时动态计划任务，则直接认为失败
                        subtask.status = SubTaskStatus.FAILED
                        subtask.error = "plan_upgrade_requested_but_runtime_subtasks_disabled"
                        logger.warning(
                            "[Dispatcher] 子任务请求升级为 Planner，但当前未启用运行时子任务：%s",
                            subtask.name,
                        )
                    else:
                        # 执行从现有任务重新展开和扩展为更多细分任务的过程
                        added, decision_text = await self._expand_subtasks_from_plan_request(
                            parent=subtask,
                            reason=reason,
                        )
                        if added > 0:
                            # 细分拆解成功，自己跳过执行，后续将由新放入队列的任务来处理
                            subtask.status = SubTaskStatus.SKIPPED
                            subtask.error = decision_text[:500]
                            logger.info(
                                "[Dispatcher] 子任务 %s 已升级为 Planner，新增 %d 个子任务",
                                subtask.name,
                                added,
                            )
                        else:
                            # 拆分被拒绝或者没法产出更进一步的子目标，任务作失败处理
                            subtask.status = SubTaskStatus.FAILED
                            subtask.error = (
                                decision_text[:500]
                                if decision_text
                                else "plan_upgrade_requested_but_no_subtasks_generated"
                            )
                            logger.warning(
                                "[Dispatcher] 子任务 %s 请求升级，但未通过上层审批或未生成新子任务",
                                subtask.name,
                            )
                elif pipeline_error:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = f"pipeline_error: {pipeline_error}"[:500]
                    logger.warning("[Dispatcher] ✗ 子任务失败: %s — %s", subtask.name, subtask.error)
                elif subtask.collected_count <= 0:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = "no_data_collected"
                    logger.warning("[Dispatcher] ✗ 子任务失败: %s — 未采集到任何记录", subtask.name)
                else:
                    subtask.status = SubTaskStatus.COMPLETED
                    logger.info(
                        "[Dispatcher] ✓ 子任务完成: %s, 采集 %d 条",
                        subtask.name,
                        subtask.collected_count,
                    )

            except asyncio.TimeoutError:
                subtask.error = f"超时 ({config.planner.subtask_timeout_minutes}分钟)"
                self._handle_failure(subtask)
                logger.warning("[Dispatcher] ⏰ 子任务超时: %s", subtask.name)

            except Exception as e:
                subtask.error = str(e)[:500]
                self._handle_failure(subtask)
                logger.error("[Dispatcher] ✗ 子任务失败: %s — %s", subtask.name, e)

            await self._save_progress()

    async def _expand_subtasks_from_plan_request(self, parent: SubTask, reason: str) -> tuple[int, str]:
        """基于执行阶段抛出的重规划请求，评估并扩展出子任务。
        
        Args:
            parent: 请求升级的原受阻子任务。
            reason: Worker 给出的扩展理由。
            
        Returns:
            tuple[int, str]: 成功扩充的数量及过程诊断日志信息。
        """
        # 防止反复进入同一个任务规划（例如模型循环要求细化）
        if parent.runtime_plan_attempted:
            return 0, "plan_agent_review_skipped: runtime_plan_already_attempted"
        
        # 限制无限次的递归细化层级
        if int(parent.depth or 0) >= self.runtime_subtasks_max_depth:
            logger.info(
                "[Dispatcher] 子任务 %s 达到运行时规划深度上限 (%d)，忽略升级请求",
                parent.id,
                self.runtime_subtasks_max_depth,
            )
            return 0, "plan_agent_rejected: runtime_subtasks_max_depth_reached"

        parent.runtime_plan_attempted = True
        # 交给上级高模型去审查该拆解请求，由 LLM 提供是否通过的最终审阅结果
        approved, review_reason, refined_request = await self._ask_plan_agent_review(
            parent=parent,
            reason=reason,
        )
        if not approved:
            message = f"plan_agent_rejected: {review_reason}".strip()
            return 0, message[:500]

        planned = await self._plan_runtime_subtasks(
            parent=parent,
            reason=reason,
            planner_request_override=refined_request,
        )
        if not planned:
            message = f"plan_agent_approved_but_no_subtasks_generated: {review_reason}".strip()
            return 0, message[:500]

        added = await self._append_runtime_subtasks(parent=parent, candidates=planned)
        if added <= 0:
            message = f"plan_agent_approved_but_no_new_subtasks_added: {review_reason}".strip()
            return 0, message[:500]

        summary = review_reason or "approved"
        return added, f"delegated_to_runtime_plan: {summary} (spawned={added})"[:500]

    def _ensure_plan_agent_llm(self) -> ChatOpenAI:
        """惰性加载 Planner LLM（复用或初始化独立的大模型能力句柄）。"""
        if self._plan_agent_llm is not None:
            return self._plan_agent_llm

        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model
        self._plan_agent_llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": config.llm.enable_thinking},
        )
        return self._plan_agent_llm

    async def _ask_plan_agent_review(
        self,
        parent: SubTask,
        reason: str,
    ) -> tuple[bool, str, str]:
        """向上层 Plan Agent 发起升级审批请求并获取响应。"""
        try:
            llm = self._ensure_plan_agent_llm()
            siblings_preview = [
                f"- {st.id}: {st.name} | status={st.status.value} | depth={st.depth}"
                for st in self.plan.subtasks[:30]
            ]
            system_prompt = render_template(
                _PLANNER_PROMPT_TEMPLATE_PATH,
                section="runtime_upgrade_review_system_prompt",
            )
            user_message = render_template(
                _PLANNER_PROMPT_TEMPLATE_PATH,
                section="runtime_upgrade_review_user_message",
                variables={
                    "original_request": self.plan.original_request,
                    "site_url": self.plan.site_url,
                    "subtask_id": parent.id,
                    "subtask_name": parent.name,
                    "subtask_list_url": parent.list_url,
                    "subtask_task_description": parent.task_description,
                    "subtask_depth": parent.depth,
                    "upgrade_reason": reason or "模型未提供具体原因",
                    "siblings_preview": "\n".join(siblings_preview) if siblings_preview else "无",
                },
            )
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ]
            )
            parsed = parse_json_dict_from_llm(str(response.content or "")) or {}

            approved = bool(coerce_bool(parsed.get("approve"), False))
            review_reason = str(parsed.get("reason") or "").strip() or (
                "plan_agent_approved" if approved else "plan_agent_rejected"
            )
            refined_request = str(parsed.get("refined_request") or "").strip()
            return approved, review_reason, refined_request
        except Exception as e:
            logger.warning("[Dispatcher] 上层 Plan Agent 审批失败（%s）: %s", parent.id, e)
            return False, f"plan_agent_review_error: {str(e)[:200]}", ""

    async def _plan_runtime_subtasks(
        self,
        parent: SubTask,
        reason: str,
        planner_request_override: str = "",
    ) -> list[SubTask]:
        """开启无头会话启动 TaskPlanner 抓取并在运行时提取子任务列表。"""
        # 给 TaskPlanner 分配一个新的隔离会话环境
        planner_session = BrowserSession(headless=self.headless)
        await planner_session.start()

        try:
            # 组合前导信息作为提示语传给 TaskPlanner
            request = str(planner_request_override or "").strip()
            if not request:
                request = str(parent.task_description or "").strip()
            extra = str(reason or "").strip()
            if extra and extra not in request:
                request = f"{request}\n\n执行阶段补充线索：{extra}"

            runtime_output_dir = Path(self.output_dir) / f"subtask_{parent.id}"
            planner = TaskPlanner(
                page=planner_session.page,
                site_url=str(parent.list_url or "").strip(),
                user_request=request,
                output_dir=str(runtime_output_dir),
                use_main_model=self.runtime_subtasks_use_main_model,
            )
            plan = await planner.plan()
            return list(plan.subtasks or [])[: self.runtime_subtasks_max_children]
        except Exception as e:
            logger.warning("[Dispatcher] 运行时规划失败（%s）: %s", parent.id, e)
            return []
        finally:
            await planner_session.stop()

    async def _append_runtime_subtasks(self, parent: SubTask, candidates: list[SubTask]) -> int:
        """将成功展开衍生的子任务集合合并并插入调度池。"""
        if not candidates:
            return 0

        # 获取对象排他锁用于防止并行的异步操作扰乱了同一深度的优先分配逻辑
        async with self._plan_lock:
            existing_ids = {st.id for st in self.plan.subtasks}
            added = 0
            # 设置子任务所属深度以及增加优先级偏移，保证深度优先执行
            child_depth = int(parent.depth or 0) + 1
            base_priority = int(parent.priority or 0) * 100 + 1

            for idx, raw in enumerate(candidates, start=1):
                child = raw.model_copy(deep=True)
                child.id = self._build_runtime_subtask_id(parent, child.id, idx, existing_ids)
                child.parent_id = parent.id
                child.depth = child_depth
                child.created_by = "runtime_plan"
                child.runtime_plan_attempted = False
                child.priority = base_priority + idx
                child.status = SubTaskStatus.PENDING
                child.retry_count = 0
                child.error = None
                child.result_file = None
                child.collected_count = 0

                # 设置必要的预置字段等继承父属性
                if not child.fields:
                    child.fields = list(parent.fields or [])
                if child.max_pages is None:
                    child.max_pages = parent.max_pages
                if child.target_url_count is None:
                    child.target_url_count = parent.target_url_count

                # 做去重过滤判断（针对 URL 与执行描述）防止同级别重复执行
                signature = self._task_signature(child)
                if signature in self._known_signatures:
                    continue

                self.plan.subtasks.append(child)
                self._known_signatures.add(signature)
                existing_ids.add(child.id)
                added += 1

            if added > 0:
                self.plan.total_subtasks = len(self.plan.subtasks)
                self.plan.updated_at = datetime.now().isoformat()
                await self._save_progress()

            return added

    def _build_runtime_subtask_id(
        self,
        parent: SubTask,
        original_id: str,
        index: int,
        existing_ids: set[str],
    ) -> str:
        """为运行时动态添加的子任务构建唯一的合并ID。"""
        normalized = str(original_id or f"category_{index:02d}").strip().replace(" ", "_")
        base = f"{parent.id}__{normalized}"
        candidate = base
        suffix = 2
        # 若重复存在则不断自增后缀，避免覆写
        while candidate in existing_ids:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _task_signature(self, subtask: SubTask) -> tuple[str, str, str]:
        """获取任务签名（组合访问路径与目的与父节点）用做重复拦截过滤器。"""
        url = str(subtask.list_url or "").strip().lower()
        task_desc = str(subtask.task_description or "").strip().lower()
        parent = str(subtask.parent_id or "").strip().lower()
        return (url, task_desc, parent)

    def _handle_failure(self, subtask: SubTask) -> None:
        """处理并在超过对应重试阈值前不断恢复失败子任务。"""
        subtask.retry_count += 1
        if subtask.retry_count <= self.max_subtask_retries:
            subtask.status = SubTaskStatus.PENDING
            logger.info(
                "[Dispatcher] 子任务 %s 将重试 (%d/%d)",
                subtask.name,
                subtask.retry_count,
                self.max_subtask_retries,
            )
        else:
            subtask.status = SubTaskStatus.FAILED
            logger.warning("[Dispatcher] 子任务 %s 重试次数用尽，标记为失败", subtask.name)

    def _load_progress(self) -> None:
        """从持久化记录中恢复当前调度的检查点状态。"""
        if not self.progress_path.exists():
            return

        try:
            with open(self.progress_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            status_map: dict[str, dict[str, Any]] = {}
            for st_data in saved.get("subtasks", []):
                st_id = st_data.get("id")
                if isinstance(st_id, str) and st_id:
                    status_map[st_id] = st_data

            existing_ids = {st.id for st in self.plan.subtasks}
            for st_id, st_data in status_map.items():
                if st_id in existing_ids:
                    continue
                try:
                    restored = SubTask.model_validate(st_data)
                except Exception:
                    continue
                self.plan.subtasks.append(restored)
                existing_ids.add(restored.id)
                self._known_signatures.add(self._task_signature(restored))

            restored = 0
            for subtask in self.plan.subtasks:
                saved_data = status_map.get(subtask.id)
                if not saved_data:
                    continue

                saved_status = str(saved_data.get("status") or "").lower()
                if saved_status == SubTaskStatus.COMPLETED:
                    subtask.status = SubTaskStatus.COMPLETED
                    subtask.collected_count = int(saved_data.get("collected_count", 0) or 0)
                    subtask.result_file = saved_data.get("result_file")
                    restored += 1
                elif saved_status == SubTaskStatus.FAILED:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.retry_count = int(saved_data.get("retry_count", 0) or 0)
                    subtask.error = saved_data.get("error")
                elif saved_status == SubTaskStatus.SKIPPED:
                    subtask.status = SubTaskStatus.SKIPPED
                    subtask.error = saved_data.get("error")
                elif saved_status == SubTaskStatus.PENDING:
                    subtask.status = SubTaskStatus.PENDING
                    subtask.retry_count = int(saved_data.get("retry_count", 0) or 0)

                subtask.runtime_plan_attempted = bool(
                    saved_data.get("runtime_plan_attempted", subtask.runtime_plan_attempted)
                )
                subtask.parent_id = saved_data.get("parent_id", subtask.parent_id)
                subtask.depth = int(saved_data.get("depth", subtask.depth) or 0)
                subtask.created_by = str(saved_data.get("created_by", subtask.created_by) or "initial_plan")

            self.plan.total_subtasks = len(self.plan.subtasks)
            self.plan.updated_at = datetime.now().isoformat()

            if restored:
                logger.info("[Dispatcher] 从进度文件恢复了 %d 个已完成子任务", restored)

        except Exception as e:
            logger.warning("[Dispatcher] 加载进度文件失败: %s", e)

    async def _save_progress(self) -> None:
        """覆盖式将现有调度的进度写盘以保证意外重启时恢复。"""
        async with self._lock:
            try:
                progress = {
                    "plan_id": self.plan.plan_id,
                    "updated_at": datetime.now().isoformat(),
                    "subtasks": [st.model_dump() for st in self.plan.subtasks],
                }

                self.progress_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.progress_path, "w", encoding="utf-8") as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning("[Dispatcher] 保存进度失败: %s", e)

    def _build_summary(self) -> dict:
        """构建完整的执行总计和所有运行情况反馈信息的字典摘要。"""
        completed = [st for st in self.plan.subtasks if st.status == SubTaskStatus.COMPLETED]
        failed = [st for st in self.plan.subtasks if st.status == SubTaskStatus.FAILED]
        skipped = [st for st in self.plan.subtasks if st.status == SubTaskStatus.SKIPPED]
        running = [st for st in self.plan.subtasks if st.status == SubTaskStatus.RUNNING]
        pending = [
            st
            for st in self.plan.subtasks
            if st.status == SubTaskStatus.PENDING
        ]

        return {
            "plan_id": self.plan.plan_id,
            "total": len(self.plan.subtasks),
            "completed": len(completed),
            "failed": len(failed),
            "skipped": len(skipped),
            "running": len(running),
            "pending": len(pending),
            "total_collected": sum(st.collected_count for st in completed),
            "started_at": self._started_at.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "failed_details": [{"id": st.id, "name": st.name, "error": st.error} for st in failed],
            "skipped_details": [{"id": st.id, "name": st.name, "error": st.error} for st in skipped],
        }
