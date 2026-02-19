"""字段 XPath 模式提取器

从多个页面的提取记录中提取公共 XPath 模式。
复用 URL 收集器模块的 XPath 模式匹配逻辑。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..common.config import config
from ..common.protocol import parse_json_dict_from_llm
from ..common.logger import get_logger
from ..common.llm.trace_logger import append_llm_trace
from ..common.utils.paths import get_prompt_path
from ..common.utils.prompt_template import render_template
from .models import (
    PageExtractionRecord,
    CommonFieldXPath,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = get_logger(__name__)
PROMPT_TEMPLATE_PATH = get_prompt_path("xpath_pattern.yaml")


def _escape_markup(text: str) -> str:
    """避免日志渲染吞掉 XPath 中的 [..] 片段。"""
    return (text or "").replace("[", "[[").replace("]", "]]")


class FieldXPathExtractor:
    """字段 XPath 模式提取器

    从多个页面的提取记录中分析每个字段的 XPath，
    提取出公共模式，用于批量爬取。
    """

    def __init__(self):
        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=0.0,
            max_tokens=1024,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": False},
        )

    async def extract_common_pattern(
        self,
        records: list[PageExtractionRecord],
        field_name: str,
    ) -> CommonFieldXPath | None:
        """
        从多个页面记录中提取公共 XPath 模式

        Args:
            records: 页面提取记录列表
            field_name: 字段名称

        Returns:
            公共 XPath 模式，如果无法提取则返回 None
        """
        if len(records) < 2:
            logger.info(f"[FieldXPathExtractor] 记录数不足: {len(records)}")
            return None

        logger.info(
            f"[FieldXPathExtractor] 从 {len(records)} 条记录中提取字段 '{field_name}' 的公共 XPath..."
        )

        # 收集所有 XPath（主 xpath + 多策略候选）
        xpaths = []
        per_record_candidates: list[list[dict]] = []
        for record in records:
            field_result = record.get_field(field_name)
            if field_result and field_result.xpath:
                xpaths.append(field_result.xpath)
                per_record_candidates.append(
                    field_result.xpath_candidates if field_result.xpath_candidates else []
                )

        if not xpaths:
            logger.info("[FieldXPathExtractor] ⚠ 未找到有效的 XPath")
            return None

        logger.info(f"[FieldXPathExtractor] 收集到 {len(xpaths)} 个 XPath:")
        for xpath in xpaths:
            logger.info(f"  - {_escape_markup(xpath)}")

        # --- P1: 从多策略候选中按策略分组，优先寻找带属性锚点的公共模式 ---
        candidate_pattern = self._find_common_pattern_from_candidates(per_record_candidates)
        if candidate_pattern and not self._is_over_broad_pattern(candidate_pattern):
            logger.info(
                f"[FieldXPathExtractor] ✓ 多策略候选合并成功: {_escape_markup(candidate_pattern)}"
            )

        # 传统规则合并
        rule_pattern = self._find_common_xpath_pattern(xpaths)
        dominant_pattern = self._find_dominant_exact_xpath(xpaths)
        normalized_structures = {self._normalize_for_comparison(xpath) for xpath in xpaths}

        if len(normalized_structures) == 1 and dominant_pattern:
            logger.info(
                "[FieldXPathExtractor] 检测到同构 XPath 变体，优先使用主模板精确 XPath"
            )
            common_pattern = dominant_pattern
        else:
            common_pattern = rule_pattern or dominant_pattern

        # 如果多策略候选合并成功，且比传统规则更稳定，则替换
        if candidate_pattern and not self._is_over_broad_pattern(candidate_pattern):
            candidate_score = self._xpath_stability_score(candidate_pattern)
            current_score = self._xpath_stability_score(common_pattern) if common_pattern else -10.0
            if candidate_score > current_score:
                logger.info(
                    "[FieldXPathExtractor] 多策略候选稳定性更高，优先使用"
                )
                common_pattern = candidate_pattern

        union_pattern = self._build_union_pattern(xpaths)

        # 仅在异构模板下且 union 明显提升覆盖时才使用 union，避免“范围过宽”
        if union_pattern and self._should_prefer_union_pattern(
            source_xpaths=xpaths,
            current_pattern=common_pattern,
            union_pattern=union_pattern,
        ):
            logger.info("[FieldXPathExtractor] 检测到异构模板，采用 union 模式")
            common_pattern = union_pattern

        if not common_pattern or self._is_over_broad_pattern(common_pattern):
            common_pattern = await self._generate_common_pattern_with_llm(
                field_name=field_name,
                source_xpaths=xpaths,
            )

        # LLM 回答过宽时，按稳定性优先级回退
        if common_pattern and self._is_over_broad_pattern(common_pattern):
            if candidate_pattern and not self._is_over_broad_pattern(candidate_pattern):
                logger.info("[FieldXPathExtractor] LLM 结果过宽，回退到多策略候选模式")
                common_pattern = candidate_pattern
            elif union_pattern and not self._is_over_broad_pattern(union_pattern):
                logger.info("[FieldXPathExtractor] LLM 结果过宽，回退到 union 模式")
                common_pattern = union_pattern
            elif rule_pattern and not self._is_over_broad_pattern(rule_pattern):
                logger.info("[FieldXPathExtractor] LLM 结果过宽，回退到规则模式")
                common_pattern = rule_pattern
            else:
                logger.info("[FieldXPathExtractor] ⚠ 公共 XPath 过宽，放弃该字段模式")
                common_pattern = None

        if not common_pattern:
            logger.info("[FieldXPathExtractor] ⚠ 未找到公共 XPath 模式")
            return None

        logger.info(
            f"[FieldXPathExtractor] ✓ 公共 XPath 模式: {_escape_markup(common_pattern)}"
        )

        # 计算置信度（统一使用标准化逻辑，避免出现异常低分）
        confidence = self._calculate_pattern_confidence(xpaths, common_pattern)

        return CommonFieldXPath(
            field_name=field_name,
            xpath_pattern=common_pattern,
            source_xpaths=xpaths,
            confidence=confidence,
        )

    async def _generate_common_pattern_with_llm(
        self,
        field_name: str,
        source_xpaths: list[str],
    ) -> str | None:
        if not source_xpaths:
            return None

        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="common_xpath_system_prompt",
        )
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="common_xpath_user_prompt",
            variables={
                "field_name": field_name,
                "source_xpaths": "\n".join(
                    [f"{idx + 1}. {xpath}" for idx, xpath in enumerate(source_xpaths)]
                ),
            },
        )

        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            payload = parse_json_dict_from_llm(str(response.content)) or {}
            raw_xpath = str(payload.get("xpath_pattern") or "").strip()
            xpath = self._clean_xpath(raw_xpath)

            append_llm_trace(
                component="field_xpath_pattern",
                payload={
                    "model": config.llm.planner_model or config.llm.model,
                    "input": {
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "field_name": field_name,
                        "source_xpaths": source_xpaths,
                    },
                    "output": {
                        "raw_response": str(response.content),
                        "parsed_payload": payload,
                        "xpath_pattern": xpath,
                    },
                },
            )
            return xpath
        except Exception as e:
            logger.info(f"[FieldXPathExtractor] LLM 生成公共 XPath 失败: {e}")
            return None

    def _clean_xpath(self, value: str) -> str:
        xpath = value.strip()
        if xpath.lower().startswith("xpath="):
            xpath = xpath[6:].strip()
        if xpath.startswith(("'", '"')) and xpath.endswith(("'", '"')):
            xpath = xpath[1:-1].strip()
        return xpath if xpath.startswith("/") else ""

    def _build_union_pattern(self, xpaths: list[str]) -> str | None:
        """
        仅在存在两个稳定模板时生成 union：
        `path_a | path_b`
        """
        if not xpaths:
            return None
        unique = list(dict.fromkeys(xpaths))
        if len(unique) != 2:
            return None
        normalized_unique = {self._normalize_for_comparison(xpath) for xpath in unique}
        # 同构路径只是在索引上变化时，不应使用 union
        if len(normalized_unique) <= 1:
            return None
        return f"{unique[0]} | {unique[1]}"

    def _find_dominant_exact_xpath(self, xpaths: list[str]) -> str | None:
        """选择出现频次最高的精确 XPath 作为主模板。"""
        cleaned = [xpath.strip() for xpath in xpaths if xpath and xpath.strip()]
        if not cleaned:
            return None

        counter = Counter(cleaned)
        top_count = counter.most_common(1)[0][1]
        ratio = top_count / len(cleaned)
        if ratio < 0.5:
            return None

        candidates = [xpath for xpath, count in counter.items() if count == top_count]
        candidates.sort(key=self._xpath_stability_score, reverse=True)
        return candidates[0] if candidates else None

    def _should_prefer_union_pattern(
        self,
        source_xpaths: list[str],
        current_pattern: str | None,
        union_pattern: str,
    ) -> bool:
        if not union_pattern or self._is_over_broad_pattern(union_pattern):
            return False

        normalized_structures = {
            self._normalize_for_comparison(xpath) for xpath in source_xpaths if xpath
        }
        if len(normalized_structures) <= 1:
            return False

        union_conf = self._calculate_pattern_confidence(source_xpaths, union_pattern)
        if union_conf < 0.75:
            return False

        if not current_pattern:
            return True

        current_conf = self._calculate_pattern_confidence(source_xpaths, current_pattern)
        return union_conf >= (current_conf + 0.25)

    def _xpath_stability_score(self, xpath: str) -> float:
        """
        对 XPath 做稳定性评分。
        分数越高表示越偏向可复用、可迁移的结构。
        """
        value = (xpath or "").strip()
        if not value:
            return -10.0

        lower = value.lower()
        score = 0.0

        if "@id=" in lower:
            score += 3.0
        if "@data-" in lower:
            score += 1.8
        if "@class" in lower:
            score += 0.8
        if lower.startswith("//*[@id="):
            score += 0.5

        numeric_index_count = len(re.findall(r"\[\d+\]", value))
        score -= numeric_index_count * 0.2

        depth = value.count("/")
        if depth > 10:
            score -= (depth - 10) * 0.08

        # 吸顶/浮层/弹窗等节点通常随模板或滚动状态变化，不宜作为公共模式锚点
        volatile_tokens = ("fixed", "sticky", "float", "popup", "modal", "dialog", "mask")
        if any(token in lower for token in volatile_tokens):
            score -= 1.8

        if "|" in value:
            score -= 0.6

        return score

    def _is_over_broad_pattern(self, xpath: str) -> bool:
        """
        判断 XPath 是否过宽。

        经验规则：
        - 出现中间 `//` 且没有任何属性锚点（id/class/data-*）时，通常命中面过大。
        - 以 `//span`、`//div`、`//*` 结尾的模式通常缺乏唯一性。
        """
        value = (xpath or "").strip()
        if "|" in value:
            parts = [part.strip() for part in value.split("|") if part.strip()]
            if not parts:
                return True
            return any(self._is_single_xpath_over_broad(part) for part in parts)
        return self._is_single_xpath_over_broad(value)

    def _is_single_xpath_over_broad(self, xpath: str) -> bool:
        value = (xpath or "").strip()
        if not value:
            return True
        if not value.startswith("/"):
            return True

        # 允许 `//*[@id="..."]`，但不允许无锚点的 `//*/...`
        if re.search(r"//\*(?!\s*\[@(?:id|class|data-[\w-]+))", value, flags=re.IGNORECASE):
            return True

        has_descendant_axis = "//" in value[2:]
        has_anchor = bool(
            re.search(
                r"@id\s*=|@class\s*=|contains\(\s*@class|@data-[\w-]+\s*=|contains\(\s*@data-",
                value,
                flags=re.IGNORECASE,
            )
        )
        if has_descendant_axis and not has_anchor:
            return True

        tail = value.lower()
        if tail.endswith("//span") or tail.endswith("//div") or tail.endswith("//*"):
            return True

        return False

    # ================================================================
    # P1: 多策略候选公共模式提取
    # ================================================================

    def _find_common_pattern_from_candidates(
        self, per_record_candidates: list[list[dict]]
    ) -> str | None:
        """从多策略 XPath 候选中按策略分组寻找公共模式

        核心思路：
        1. 将各记录的候选按 strategy 字段分组
        2. 按策略稳定性（id > class-anchor > id-relative > ...）排序
        3. 对每个策略，如果所有记录都有该策略的候选，则尝试合并
        4. 返回第一个合并成功的结果

        Args:
            per_record_candidates: 每条记录的候选列表

        Returns:
            合并成功的公共模式，或 None
        """
        if len(per_record_candidates) < 2:
            return None

        # 过滤掉没有候选的记录
        valid_records = [c for c in per_record_candidates if c]
        if len(valid_records) < 2:
            return None

        # 按策略分组，收集每条记录每种策略的 xpath 列表
        # strategy_groups[strategy] = [[record_0 的 xpaths], [record_1 的 xpaths], ...]
        strategy_groups: dict[str, list[list[str]]] = {}
        for record_candidates in valid_records:
            record_by_strategy: dict[str, list[str]] = {}
            for c in record_candidates:
                if not isinstance(c, dict):
                    continue
                strategy = c.get("strategy", "unknown")
                xpath = c.get("xpath", "")
                if xpath:
                    record_by_strategy.setdefault(strategy, []).append(xpath)
            for strategy, xpaths in record_by_strategy.items():
                strategy_groups.setdefault(strategy, []).append(xpaths)

        # 策略优先级顺序（稳定性从高到低）
        strategy_priority = [
            "id", "testid", "id-class-relative", "class-anchor",
            "id-relative", "data-attr",
        ]

        # 对每个策略尝试合并
        for strategy in strategy_priority:
            group = strategy_groups.get(strategy, [])
            # 要求所有有效记录都有该策略的候选
            if len(group) < len(valid_records):
                continue

            # 从每条记录中取第一个该策略的 xpath
            per_record_xpaths = [xpaths[0] for xpaths in group]

            # 检查是否全部完全相同
            if len(set(per_record_xpaths)) == 1:
                logger.info(
                    f"[FieldXPathExtractor] 策略 '{strategy}' 完全一致: "
                    f"{_escape_markup(per_record_xpaths[0])}"
                )
                return per_record_xpaths[0]

            # 尝试合并
            pattern = self._smart_extract_common_pattern(per_record_xpaths)
            if pattern and not self._is_over_broad_pattern(pattern):
                logger.info(
                    f"[FieldXPathExtractor] 策略 '{strategy}' 合并成功: "
                    f"{_escape_markup(pattern)}"
                )
                return pattern

            # 如果 smart 合并失败，尝试后缀对齐合并
            suffix_pattern = self._suffix_aligned_extract(per_record_xpaths)
            if suffix_pattern and not self._is_over_broad_pattern(suffix_pattern):
                logger.info(
                    f"[FieldXPathExtractor] 策略 '{strategy}' 后缀对齐合并成功: "
                    f"{_escape_markup(suffix_pattern)}"
                )
                return suffix_pattern

        return None

    def _suffix_aligned_extract(self, xpaths: list[str]) -> str | None:
        """后缀对齐的 XPath 公共模式提取

        当不同页面的 XPath 深度不同但后缀结构相似时使用。
        例如：
            //*[@id='main']/div/article/h1
            //*[@id='content']/div/div/article/h1
        后缀对齐后：
            .../article/h1 -> 找到共同后缀 -> 用 // 连接锚点

        Args:
            xpaths: XPath 列表

        Returns:
            合并后的模式，或 None
        """
        if len(xpaths) < 2:
            return xpaths[0] if xpaths else None

        all_segments = [self._parse_xpath_segments(xpath) for xpath in xpaths]
        if not all(all_segments):
            return None

        # 从后往前对齐
        min_len = min(len(segs) for segs in all_segments)
        if min_len < 1:
            return None

        # 找最长的公共后缀（tag 一致即可）
        common_suffix_len = 0
        for i in range(1, min_len + 1):
            tags = {segs[-i]["tag"] for segs in all_segments}
            if len(tags) == 1:
                common_suffix_len = i
            else:
                break

        if common_suffix_len < 1:
            return None

        # 检查公共后缀中的属性是否一致
        suffix_parts = []
        for i in range(common_suffix_len, 0, -1):
            seg_idx = -i
            tags = {segs[seg_idx]["tag"] for segs in all_segments}
            tag = tags.pop()

            # 索引：全相同则保留
            indices = [segs[seg_idx]["index"] for segs in all_segments]
            non_none = [x for x in indices if x is not None]
            index_str = ""
            if non_none and len(non_none) == len(indices) and len(set(non_none)) == 1:
                index_str = f"[{non_none[0]}]"

            # 属性：取交集
            all_attrs = [segs[seg_idx]["attrs"] for segs in all_segments]
            common_attrs = self._merge_attributes(all_attrs)
            attrs_str = "".join(common_attrs) if common_attrs else ""

            suffix_parts.append(f"{tag}{index_str}{attrs_str}")

        suffix_path = "/".join(suffix_parts)

        # 尝试找到公共前缀锚点（带 @id 或 @class 的节点）
        # 如果所有 xpath 在后缀之前都有一个一致的锚点，使用它
        anchors = []
        for seg_list in all_segments:
            prefix = seg_list[:-common_suffix_len] if common_suffix_len < len(seg_list) else []
            anchor = None
            for seg in reversed(prefix):
                if seg["attrs"]:
                    # 有属性锚点
                    anchor = f"{seg['separator']}{seg['tag']}{''.join(seg['attrs'])}"
                    break
            anchors.append(anchor)

        if anchors and all(a is not None for a in anchors) and len(set(anchors)) == 1:
            # 所有记录的锚点一致
            return f"{anchors[0]}//{suffix_path}"

        # 无法找到统一锚点，用 // 开头
        if common_suffix_len >= 2:
            # 后缀足够长时直接使用 //后缀
            return f"//{suffix_path}"

        return None

    def _find_common_xpath_pattern(self, xpaths: list[str]) -> str | None:
        """
        从一组 XPath 中找出公共模式（智能版）

        处理策略：
        1. 将XPath按节点分段
        2. 对每个节点位置进行智能对比
        3. 对于位置索引：如果所有XPath在该位置的索引相同则保留，不同则删除
        4. 对于属性选择器（如@class, @id）：保持不变
        5. 统计最常见的模式并返回置信度

        Examples:
            - 输入: [//div/ul/li[1]/a, //div/ul/li[2]/a, //div/ul/li[3]/a]
              输出: //div/ul/li/a (索引变化，删除)
            - 输入: [//div[1]/ul/li[1]/a, //div[1]/ul/li[2]/a]
              输出: //div[1]/ul/li/a (div的索引固定，保留；li的索引变化，删除)
        """
        if not xpaths:
            return None

        # 使用智能节点对比方法
        smart_pattern = self._smart_extract_common_pattern(xpaths)
        if smart_pattern:
            return smart_pattern

        # 尝试后缀对齐（处理不同深度的 XPath）
        suffix_pattern = self._suffix_aligned_extract(xpaths)
        if suffix_pattern and not self._is_over_broad_pattern(suffix_pattern):
            return suffix_pattern

        # 如果智能方法和后缀对齐都失败，回退到简化策略
        return self._fallback_extract_pattern(xpaths)

    def _parse_xpath_segments(self, xpath: str) -> list[dict]:
        """
        解析XPath为节点段列表
        
        每个节点段包含：
        - raw: 原始文本（如 "div[1]" 或 "a[@class='link']"）
        - tag: 标签名（如 "div", "a"）
        - index: 位置索引（如 1, 2, None）
        - attrs: 属性选择器列表
        - separator: 前导分隔符（"/" 或 "//"）
        """
        segments = []
        
        # 匹配XPath节点段，支持 / 和 // 分隔
        # 模式：匹配 //tag[...] 或 /tag[...]
        pattern = r'(//?)([a-zA-Z*][\w-]*)(\[[^\]]+\])*'
        
        for match in re.finditer(pattern, xpath):
            separator = match.group(1)  # "/" 或 "//"
            tag = match.group(2)  # 标签名
            predicates_raw = match.group(3) or ""  # 所有谓词 [...]
            
            # 解析谓词
            index = None
            attrs = []
            
            # 提取所有谓词
            for pred_match in re.finditer(r'\[([^\]]+)\]', predicates_raw):
                pred = pred_match.group(1)
                # 判断是位置索引还是属性选择器
                if re.match(r'^\d+$', pred.strip()):
                    index = int(pred.strip())
                else:
                    attrs.append(f"[{pred}]")
            
            segments.append({
                "raw": match.group(0),
                "tag": tag,
                "index": index,
                "attrs": attrs,
                "separator": separator,
            })
        
        return segments

    def _smart_extract_common_pattern(self, xpaths: list[str]) -> str | None:
        """
        智能提取公共XPath模式
        
        对比所有XPath的节点段，对每个位置：
        - 如果标签名不同，则无法合并
        - 如果索引相同，则保留索引
        - 如果索引不同，则删除索引
        - 属性选择器保持不变
        """
        if len(xpaths) < 2:
            return xpaths[0] if xpaths else None

        # 解析所有XPath
        all_segments = [self._parse_xpath_segments(xpath) for xpath in xpaths]
        
        # 检查节点数量是否一致
        segment_counts = [len(segs) for segs in all_segments]
        if len(set(segment_counts)) > 1:
            logger.debug(f"[FieldXPathExtractor] XPath节点数量不一致: {segment_counts}")
            # 尝试找出最常见的节点数量，只处理相同长度的XPath
            count_freq = Counter(segment_counts)
            most_common_count = count_freq.most_common(1)[0][0]
            
            # 过滤出相同长度的XPath
            filtered_xpaths = [
                xpaths[i] for i, segs in enumerate(all_segments) 
                if len(segs) == most_common_count
            ]
            if len(filtered_xpaths) < 2:
                return None
            
            # 重新解析
            all_segments = [self._parse_xpath_segments(xpath) for xpath in filtered_xpaths]
            xpaths = filtered_xpaths

        num_segments = len(all_segments[0])
        
        # 构建公共模式
        result_parts = []
        
        for seg_idx in range(num_segments):
            # 收集该位置所有节点的信息
            tags = [segs[seg_idx]["tag"] for segs in all_segments]
            indices = [segs[seg_idx]["index"] for segs in all_segments]
            all_attrs = [segs[seg_idx]["attrs"] for segs in all_segments]
            separators = [segs[seg_idx]["separator"] for segs in all_segments]
            
            # 标签必须一致
            if len(set(tags)) > 1:
                logger.debug(f"[FieldXPathExtractor] 位置 {seg_idx} 标签不一致: {set(tags)}")
                return None
            
            tag = tags[0]
            separator = separators[0]  # 分隔符应该一致
            
            # 判断索引是否应该保留
            # 规则：如果所有非None索引值相同，则保留；否则删除
            non_none_indices = [i for i in indices if i is not None]
            
            keep_index = False
            index_value = None
            if non_none_indices and len(non_none_indices) == len(indices):
                counter = Counter(non_none_indices)
                most_common_index, freq = counter.most_common(1)[0]
                ratio = freq / len(indices)
                if ratio >= 0.67:
                    # 索引多数一致时保留多数值，避免把多模板压平成过宽路径
                    keep_index = True
                    index_value = most_common_index
            
            # 合并属性选择器（取交集或最常见的）
            common_attrs = self._merge_attributes(all_attrs)

            # P1 增强：当索引被删除时，尝试用 class 属性替代索引来保持唯一性
            class_enhanced_attr = None
            if not keep_index and not common_attrs:
                class_enhanced_attr = self._find_common_class_for_position(
                    all_segments, seg_idx
                )
            
            # 构建节点表达式
            node_expr = f"{separator}{tag}"
            if keep_index:
                node_expr += f"[{index_value}]"
            if common_attrs:
                node_expr += "".join(common_attrs)
            elif class_enhanced_attr:
                node_expr += class_enhanced_attr
            
            result_parts.append(node_expr)
        
        if not result_parts:
            return None
        
        result = "".join(result_parts)
        
        # 验证置信度
        confidence = self._calculate_pattern_confidence(xpaths, result)
        
        logger.info(f"[FieldXPathExtractor] 智能提取模式: {_escape_markup(result)}")
        logger.info(f"[FieldXPathExtractor] 置信度: {confidence:.2%}")
        
        if confidence >= 0.5:
            return result
        else:
            return None

    def _merge_attributes(self, all_attrs: list[list[str]]) -> list[str]:
        """
        合并多个XPath节点的属性选择器
        
        策略：取所有XPath共有的属性选择器
        """
        if not all_attrs:
            return []
        
        # 取交集
        if not all_attrs[0]:
            return []
        
        common = set(all_attrs[0])
        for attrs in all_attrs[1:]:
            common &= set(attrs)
        
        return sorted(list(common))

    def _find_common_class_for_position(
        self, all_segments: list[list[dict]], seg_idx: int
    ) -> str | None:
        """在所有 XPath 的指定位置寻找可共用的 class 属性

        当索引被删除且没有公共属性时，检查各段的原始文本中是否包含
        contains(@class, ...) 或 @class= 表达式。如果多数记录在该位置
        有相同的 class 值，则返回一个 [contains(@class, 'xxx')] 谓词。

        Args:
            all_segments: 所有 XPath 的解析段列表
            seg_idx: 当前处理的段索引

        Returns:
            class 谓词字符串，或 None
        """
        class_values: list[str | None] = []

        for segs in all_segments:
            if seg_idx >= len(segs):
                class_values.append(None)
                continue

            seg_raw = segs[seg_idx].get("raw", "")
            seg_attrs = segs[seg_idx].get("attrs", [])

            found_class = None
            # 在属性谓词中查找 class 相关表达式
            for attr in seg_attrs:
                # 匹配 contains(@class, 'xxx') 或 @class='xxx'
                m = re.search(
                    r"contains\(\s*@class\s*,\s*['\"]([^'\"]+)['\"]",
                    attr, re.IGNORECASE,
                )
                if m:
                    found_class = m.group(1).strip()
                    break
                m = re.search(
                    r"@class\s*=\s*['\"]([^'\"]+)['\"]",
                    attr, re.IGNORECASE,
                )
                if m:
                    # 取第一个非噪声 class token
                    tokens = m.group(1).strip().split()
                    for token in tokens:
                        if len(token) >= 3 and not token.isdigit():
                            found_class = token
                            break
                    if found_class:
                        break

            class_values.append(found_class)

        # 统计非 None 的 class 值
        non_none = [v for v in class_values if v is not None]
        if not non_none:
            return None

        # 取最常见的 class 值
        counter = Counter(non_none)
        most_common_class, freq = counter.most_common(1)[0]
        ratio = freq / len(all_segments)

        # 至少 60% 的记录有相同的 class
        if ratio >= 0.6:
            # 安全转义 class 值
            if "'" not in most_common_class:
                return f"[contains(@class, '{most_common_class}')]"
            elif '"' not in most_common_class:
                return f'[contains(@class, "{most_common_class}")]'

        return None

    def _calculate_pattern_confidence(self, original_xpaths: list[str], pattern: str) -> float:
        """
        计算模式的置信度
        
        使用“精确匹配 + 结构匹配”混合评分，避免仅靠索引归一化导致置信度虚高。
        """
        if not original_xpaths:
            return 0.0

        if "|" in pattern:
            exact_parts = {p.strip() for p in pattern.split("|") if p.strip()}
            pattern_parts = [
                self._normalize_for_comparison(p.strip())
                for p in pattern.split("|")
                if p.strip()
            ]
            pattern_set = set(pattern_parts)
            if not pattern_set or not exact_parts:
                return 0.0
            exact_matching = 0
            normalized_matching = 0
            for xpath in original_xpaths:
                raw = (xpath or "").strip()
                xpath_normalized = self._normalize_for_comparison(raw)
                if raw in exact_parts:
                    exact_matching += 1
                if xpath_normalized in pattern_set:
                    normalized_matching += 1
            exact_ratio = exact_matching / len(original_xpaths)
            normalized_ratio = normalized_matching / len(original_xpaths)
            return (exact_ratio * 0.7) + (normalized_ratio * 0.3)

        exact_matching = 0
        normalized_matching = 0
        pattern_normalized = self._normalize_for_comparison(pattern)
        
        for xpath in original_xpaths:
            raw = (xpath or "").strip()
            xpath_normalized = self._normalize_for_comparison(raw)
            if raw == pattern.strip():
                exact_matching += 1
            if xpath_normalized == pattern_normalized:
                normalized_matching += 1

        exact_ratio = exact_matching / len(original_xpaths)
        normalized_ratio = normalized_matching / len(original_xpaths)
        return (exact_ratio * 0.7) + (normalized_ratio * 0.3)

    def _normalize_for_comparison(self, xpath: str) -> str:
        """
        标准化XPath用于比较
        
        只删除变化的位置索引，保留属性选择器
        """
        # 删除位置索引（纯数字的谓词）
        return re.sub(r'\[\d+\]', '', xpath)

    def _fallback_extract_pattern(self, xpaths: list[str]) -> str | None:
        """
        回退方案：简单的索引删除策略
        
        当智能策略失败时使用
        """
        logger.debug("[FieldXPathExtractor] 使用回退策略提取模式")
        
        # 去掉索引，标准化
        normalized = []
        for xpath in xpaths:
            # 去掉所有的位置索引 [数字]
            norm = re.sub(r"\[\d+\]", "", xpath)
            normalized.append(norm)

        # 统计模式出现次数
        pattern_counts = Counter(normalized)
        most_common = pattern_counts.most_common(1)

        if not most_common:
            return None

        common_pattern, count = most_common[0]
        confidence = count / len(xpaths)

        logger.info(
            f"[FieldXPathExtractor] (回退)最常见模式: {_escape_markup(common_pattern)}"
        )
        logger.info(f"[FieldXPathExtractor] (回退)出现次数: {count}/{len(xpaths)} (置信度: {confidence:.2%})")

        # 置信度阈值
        if confidence >= 0.5:
            return common_pattern
        else:
            return None

    def _count_matching_pattern(self, xpaths: list[str], pattern: str) -> int:
        """统计匹配公共模式的 XPath 数量"""
        count = 0
        pattern_normalized = self._normalize_for_comparison(pattern)
        for xpath in xpaths:
            normalized = self._normalize_for_comparison(xpath)
            if normalized == pattern_normalized:
                count += 1
        return count

    async def extract_all_common_patterns(
        self,
        records: list[PageExtractionRecord],
        field_names: list[str],
    ) -> list[CommonFieldXPath]:
        """
        提取所有字段的公共 XPath 模式

        Args:
            records: 页面提取记录列表
            field_names: 字段名称列表

        Returns:
            公共 XPath 模式列表
        """
        patterns = []

        for field_name in field_names:
            pattern = await self.extract_common_pattern(records, field_name)
            if pattern:
                patterns.append(pattern)

        return patterns


class XPathValueLLMValidator:
    """字段值 LLM 语义校验器"""

    def __init__(self):
        api_key = config.llm.planner_api_key or config.llm.api_key
        api_base = config.llm.planner_api_base or config.llm.api_base
        model = config.llm.planner_model or config.llm.model
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=0.0,
            max_tokens=512,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": False},
        )

    async def validate_value(
        self,
        field_name: str,
        field_description: str,
        field_data_type: str,
        page_url: str,
        xpath_pattern: str,
        extracted_value: str,
    ) -> tuple[bool, str, str]:
        """使用 LLM 校验字段值语义，返回 (是否通过, 规范值, 原因)"""
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="value_validation_system_prompt",
        )
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="value_validation_user_prompt",
            variables={
                "field_name": field_name or "unknown",
                "field_description": field_description or "",
                "field_data_type": field_data_type or "text",
                "page_url": page_url or "",
                "xpath_pattern": xpath_pattern or "",
                "extracted_value": extracted_value or "",
            },
        )

        response = await self.llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        payload = parse_json_dict_from_llm(str(response.content)) or {}
        is_valid = _to_bool(payload.get("is_valid"))
        normalized_value = str(payload.get("normalized_value") or extracted_value).strip()
        reason = str(payload.get("reason") or "").strip()
        if not normalized_value:
            normalized_value = extracted_value

        append_llm_trace(
            component="field_xpath_value_validation",
            payload={
                "model": config.llm.planner_model or config.llm.model,
                "input": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "field_name": field_name,
                    "field_description": field_description,
                    "field_data_type": field_data_type,
                    "page_url": page_url,
                    "xpath_pattern": xpath_pattern,
                    "extracted_value": extracted_value,
                },
                "output": {
                    "raw_response": str(response.content),
                    "parsed_payload": payload,
                    "is_valid": is_valid,
                    "normalized_value": normalized_value,
                    "reason": reason,
                },
            },
        )
        return is_valid, normalized_value, reason


_DEFAULT_XPATH_VALUE_VALIDATOR: XPathValueLLMValidator | None = None


def _get_default_xpath_value_validator() -> XPathValueLLMValidator | None:
    global _DEFAULT_XPATH_VALUE_VALIDATOR
    if _DEFAULT_XPATH_VALUE_VALIDATOR is not None:
        return _DEFAULT_XPATH_VALUE_VALIDATOR
    try:
        _DEFAULT_XPATH_VALUE_VALIDATOR = XPathValueLLMValidator()
    except Exception as e:
        logger.info(f"[validate_xpath_pattern] 初始化 LLM 校验器失败: {e}")
        return None
    return _DEFAULT_XPATH_VALUE_VALIDATOR


async def validate_xpath_pattern(
    page: "Page",
    url: str,
    xpath_pattern: str,
    expected_value: str | None = None,
    data_type: str | None = None,
    field_name: str | None = None,
    field_description: str | None = None,
    llm_validator: XPathValueLLMValidator | None = None,
) -> tuple[bool, str | None]:
    """
    验证 XPath 模式是否能正确提取字段

    Args:
        page: Playwright 页面对象
        url: 验证用的 URL
        xpath_pattern: XPath 模式
        expected_value: 预期值（可选，用于对比）
        data_type: 字段类型（text/number/date/url）
        field_name: 字段名（用于 LLM 语义校验）
        field_description: 字段描述（用于 LLM 语义校验）
        llm_validator: 可复用的 LLM 校验器（可选）

    Returns:
        (验证是否通过, 提取到的值)
    """
    try:
        # 导航到页面
        await page.goto(url, wait_until="domcontentloaded")

        locator = page.locator(f"xpath={xpath_pattern}")
        count = await locator.count()
        if count <= 0:
            return False, None

        prefer_url = (data_type or "").lower() == "url"
        max_candidates = min(count, 8)
        candidates: list[str] = []
        for idx in range(max_candidates):
            value = await _read_candidate_value(locator.nth(idx), prefer_url=prefer_url)
            if value:
                candidates.append(value.strip())

        # 去重与去空
        uniq_values: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            uniq_values.append(value)

        if not uniq_values:
            return False, None

        # 必须唯一：若匹配到多个不同候选值，直接判定 XPath 过宽
        normalized_uniq_values = {_normalize_text(v) for v in uniq_values}
        if len(normalized_uniq_values) != 1:
            logger.info(
                f"[validate_xpath_pattern] XPath 命中多个不同值，唯一性校验失败: {xpath_pattern}"
            )
            return False, None

        selected_value = uniq_values[0]

        # 如果有预期值，仅做相似度校验（唯一值前提下）
        if expected_value:
            expected_normalized = expected_value.strip().lower()
            from difflib import SequenceMatcher

            actual_normalized = selected_value.lower()
            if (
                expected_normalized in actual_normalized
                or actual_normalized in expected_normalized
            ):
                pass
            else:
                similarity = SequenceMatcher(
                    None, expected_normalized, actual_normalized
                ).ratio()
                if similarity < 0.7:
                    return False, selected_value

        # 先做通用类型校验，再做 LLM 语义校验
        if not _is_semantically_valid(selected_value, data_type):
            logger.info(
                f"[validate_xpath_pattern] 值未通过类型语义校验: field={field_name or ''}, value={selected_value[:80]}"
            )
            return False, None

        validator = llm_validator or _get_default_xpath_value_validator()
        if validator is None:
            logger.info("[validate_xpath_pattern] LLM 校验器不可用，校验失败")
            return False, None

        llm_valid, normalized_value, llm_reason = await validator.validate_value(
            field_name=field_name or "",
            field_description=field_description or "",
            field_data_type=(data_type or "text"),
            page_url=url,
            xpath_pattern=xpath_pattern,
            extracted_value=selected_value,
        )
        if not llm_valid:
            logger.info(
                f"[validate_xpath_pattern] LLM 语义校验失败: field={field_name or ''}, reason={llm_reason or 'N/A'}"
            )
            return False, None

        return True, normalized_value

    except Exception as e:
        logger.info(f"[validate_xpath_pattern] 验证失败: {e}")
        return False, None


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _looks_like_url(value: str) -> bool:
    value = (value or "").strip()
    if value.startswith("/"):
        return True
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _looks_like_number(value: str) -> bool:
    value = (value or "").strip()
    # 通用数字表达式：支持货币前后缀、千分位、小数
    return bool(re.fullmatch(r"[^\d\-+]*[-+]?\d[\d,\.\s]*[^\d]*", value))


def _looks_like_date(value: str) -> bool:
    value = (value or "").strip()
    patterns = [
        r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?",
        r"\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?",
    ]
    return any(re.search(p, value) for p in patterns)


def _is_semantically_valid(
    value: str,
    data_type: str | None,
) -> bool:
    text = (value or "").strip()
    if not text:
        return False

    dtype = (data_type or "").lower()
    if dtype == "url":
        return _looks_like_url(text)

    if dtype == "number":
        return _looks_like_number(text)

    if dtype == "date":
        return _looks_like_date(text)

    return True


async def _read_candidate_value(element_locator, prefer_url: bool) -> str | None:
    try:
        if prefer_url:
            for attr in ("href", "src", "data-href"):
                attr_val = await element_locator.get_attribute(attr, timeout=3000)
                if attr_val and attr_val.strip():
                    return attr_val.strip()
        text = await element_locator.inner_text(timeout=5000)
        text = (text or "").strip()
        if text:
            return text
    except Exception:
        return None
    return None
