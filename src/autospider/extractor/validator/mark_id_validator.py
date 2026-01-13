"""mark_id 文本优先解析器

历史设计：LLM 返回 mark_id + 文本，再通过“文本相似度”校验 mark_id 是否选对。
当前设计：仍返回 mark_id + 文本，但以“文本”为准（认为文本一定正确）。

解析规则：
1) 若 mark_id 对应的实际元素文本与 LLM 文本匹配（包含关系/短文本严格），直接使用该 mark_id。
2) 否则在当前 SoM 候选元素中按文本搜索：
   - 唯一命中：返回该命中的 mark_id（纠正 LLM 的 mark_id）。
   - 多个命中：标记为歧义，交由上层通过“重新框选候选并让 LLM 重选”消歧。
   - 0 命中：上层按策略报错（不回退 mark_id）。
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from ...common.config import config

if TYPE_CHECKING:
    from ...common.types import SoMSnapshot, ElementMark
    from playwright.async_api import Page


class MarkIdValidationResult:
    """mark_id 解析结果（文本优先）"""
    
    def __init__(
        self,
        mark_id: int | None,
        llm_text: str,
        actual_text: str,
        resolved_mark_id: int | None,
        candidate_mark_ids: list[int],
        is_valid: bool,
        element: "ElementMark | None" = None,
        status: str = "",
    ):
        self.mark_id = mark_id  # LLM 返回的 mark_id（可能为空或错误）
        self.llm_text = llm_text  # LLM 返回的文本
        self.actual_text = actual_text  # LLM mark_id 对应的实际文本（若 mark_id 无效则为说明文字）
        self.resolved_mark_id = resolved_mark_id  # 文本优先解析后的最终 mark_id（唯一命中时）
        self.candidate_mark_ids = candidate_mark_ids  # 文本匹配到的候选 mark_id（可能 0/1/多）
        self.is_valid = is_valid  # 是否已唯一解析成功
        self.element = element  # LLM mark_id 对应的元素（如果找到）
        self.status = status  # 解析状态：id_match/text_unique/text_ambiguous/text_not_found/invalid_mark_id 等
    
    def __repr__(self) -> str:
        ok = "✓" if self.is_valid else "✗"
        resolved = f" -> {self.resolved_mark_id}" if self.resolved_mark_id is not None else ""
        return f"[{self.mark_id}] {ok}{resolved} {self.status} | LLM: '{self.llm_text[:30]}...' vs Actual: '{self.actual_text[:30]}...'"


class MarkIdValidator:
    """文本优先的 mark_id 解析器"""
    
    def __init__(
        self, debug: bool | None = None
    ):
        self.debug = debug if debug is not None else config.url_collector.debug_mark_id_validation
        # 需求确认：短文本（<=2）要求严格匹配，避免“包含匹配”误命中大量元素
        self.short_text_strict_len = 2
    
    async def validate_mark_id_text_map(
        self,
        mark_id_text_map: dict[str, str],
        snapshot: "SoMSnapshot",
        page: "Page | None" = None,
    ) -> tuple[list[int], list[MarkIdValidationResult]]:
        """解析 LLM 返回的 mark_id 与文本映射（文本优先）
        
        Args:
            mark_id_text_map: LLM 返回的 {mark_id: text} 映射（mark_id 为字符串）
            snapshot: SoM 快照
            page: Playwright Page（可选）。提供时会从 DOM 读取完整 innerText，避免 SoM 截断文本影响匹配。
            
        Returns:
            (resolved_mark_ids, results): 已唯一解析成功的 mark_id 列表（去重）与所有解析结果
        """
        resolved_mark_ids: list[int] = []
        results = []
        
        # 构建 mark_id -> element 的映射
        mark_id_to_element = {m.mark_id: m for m in snapshot.marks}

        # 构建 mark_id -> 实际文本（优先 DOM innerText）
        mark_id_to_actual_text = await self._build_mark_id_to_actual_text(
            snapshot=snapshot,
            page=page,
        )
        
        for mark_id_str, llm_text in mark_id_text_map.items():
            llm_text = llm_text or ""

            llm_mark_id: int | None = None
            element = None
            actual_text = ""
            status = ""

            try:
                llm_mark_id = int(mark_id_str)
            except (ValueError, TypeError):
                status = "invalid_mark_id"
                actual_text = "[LLM mark_id 无效]"

            if llm_mark_id is not None:
                element = mark_id_to_element.get(llm_mark_id)
                if element is None:
                    actual_text = "[元素不存在]"
                    status = status or "mark_id_not_in_snapshot"
                else:
                    actual_text = mark_id_to_actual_text.get(llm_mark_id) or element.text or ""

            # 1) 先尝试：LLM 的 mark_id 是否与文本匹配（包含/短文本严格）
            if llm_mark_id is not None and element is not None:
                if self._is_text_match(llm_text, actual_text):
                    result = MarkIdValidationResult(
                        mark_id=llm_mark_id,
                        llm_text=llm_text,
                        actual_text=actual_text,
                        resolved_mark_id=llm_mark_id,
                        candidate_mark_ids=[llm_mark_id],
                        is_valid=True,
                        element=element,
                        status="id_match",
                    )
                    results.append(result)
                    resolved_mark_ids.append(llm_mark_id)
                    if self.debug:
                        print(f"[Validator] ✓ id_match: mark_id={llm_mark_id}")
                    continue

            # 2) 否则：以文本为准，在当前候选元素中搜索
            candidate_mark_ids = []
            for candidate_id, candidate_text in mark_id_to_actual_text.items():
                if self._is_text_match(llm_text, candidate_text):
                    candidate_mark_ids.append(candidate_id)

            candidate_mark_ids = sorted(set(candidate_mark_ids))

            if len(candidate_mark_ids) == 1:
                resolved_id = candidate_mark_ids[0]
                result = MarkIdValidationResult(
                    mark_id=llm_mark_id,
                    llm_text=llm_text,
                    actual_text=actual_text or "[未找到 LLM mark_id 对应元素]",
                    resolved_mark_id=resolved_id,
                    candidate_mark_ids=candidate_mark_ids,
                    is_valid=True,
                    element=element,
                    status="text_unique",
                )
                results.append(result)
                resolved_mark_ids.append(resolved_id)
                if self.debug:
                    print(f"[Validator] ✓ text_unique: '{llm_text[:50]}...' -> mark_id={resolved_id}")
                continue

            if len(candidate_mark_ids) > 1:
                result = MarkIdValidationResult(
                    mark_id=llm_mark_id,
                    llm_text=llm_text,
                    actual_text=actual_text or "[未找到 LLM mark_id 对应元素]",
                    resolved_mark_id=None,
                    candidate_mark_ids=candidate_mark_ids,
                    is_valid=False,
                    element=element,
                    status="text_ambiguous",
                )
                results.append(result)
                if self.debug:
                    print(f"[Validator] ? text_ambiguous: '{llm_text[:50]}...' -> {candidate_mark_ids}")
                continue

            # 0 命中
            result = MarkIdValidationResult(
                mark_id=llm_mark_id,
                llm_text=llm_text,
                actual_text=actual_text or "[未找到 LLM mark_id 对应元素]",
                resolved_mark_id=None,
                candidate_mark_ids=[],
                is_valid=False,
                element=element,
                status="text_not_found",
            )
            results.append(result)
            if self.debug:
                print(f"[Validator] ✗ text_not_found: '{llm_text[:50]}...'")

        # 去重并保持稳定顺序
        unique_resolved: list[int] = []
        seen = set()
        for mid in resolved_mark_ids:
            if mid not in seen:
                unique_resolved.append(mid)
                seen.add(mid)

        return unique_resolved, results

    async def _build_mark_id_to_actual_text(
        self,
        snapshot: "SoMSnapshot",
        page: "Page | None" = None,
    ) -> dict[int, str]:
        # 默认回退：使用 SoM 截断文本（至少可用）
        fallback = {m.mark_id: (m.text or "") for m in snapshot.marks}
        if page is None:
            return fallback

        mark_ids = [m.mark_id for m in snapshot.marks]
        if not mark_ids:
            return {}

        # 修改原因：很多可交互元素（尤其是 input/按钮图标）innerText 为空，
        # 但 aria-label/placeholder/title/value 等才是“人眼看到/能描述”的文本。
        js = r"""
        (ids) => {
          const out = {};
          for (const id of ids) {
            const el = document.querySelector(`[data-som-id="${id}"]`);
            if (!el) continue;
            const inner = (el.innerText || el.textContent || '').trim();
            const aria = (el.getAttribute('aria-label') || '').trim();
            const placeholder = (el.getAttribute('placeholder') || '').trim();
            const title = (el.getAttribute('title') || '').trim();
            let value = '';
            try {
              if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                value = (el.value || '').trim();
              }
            } catch (e) {}

            // 优先级：可见文本 > aria-label > placeholder > title > value
            const text = inner || aria || placeholder || title || value || '';
            out[id] = text;
          }
          return out;
        }
        """

        try:
            dom_map = await page.evaluate(js, mark_ids)
        except Exception:
            return fallback

        # 兜底：DOM 取不到的用 snapshot.text
        result: dict[int, str] = {}
        for mid in mark_ids:
            text = ""
            if isinstance(dom_map, dict):
                # JS 返回的对象 key 会变成字符串，这里同时兼容 int/str
                text = dom_map.get(mid) or dom_map.get(str(mid)) or ""
            result[mid] = text or fallback.get(mid, "")
        return result

    def _normalize_text(self, text: str) -> str:
        """宽松归一化：NFKC + 空白处理 + 大小写不敏感

        修改原因：视觉模型可能把中文之间插入空格/换行（如“提 升”），同时页面 DOM 文本通常不含该空格；
        另外很多页面混有 NBSP / 零宽字符，需统一清洗，否则会导致 text_not_found。
        """
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\u00A0", " ")  # NBSP
        text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)  # 零宽字符
        text = re.sub(r"\s+", " ", text).strip()
        return text.casefold()

    def _normalize_text_no_ws(self, text: str) -> str:
        """去掉全部空白的归一化版本（用于修复“中文被插入空格”导致的包含匹配失败）"""
        normalized = self._normalize_text(text)
        if not normalized:
            return ""
        return re.sub(r"\s+", "", normalized)

    def _llm_text_variants(self, llm_text: str) -> list[str]:
        """生成 LLM 文本的匹配变体（处理截断/省略号/括号等）

        修改原因：很多列表标题在页面显示会被省略截断，LLM 返回的文本可能包含“....../……/…”等占位符，
        或截断导致括号不闭合；直接做包含匹配容易命中失败。
        """
        llm_text = (llm_text or "").strip()
        if not llm_text:
            return []

        variants: list[str] = [llm_text]

        # 统一省略号：将各种点状序列视作截断符
        ellipsis_match = re.search(r"(?:\.{3,}|…+|⋯+|……+)", llm_text)
        if ellipsis_match:
            prefix = llm_text[: ellipsis_match.start()].strip()
            if prefix:
                variants.append(prefix)

        # 截断括号：取括号前缀（避免“(......”这种不在 DOM 中出现）
        for sep in ["（", "("]:
            if sep in llm_text:
                prefix = llm_text.split(sep, 1)[0].strip()
                if prefix:
                    variants.append(prefix)

        # 去掉结尾常见的截断符号组合
        trimmed = re.sub(r"[\s\.\u2026\u22EF·…⋯]+$", "", llm_text).strip()
        if trimmed:
            variants.append(trimmed)

        # 去重，保留顺序
        seen = set()
        out: list[str] = []
        for v in variants:
            v = v.strip()
            if not v:
                continue
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out

    def _is_text_match(self, llm_text: str, actual_text: str) -> bool:
        """文本匹配：短文本严格，其余包含关系"""
        for variant in self._llm_text_variants(llm_text):
            if self._is_text_match_one(variant, actual_text):
                return True
        return False

    def _is_text_match_one(self, llm_text: str, actual_text: str) -> bool:
        norm_llm = self._normalize_text(llm_text)
        norm_actual = self._normalize_text(actual_text)
        norm_llm_no_ws = self._normalize_text_no_ws(llm_text)
        norm_actual_no_ws = self._normalize_text_no_ws(actual_text)

        if not norm_llm_no_ws or not norm_actual_no_ws:
            return False

        if len(norm_llm_no_ws) <= self.short_text_strict_len:
            # 短文本严格：用“去空白版本”做全等，避免“提 升/提升”这种被空格干扰
            return norm_llm_no_ws == norm_actual_no_ws

        # 长文本：包含关系（分别在保留空白/去空白两种归一化空间下判断）
        if norm_llm and norm_actual and (norm_llm in norm_actual or norm_actual in norm_llm):
            return True

        return norm_llm_no_ws in norm_actual_no_ws or norm_actual_no_ws in norm_llm_no_ws


# 兼容旧版本的 mark_ids 列表格式
def convert_mark_ids_to_map(
    mark_ids: list[int],
    snapshot: "SoMSnapshot",
) -> dict[str, str]:
    """将旧版本的 mark_ids 列表转换为 mark_id_text_map 格式
    
    用于向后兼容。自动从 snapshot 中获取每个 mark_id 对应的文本。
    
    Args:
        mark_ids: mark_id 列表
        snapshot: SoM 快照
        
    Returns:
        {mark_id: text} 映射
    """
    mark_id_to_element = {m.mark_id: m for m in snapshot.marks}
    result = {}
    
    for mark_id in mark_ids:
        element = mark_id_to_element.get(mark_id)
        if element:
            result[str(mark_id)] = element.text or ""
    
    return result
