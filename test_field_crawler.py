from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from lxml import html as lxml_html
from lxml.etree import _Element
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from autospider.common.browser import create_browser_session
from autospider.common.config import config
from autospider.common.protocol import parse_json_dict_from_llm
from autospider.field.models import FieldDefinition


# -----------------------------
# 配置区
# -----------------------------

EXPLORE_URLS = [
    "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=c557d3af8825fcfeb90db48e4ac8be3b&projectCode=E4407010802004597001&bizCode=3C52&siteCode=440700&publishDate=20260113181851&source=%E6%B1%9F%E9%97%A8%E5%B8%82%E5%85%AC%E5%85%B1%E8%B5%84%E6%BA%90%E4%BA%A4%E6%98%93%E5%B9%B3%E5%8F%B0&titleDetails=%E5%B7%A5%E7%A8%8B%E5%BB%BA%E8%AE%BE&classify=A03&nodeId=1942795323926024255",
    "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=dffd458c-02c8-45af-ae3f-66a27acfcacf&projectCode=E4401000002505479001&bizCode=3C52&siteCode=440100&publishDate=20260114190003&source=%E5%B9%BF%E4%BA%A4%E6%98%93%E6%95%B0%E5%AD%97%E4%BA%A4%E6%98%93%E5%B9%B3%E5%8F%B0&titleDetails=%E5%B7%A5%E7%A8%8B%E5%BB%BA%E8%AE%BE&classify=A03&nodeId=2005939215326740481",
    "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=4403003C52f6ba259161d44acca3e535077b4f4faa&projectCode=E4403000004z08761026&bizCode=3C52&siteCode=440300&publishDate=20250429145437&source=%E6%B7%B1%E5%9C%B3%E4%BA%A4%E6%98%93%E9%9B%86%E5%9B%A2%E7%BB%9F%E4%B8%80%E8%BA%AB%E4%BB%BD%E8%AE%A4%E8%AF%81%E5%B9%B3%E5%8F%B0&titleDetails=%E5%B7%A5%E7%A8%8B%E5%BB%BA%E8%AE%BE&classify=A06&nodeId=1993631416209039361",
]

VALIDATE_URLS = [
    "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=80c39264-8824-499d-b274-b757c8336bae&projectCode=E4401000002501074001&bizCode=3C52&siteCode=44&publishDate=20250428200004&source=%E5%B9%BF%E4%BA%A4%E6%98%93%E6%95%B0%E5%AD%97%E4%BA%A4%E6%98%93%E5%B9%B3%E5%8F%B0&titleDetails=%E5%B7%A5%E7%A8%8B%E5%BB%BA%E8%AE%BE&classify=A04&nodeId=1982730340625596418",
]

FIELDS = [
    FieldDefinition(name="中标人", description="中标人/中标单位名称", required=False, data_type="text"),
    FieldDefinition(name="中标价", description="中标金额/成交金额/中标报价", required=False, data_type="text"),
    FieldDefinition(name="工期（交货期）", description="工期/交货期/供货期/服务期", required=False, data_type="text"),
    FieldDefinition(name="项目负责人", description="项目负责人/项目经理", required=False, data_type="text"),
]

LABEL_TAGS = {"th", "td", "dt", "label", "span", "div", "p", "strong", "b"}
VALUE_TAGS = {"td", "dd", "span", "div", "p"}
SCOPE_TAGS = {"main", "article", "section", "div"}
VALUE_BAD_TAGS = {
    "tr", "table", "tbody", "thead", "tfoot",
    "section", "article", "main",
    "ul", "ol", "li", "dl", "dt",
    "form", "body", "html",
}

NOISE_HINTS = [
    "登录", "注册", "返回", "首页", "导航", "菜单", "帮助", "联系我们", "版权", "友情链接",
    "footer", "header", "nav", "breadcrumb", "sidebar"
]

ENABLE_LLM_FALLBACK = True
BOOTSTRAP_FROM_VALIDATE_WHEN_SIGNATURE_MISSING = True

LLM_SYSTEM_PROMPT = """你是网页信息抽取助手。请严格输出 JSON，不要输出多余文字。"""

LLM_USER_TEMPLATE = """请从截图中识别以下字段的【字段名(label)】与【字段值(value)】。

字段名: {field_name}
字段描述: {field_desc}

要求：
1) 输出 JSON：{{"found": true/false, "label_text": "...", "value_text": "...", "value_key": "...", "reason": "..."}}
2) label_text 必须是页面上真实出现的字段名文本（如“中标人”、“中标金额”）。
3) value_text 必须是与该字段名对应的值文本（紧邻或同一块区域）。
4) 如果页面不存在该字段，found=false，label_text/value_text 为空字符串。
5) value_key 用于 DOM 定位：如果 value_text 里主要是数字/金额，请只输出数字（去掉逗号、空格、单位）；否则 value_key=value_text。
"""


# -----------------------------
# 数据结构
# -----------------------------

@dataclass
class TextCandidate:
    element: _Element
    text: str
    similarity: float
    tag: str


@dataclass
class RuleCandidate:
    field_name: str
    signature: str
    relative_xpath: str
    label_xpath: str
    value_xpath: str
    label_text: str
    value_text: str
    score: float


@dataclass
class LCARule:
    field_name: str
    signature: str
    relative_xpath: str
    anchor_texts: list[str]
    confidence: float
    support: int
    total: int


# -----------------------------
# 基础工具
# -----------------------------

_LLM_INSTANCE: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None:
        if not config.llm.api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 LLM")
        _LLM_INSTANCE = ChatOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.api_base,
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        )
    return _LLM_INSTANCE


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u00A0", " ")
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_for_compare(text: str) -> str:
    return _normalize_text(text).casefold()


def _text_of(node: _Element) -> str:
    if node is None:
        return ""
    if not isinstance(getattr(node, "tag", None), str):
        return ""
    if node.tag in {"input", "textarea", "select"}:
        value = node.get("value") or ""
        if value:
            return _normalize_text(value)
    try:
        return _normalize_text("".join(node.itertext()))
    except Exception:
        return ""


def _similarity(a: str, b: str) -> float:
    na = _normalize_for_compare(a)
    nb = _normalize_for_compare(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _number_key(text: str) -> str:
    t = _normalize_for_compare(text)
    if not t:
        return ""
    t = t.replace(",", "")
    matches = re.findall(r"\d+(?:\.\d+)?", t)
    if not matches:
        return ""
    matches.sort(key=len, reverse=True)
    return matches[0]


def _best_text_similarity(target_text: str, candidate_text: str) -> float:
    nt = _number_key(target_text)
    nc = _number_key(candidate_text)
    if nt and nc:
        if nt == nc:
            return 1.0
        if nt in nc or nc in nt:
            return 0.95
        return SequenceMatcher(None, nt, nc).ratio()
    return _similarity(target_text, candidate_text)


def _split_name_variants(name: str) -> list[str]:
    variants: list[str] = []
    if not name:
        return variants
    variants.append(name)
    for match in re.findall(r"[（(]([^）)]+)[）)]", name):
        if match:
            variants.append(match)
    name_clean = re.sub(r"[（(][^）)]+[）)]", "", name).strip()
    if name_clean:
        variants.append(name_clean)
    return variants


def build_label_aliases(field: FieldDefinition) -> list[str]:
    aliases: list[str] = []
    aliases.extend(_split_name_variants(field.name))
    if field.description:
        parts = re.split(r"[\/、,，;；\s]+", field.description)
        aliases.extend([p for p in parts if p])

    seen = set()
    out = []
    for a in aliases:
        a = _normalize_text(a)
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(a)

    out.sort(key=lambda s: (-len(s), s))
    return out


def parse_html(html_content: str) -> _Element:
    try:
        return lxml_html.fromstring(html_content)
    except Exception:
        return lxml_html.fragment_fromstring(html_content, create_parent="div")


def _extract_shadow_templates_html(tree: _Element) -> list[str]:
    html_chunks: list[str] = []
    try:
        templates = tree.xpath("//template[@shadowrootmode]")
    except Exception:
        return html_chunks

    for t in templates or []:
        txt = "".join(t.itertext()).strip()
        if txt:
            html_chunks.append(txt)
    return html_chunks


def enrich_tree_with_shadow_templates(tree: _Element) -> _Element:
    chunks = _extract_shadow_templates_html(tree)
    if not chunks:
        return tree

    container = lxml_html.Element("div")
    container.set("data-shadow-merged", "1")

    for ch in chunks:
        try:
            sub = parse_html(ch)
            container.append(sub)
        except Exception:
            continue

    try:
        body = tree.xpath("//body")
        if body:
            body[0].append(container)
        else:
            tree.append(container)
    except Exception:
        try:
            tree.append(container)
        except Exception:
            pass

    return tree


def _noise_penalty(text: str) -> float:
    t = _normalize_for_compare(text)
    if not t:
        return 0.0
    penalty = 0.0
    for h in NOISE_HINTS:
        if _normalize_for_compare(h) in t:
            penalty += 0.08
    return min(0.6, penalty)


def _count_struct_signals(node: _Element) -> tuple[int, int]:
    try:
        table_count = len(node.xpath(".//table"))
    except Exception:
        table_count = 0
    try:
        dl_count = len(node.xpath(".//dl"))
    except Exception:
        dl_count = 0
    return table_count, dl_count


def pick_main_container(tree: _Element) -> tuple[_Element, dict[str, Any]]:
    candidates: list[_Element] = []
    try:
        candidates.extend(tree.xpath("//main | //article | //*[@role='main']"))
    except Exception:
        pass
    try:
        candidates.extend(tree.xpath("//section | //div"))
    except Exception:
        pass

    uniq: list[_Element] = []
    seen = set()
    for c in candidates:
        if not isinstance(c, _Element):
            continue
        if c.tag not in SCOPE_TAGS and c.tag not in {"main", "article"}:
            continue
        k = id(c)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    try:
        body = tree.xpath("//body")
        if body:
            uniq.append(body[0])
    except Exception:
        pass

    best = None
    best_score = -1.0
    best_dbg = {}

    for node in uniq:
        text = _normalize_text("".join(node.itertext()))
        text_len = len(text)
        if text_len < 200:
            continue

        table_count, dl_count = _count_struct_signals(node)

        try:
            elem_count = len(node.xpath(".//*")) + 1
        except Exception:
            elem_count = 200
        density = text_len / max(50, elem_count)

        noise = _noise_penalty(text)
        structure_signal = min(1.0, 0.25 * table_count + 0.15 * dl_count)
        size_signal = min(1.0, text_len / 6000.0)

        score = (
            0.45 * structure_signal
            + 0.35 * min(1.0, density / 40.0)
            - 0.25 * noise
            + 0.20 * size_signal
        )

        if score > best_score:
            best_score = score
            best = node
            best_dbg = {
                "score": round(score, 4),
                "tables": table_count,
                "dls": dl_count,
                "text_len": text_len,
                "density": round(density, 3),
                "noise": round(noise, 3),
                "tag": node.tag,
                "id": node.get("id"),
            }

    if best is None:
        try:
            body = tree.xpath("//body")
            if body:
                return body[0], {"score": 0.0, "reason": "fallback_body"}
        except Exception:
            pass
        return tree, {"score": 0.0, "reason": "fallback_root"}

    return best, best_dbg


def _safe_tag_name(node: _Element) -> str:
    tag = getattr(node, "tag", "")
    return tag if isinstance(tag, str) else type(node).__name__


def _fingerprint_structure(node: _Element, depth: int = 2, max_children: int = 12) -> str:
    if node is None or depth < 0:
        return ""

    children = [c for c in node if isinstance(c, _Element)]
    child_tags = [_safe_tag_name(c) for c in children[:max_children]]
    head = f"{_safe_tag_name(node)}({','.join(child_tags)})"

    if depth == 0 or not children:
        return head

    sub = ",".join(_fingerprint_structure(c, depth - 1, max_children) for c in children[:max_children])
    return f"{head}{{{sub}}}"


def build_structure_signature(node: _Element) -> tuple[str, str]:
    raw = _fingerprint_structure(node, depth=2, max_children=12)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return digest, raw


def _iter_text_nodes(tree: _Element) -> list[tuple[_Element, str]]:
    items: list[tuple[_Element, str]] = []
    for el in tree.iter():
        if not isinstance(el, _Element):
            continue
        if not isinstance(getattr(el, "tag", None), str):
            continue
        if el.text and el.text.strip():
            items.append((el, el.text))
        if el.tail and el.tail.strip():
            parent = el.getparent()
            if parent is not None and isinstance(parent, _Element) and isinstance(getattr(parent, "tag", None), str):
                items.append((parent, el.tail))
    return items


def find_text_candidates(
    tree: _Element,
    target_text: str,
    threshold: float = 0.76,
    max_candidates: int = 8,
) -> list[TextCandidate]:
    if not target_text:
        return []

    candidates: list[TextCandidate] = []
    for element, raw_text in _iter_text_nodes(tree):
        text = _normalize_text(raw_text)
        if not text or len(text) > 240:
            continue
        sim = _best_text_similarity(target_text, text)
        if sim < threshold:
            continue
        candidates.append(TextCandidate(element=element, text=text, similarity=sim, tag=str(element.tag)))

    candidates.sort(key=lambda c: (-c.similarity, len(c.text)))
    return candidates[:max_candidates]


def _label_score(candidate: TextCandidate, label_text: str) -> float:
    score = candidate.similarity
    norm_label = _normalize_text(label_text).rstrip("：:")
    norm_text = _normalize_text(candidate.text).rstrip("：:")
    if norm_label and norm_text == norm_label:
        score += 0.3
    if candidate.tag in LABEL_TAGS:
        score += 0.15
    length_pen = min(0.4, max(0.0, (len(candidate.text) - 20) * 0.01))
    score -= length_pen
    return score


def _value_score(candidate: TextCandidate) -> float:
    score = candidate.similarity
    if candidate.tag in VALUE_TAGS:
        score += 0.1
    if len(candidate.text) > 120:
        score -= 0.2
    if candidate.tag in VALUE_BAD_TAGS:
        score -= 0.8
    return score


def _split_xpath(xpath: str) -> list[str]:
    xp = xpath.strip()
    if xp.startswith("xpath="):
        xp = xp[len("xpath=") :]
    if xp.startswith("/"):
        xp = xp[1:]
    return [seg for seg in xp.split("/") if seg]


def _lca_distance(label_xpath: str, value_xpath: str) -> tuple[int, int]:
    label_segs = _split_xpath(label_xpath)
    value_segs = _split_xpath(value_xpath)
    common = 0
    for a, b in zip(label_segs, value_segs):
        if a == b:
            common += 1
        else:
            break
    distance = (len(label_segs) - common) + (len(value_segs) - common)
    return distance, common


def build_relative_xpath(label_xpath: str, value_xpath: str) -> tuple[str, str]:
    label_segs = _split_xpath(label_xpath)
    value_segs = _split_xpath(value_xpath)
    common = 0
    for a, b in zip(label_segs, value_segs):
        if a == b:
            common += 1
        else:
            break
    lca_xpath = "/" + "/".join(label_segs[:common]) if common > 0 else "/"
    up_steps = len(label_segs) - common
    down_segs = value_segs[common:]
    parts = [".."] * up_steps + down_segs
    rel = "/".join(parts) if parts else "."
    return rel, lca_xpath


def _is_generic_relative_xpath(rel: str) -> bool:
    if not rel:
        return True
    parts = [p for p in rel.split("/") if p and p != "."]
    if not parts:
        return True
    return all(p == ".." for p in parts)


def _best_candidate_pair(
    label_candidates: list[TextCandidate],
    value_candidates: list[TextCandidate],
    label_text: str,
) -> tuple[Optional[TextCandidate], Optional[TextCandidate], dict[str, Any]]:
    best_score = -1e9
    best_pair = (None, None)
    debug: dict[str, Any] = {"pairs": []}

    if not label_candidates or not value_candidates:
        return None, None, debug

    label_ranked = sorted(label_candidates, key=lambda c: _label_score(c, label_text), reverse=True)[:6]
    value_ranked = sorted(value_candidates, key=_value_score, reverse=True)[:8]

    for lc in label_ranked:
        label_xpath = lc.element.getroottree().getpath(lc.element)
        label_score = _label_score(lc, label_text)
        for vc in value_ranked:
            if vc.element is lc.element:
                continue
            if vc.tag in VALUE_BAD_TAGS:
                continue
            value_xpath = vc.element.getroottree().getpath(vc.element)
            distance, _ = _lca_distance(label_xpath, value_xpath)
            if distance > 12:
                continue
            score = label_score + _value_score(vc) - 0.1 * distance
            debug["pairs"].append({
                "label": lc.text,
                "value": vc.text,
                "distance": distance,
                "score": round(score, 4),
            })
            if score > best_score:
                best_score = score
                best_pair = (lc, vc)

    return best_pair[0], best_pair[1], debug


def build_rule_candidate(
    tree: _Element,
    field: FieldDefinition,
    label_text: str,
    value_text: str,
    signature: str,
) -> tuple[Optional[RuleCandidate], dict[str, Any]]:
    debug: dict[str, Any] = {
        "field": field.name,
        "label_text": label_text,
        "value_text": value_text,
    }

    label_candidates = find_text_candidates(tree, label_text, threshold=0.76, max_candidates=10)
    value_candidates = find_text_candidates(tree, value_text, threshold=0.76, max_candidates=10)

    if not label_candidates or not value_candidates:
        debug["reason"] = "label_or_value_not_found_in_dom"
        return None, debug

    best_label, best_value, pair_dbg = _best_candidate_pair(label_candidates, value_candidates, label_text)
    debug["pair_debug"] = pair_dbg
    if best_label is None or best_value is None:
        debug["reason"] = "no_good_pair"
        return None, debug

    label_xpath = best_label.element.getroottree().getpath(best_label.element)
    value_xpath = best_value.element.getroottree().getpath(best_value.element)
    relative_xpath, lca_xpath = build_relative_xpath(label_xpath, value_xpath)

    if _is_generic_relative_xpath(relative_xpath):
        debug["reason"] = "relative_xpath_too_generic"
        debug["relative_xpath"] = relative_xpath
        return None, debug

    if best_value.tag in VALUE_BAD_TAGS:
        debug["reason"] = "value_node_is_container"
        debug["value_tag"] = best_value.tag
        return None, debug

    # 规则自验证：用相对 XPath 回抽，必须能对齐到预期 value
    try:
        nodes = [best_label.element] if relative_xpath == "." else best_label.element.xpath(relative_xpath)
    except Exception:
        nodes = []
    extracted = ""
    for node in nodes:
        extracted = _text_of(node) if isinstance(node, _Element) else _normalize_text(str(node))
        if extracted:
            break
    if not extracted or _best_text_similarity(value_text, extracted) < 0.78 or not validate_field_value(field, extracted):
        debug["reason"] = "relative_xpath_validation_failed"
        debug["extracted"] = extracted
        debug["similarity"] = round(_best_text_similarity(value_text, extracted), 4) if extracted else 0.0
        return None, debug

    debug["label_xpath"] = label_xpath
    debug["value_xpath"] = value_xpath
    debug["lca_xpath"] = lca_xpath
    debug["relative_xpath"] = relative_xpath

    candidate = RuleCandidate(
        field_name=field.name,
        signature=signature,
        relative_xpath=relative_xpath,
        label_xpath=label_xpath,
        value_xpath=value_xpath,
        label_text=label_text,
        value_text=value_text,
        score=_label_score(best_label, label_text) + _value_score(best_value),
    )
    return candidate, debug


def _cleanup_value(value: str, label_texts: list[str]) -> str:
    v = _normalize_text(value)
    for label in label_texts:
        if not label:
            continue
        nl = _normalize_text(label).rstrip("：:")
        if v.startswith(nl):
            v = v[len(nl):].lstrip("：: ")
    return v.strip()


def validate_field_value(field: FieldDefinition, value: str) -> bool:
    if not value:
        return False
    v = _normalize_text(value)
    if not v:
        return False
    if len(v) > 200:
        return False

    noise_words = ["招标公告", "资格预审", "招标文件", "公告", "下载", "投标", "投标人", "链接"]
    for w in noise_words:
        if w in v:
            return False

    name = field.name
    if "价" in name or "金额" in name:
        if not re.search(r"\d", v):
            return False
    if "工期" in name or "交货期" in name:
        if not re.search(r"\d", v):
            allow = ["按招标文件", "详见招标文件", "以招标文件", "见招标文件", "按合同", "以合同"]
            if not any(a in v for a in allow):
                return False
    if "负责人" in name or "经理" in name:
        if len(v) > 40:
            return False
    if "中标人" in name:
        if len(v) < 2 or len(v) > 80:
            return False

    return True


def extract_by_rule(tree: _Element, field: FieldDefinition, rule: LCARule) -> tuple[Optional[str], dict[str, Any]]:
    debug: dict[str, Any] = {"field": field.name, "signature": rule.signature, "relative_xpath": rule.relative_xpath}

    label_candidates: dict[int, tuple[TextCandidate, float, str]] = {}
    for anchor in rule.anchor_texts:
        if not anchor:
            continue
        cands = find_text_candidates(tree, anchor, threshold=0.86, max_candidates=6)
        for c in cands:
            score = _label_score(c, anchor)
            key = id(c.element)
            if key not in label_candidates or label_candidates[key][1] < score:
                label_candidates[key] = (c, score, anchor)

    ranked = sorted(label_candidates.values(), key=lambda item: item[1], reverse=True)
    debug["label_candidates"] = [
        {"text": c.text, "score": round(score, 4), "anchor": anchor, "tag": c.tag}
        for c, score, anchor in ranked[:6]
    ]

    for c, _, anchor in ranked[:6]:
        rel = rule.relative_xpath
        try:
            nodes = [c.element] if rel == "." else c.element.xpath(rel)
        except Exception:
            nodes = []

        if not nodes:
            continue

        for node in nodes:
            value = _text_of(node) if isinstance(node, _Element) else _normalize_text(str(node))
            value = _cleanup_value(value, [anchor])
            if not value:
                continue
            if validate_field_value(field, value):
                debug["used_label"] = c.text
                debug["used_anchor"] = anchor
                return value, debug

    return None, debug


def group_rules(rules: list[LCARule]) -> dict[str, dict[str, LCARule]]:
    out: dict[str, dict[str, LCARule]] = {}
    for r in rules:
        out.setdefault(r.field_name, {})[r.signature] = r
    return out


def _format_anchor_texts(field: FieldDefinition, collected: set[str]) -> list[str]:
    anchors: list[str] = []
    for t in collected:
        t = _normalize_text(t)
        if t:
            anchors.append(t)
    for a in build_label_aliases(field):
        if a not in anchors:
            anchors.append(a)
    return anchors


def _extract_label_value_from_llm(payload: dict[str, Any]) -> tuple[bool, str, str, str]:
    found = bool(payload.get("found")) if payload.get("found") is not None else True
    label_text = payload.get("label_text") or payload.get("label") or ""
    value_text = payload.get("value_text") or payload.get("value") or payload.get("field_value") or ""
    value_key = payload.get("value_key") or payload.get("value_match") or payload.get("value_hint") or ""
    reason = payload.get("reason") or payload.get("thinking") or ""

    label_text = _normalize_text(str(label_text))
    value_text = _normalize_text(str(value_text))
    value_key = _normalize_text(str(value_key))
    if not value_key:
        value_key = value_text

    if not label_text or not value_text:
        found = False

    return found, label_text, value_text, value_key, str(reason).strip()


def build_llm_prompt(field: FieldDefinition) -> str:
    return LLM_USER_TEMPLATE.format(
        field_name=field.name,
        field_desc=field.description or "",
    )


def _build_message_with_image(user_text: str, screenshot_base64: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": user_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
        },
    ]


async def llm_extract_label_value(page, field: FieldDefinition) -> dict[str, Any]:
    screenshot_bytes = await page.screenshot(full_page=True)
    screenshot_base64 = base64.b64encode(screenshot_bytes).decode("ascii")

    system_prompt = LLM_SYSTEM_PROMPT
    user_prompt = build_llm_prompt(field)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=_build_message_with_image(user_prompt, screenshot_base64)),
    ]

    response = await get_llm().ainvoke(messages)
    data = parse_json_dict_from_llm(getattr(response, "content", "") or "") or {}

    found, label_text, value_text, value_key, reason = _extract_label_value_from_llm(data)

    return {
        "found": found,
        "label_text": label_text,
        "value_text": value_text,
        "value_key": value_key,
        "reason": reason,
        "raw": data,
    }


# -----------------------------
# 页面获取
# -----------------------------

async def fetch_html(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    return await page.content()


# -----------------------------
# 主流程
# -----------------------------

async def run() -> dict[str, Any]:
    if not config.llm.api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 LLM（用于探索集提取）")

    votes: dict[str, dict[str, dict[str, int]]] = {f.name: {} for f in FIELDS}
    anchor_map: dict[str, dict[str, set[str]]] = {f.name: {} for f in FIELDS}

    train_debug: list[dict[str, Any]] = []
    train_signature_summary: list[dict[str, Any]] = []
    bootstrap_debug: list[dict[str, Any]] = []

    debug_dir = PROJECT_ROOT / "output" / "debug_html"
    debug_dir.mkdir(parents=True, exist_ok=True)
    saved_debug: set[str] = set()

    async with create_browser_session(headless=True, close_engine=True) as session:
        # 先计算 validate 的 signature，便于后续判断是否缺少对应规则
        validate_signatures: dict[str, str] = {}
        for vurl in VALIDATE_URLS:
            try:
                vhtml = await fetch_html(session.page, vurl)
                vtree = enrich_tree_with_shadow_templates(parse_html(vhtml))
                vscope, _ = pick_main_container(vtree)
                vsig, _ = build_structure_signature(vscope)
                validate_signatures[vurl] = vsig
            except Exception:
                continue

        # ---------- TRAIN ----------
        for url in EXPLORE_URLS:
            html_content = await fetch_html(session.page, url)
            tree = parse_html(html_content)
            tree = enrich_tree_with_shadow_templates(tree)

            scope, scope_dbg = pick_main_container(tree)
            signature, _ = build_structure_signature(scope)
            train_signature_summary.append({
                "url": url,
                "signature": signature,
                "scope": scope_dbg,
            })

            per_url_dbg = {
                "url": url,
                "signature": signature,
                "scope": scope_dbg,
                "fields": [],
            }

            for field in FIELDS:
                llm_result = await llm_extract_label_value(session.page, field)
                field_dbg = {"field": field.name, "llm": llm_result}

                if not llm_result.get("found"):
                    field_dbg["reason"] = "llm_not_found"
                    per_url_dbg["fields"].append(field_dbg)
                    continue

                label_text = llm_result.get("label_text") or ""
                value_text = llm_result.get("value_key") or llm_result.get("value_text") or ""

                candidate, cand_dbg = build_rule_candidate(
                    tree=tree,
                    field=field,
                    label_text=label_text,
                    value_text=value_text,
                    signature=signature,
                )
                field_dbg["candidate"] = cand_dbg

                if candidate:
                    votes.setdefault(field.name, {}).setdefault(signature, {})
                    votes[field.name][signature].setdefault(candidate.relative_xpath, 0)
                    votes[field.name][signature][candidate.relative_xpath] += 1

                    anchor_map.setdefault(field.name, {}).setdefault(signature, set())
                    anchor_map[field.name][signature].add(label_text)
                else:
                    if cand_dbg.get("reason") == "label_or_value_not_found_in_dom":
                        safe_field = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", field.name)
                        safe_sig = re.sub(r"[^0-9a-zA-Z]+", "_", signature)
                        key = f"{safe_sig}_{safe_field}"
                        if key not in saved_debug:
                            saved_debug.add(key)
                            debug_path = debug_dir / f"{key}.html"
                            with open(debug_path, "w", encoding="utf-8") as f:
                                f.write(html_content)

                per_url_dbg["fields"].append(field_dbg)

            train_debug.append(per_url_dbg)

        # ---------- BOOTSTRAP（可选）：如果校验页 signature 完全没学到规则，就用校验页补齐该 signature ----------
        if BOOTSTRAP_FROM_VALIDATE_WHEN_SIGNATURE_MISSING and validate_signatures:
            learned_signatures: set[str] = set()
            for field_name, sig_map in votes.items():
                learned_signatures.update(sig_map.keys())

            missing = [u for u, sig in validate_signatures.items() if sig and sig not in learned_signatures]
            for url in missing:
                html_content = await fetch_html(session.page, url)
                tree = enrich_tree_with_shadow_templates(parse_html(html_content))
                scope, scope_dbg = pick_main_container(tree)
                signature, _ = build_structure_signature(scope)

                per_url_dbg = {"url": url, "signature": signature, "scope": scope_dbg, "fields": []}

                for field in FIELDS:
                    llm_result = await llm_extract_label_value(session.page, field)
                    field_dbg = {"field": field.name, "llm": llm_result}

                    if not llm_result.get("found"):
                        field_dbg["reason"] = "llm_not_found"
                        per_url_dbg["fields"].append(field_dbg)
                        continue

                    label_text = llm_result.get("label_text") or ""
                    value_text = llm_result.get("value_key") or llm_result.get("value_text") or ""

                    candidate, cand_dbg = build_rule_candidate(
                        tree=tree,
                        field=field,
                        label_text=label_text,
                        value_text=value_text,
                        signature=signature,
                    )
                    field_dbg["candidate"] = cand_dbg

                    if candidate:
                        votes.setdefault(field.name, {}).setdefault(signature, {})
                        votes[field.name][signature].setdefault(candidate.relative_xpath, 0)
                        votes[field.name][signature][candidate.relative_xpath] += 1

                        anchor_map.setdefault(field.name, {}).setdefault(signature, set())
                        anchor_map[field.name][signature].add(label_text)

                    per_url_dbg["fields"].append(field_dbg)

                bootstrap_debug.append(per_url_dbg)

        # ---------- BUILD RULES ----------
        rules: list[LCARule] = []
        field_map = {f.name: f for f in FIELDS}
        for field_name, sig_map in votes.items():
            for signature, xpath_counts in sig_map.items():
                if not xpath_counts:
                    continue
                total = sum(xpath_counts.values())
                best_xpath, support = max(xpath_counts.items(), key=lambda kv: kv[1])
                confidence = support / max(1, total)

                anchors = _format_anchor_texts(
                    field_map[field_name],
                    anchor_map.get(field_name, {}).get(signature, set()),
                )

                rules.append(
                    LCARule(
                        field_name=field_name,
                        signature=signature,
                        relative_xpath=best_xpath,
                        anchor_texts=anchors,
                        confidence=confidence,
                        support=support,
                        total=total,
                    )
                )

        rules_by_field = group_rules(rules)

        # ---------- TEST ----------
        test_records: list[dict[str, Any]] = []
        test_signature_summary: list[dict[str, Any]] = []

        for url in VALIDATE_URLS:
            html_content = await fetch_html(session.page, url)
            tree = parse_html(html_content)
            tree = enrich_tree_with_shadow_templates(tree)

            scope, scope_dbg = pick_main_container(tree)
            signature, _ = build_structure_signature(scope)
            test_signature_summary.append({"url": url, "signature": signature, "scope": scope_dbg})

            rec = {"url": url, "signature": signature, "success": True, "fields": []}

            for field in FIELDS:
                rule = rules_by_field.get(field.name, {}).get(signature)
                value = None
                debug = {"rule_used": None}

                if rule:
                    value, debug = extract_by_rule(tree, field, rule)
                    debug["rule_used"] = {
                        "signature": rule.signature,
                        "relative_xpath": rule.relative_xpath,
                        "confidence": rule.confidence,
                    }

                if not value and ENABLE_LLM_FALLBACK:
                    llm_result = await llm_extract_label_value(session.page, field)
                    if llm_result.get("found"):
                        value = llm_result.get("value_text")
                        debug["fallback"] = "llm"
                    else:
                        debug["fallback"] = "llm_not_found"

                ok = value is not None
                if not ok:
                    rec["success"] = False

                rec["fields"].append(
                    {
                        "field_name": field.name,
                        "value": value,
                        "ok": ok,
                        "debug": debug,
                    }
                )

            test_records.append(rec)

    return {
        "train": {
            "urls": EXPLORE_URLS,
            "signature_summary": train_signature_summary,
            "bootstrap_from_validate": BOOTSTRAP_FROM_VALIDATE_WHEN_SIGNATURE_MISSING,
            "bootstrap_debug": bootstrap_debug,
            "rules": [
                {
                    "field_name": r.field_name,
                    "signature": r.signature,
                    "relative_xpath": r.relative_xpath,
                    "anchor_texts": r.anchor_texts,
                    "confidence": round(r.confidence, 4),
                    "support": r.support,
                    "total": r.total,
                }
                for r in rules
            ],
            "debug_per_url": train_debug,
        },
        "test": {
            "urls": VALIDATE_URLS,
            "signature_summary": test_signature_summary,
            "records": test_records,
        },
    }


if __name__ == "__main__":
    data = asyncio.run(run())
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "lca_rule_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] 结果已保存: {output_path}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
