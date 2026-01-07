"""任务规划器 - 在执行前分析任务并生成执行计划"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ...common.config import config
from .prompt_template import render_template

if TYPE_CHECKING:
    pass


class TaskPlan(BaseModel):
    """任务执行计划"""
    
    task_analysis: str = Field(..., description="任务分析")
    steps: list[str] = Field(default_factory=list, description="执行步骤列表")
    target_description: str = Field(..., description="目标描述")
    success_criteria: str = Field(..., description="成功标准")
    potential_challenges: list[str] = Field(default_factory=list, description="潜在挑战")


# Prompt模板文件路径
PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent.parent.parent.parent / "prompts" / "planner.yaml")


class TaskPlanner:
    """任务规划器"""
    
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
    ):
        """
        初始化任务规划器
        
        Args:
            api_key: API Key（可选，默认使用 config 中的 planner_api_key 或 api_key）
            api_base: API Base URL（可选，默认使用 config 中的 planner_api_base 或 api_base）
            model: 模型名称（可选，默认使用 config 中的 planner_model 或 model）
        """
        # 优先使用参数，其次使用 planner 专用配置，最后使用主配置
        self.api_key = api_key or config.llm.planner_api_key or config.llm.api_key
        self.api_base = api_base or config.llm.planner_api_base or config.llm.api_base
        self.model = model or config.llm.planner_model or config.llm.model
        
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            model=self.model,
            temperature=0.1,
            max_tokens=2000,
        )
    
    async def plan(self, start_url: str, task: str, target_text: str) -> TaskPlan:
        """
        分析任务并生成执行计划
        
        Args:
            start_url: 起始URL
            task: 任务描述
            target_text: 目标提取文本
            
        Returns:
            TaskPlan: 执行计划
        """
        # 使用模板引擎加载和渲染 prompt
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="system_prompt",
        )
        
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="user_prompt",
            variables={
                "start_url": start_url,
                "task": task,
                "target_text": target_text,
            }
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        
        response = await self.llm.ainvoke(messages)
        response_text = response.content
        
        # 解析响应
        plan = self._parse_response(response_text, task, target_text)
        return plan
    
    def _parse_response(self, response_text: str, task: str, target_text: str) -> TaskPlan:
        """解析LLM响应"""
        # 清理 markdown 代码块
        cleaned_text = response_text
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned_text)
        if code_block_match:
            cleaned_text = code_block_match.group(1).strip()
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
        if json_match:
            try:
                json_str = json_match.group()
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                data = json.loads(json_str)
                
                return TaskPlan(
                    task_analysis=data.get("task_analysis", task),
                    steps=data.get("steps", []),
                    target_description=data.get("target_description", f"找到包含「{target_text}」的内容"),
                    success_criteria=data.get("success_criteria", f"页面中出现「{target_text}」"),
                    potential_challenges=data.get("potential_challenges", []),
                )
            except json.JSONDecodeError:
                pass
        
        # 解析失败，返回默认计划
        return TaskPlan(
            task_analysis=task,
            steps=["导航到目标页面", "查找并点击相关链接", "定位目标内容", "提取目标文本"],
            target_description=f"找到包含「{target_text}」的内容",
            success_criteria=f"页面中出现「{target_text}」",
            potential_challenges=["页面结构可能复杂", "可能需要多次点击"],
        )
