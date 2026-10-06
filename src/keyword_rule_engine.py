"""
关键词判断引擎：单组 OR 逻辑，命中任意关键词即推荐。
纯英数字关键词按完整词匹配，避免 Q1 误命中 Q1R5。
"""
import re
from typing import Any, Dict, Iterable, List, Optional


_ASCII_TOKEN_KEYWORD_PATTERN = re.compile(r"^[a-z0-9 ]+$")
_ASCII_TOKEN_BOUNDARY = r"[a-z0-9]"

# 中英文同义词归一：关键词与商品文本同时替换，解决"苹果手表"匹配不了"Apple Watch"的问题
_SYNONYM_MAP = {
    "apple watch": "苹果手表",
    "applewatch": "苹果手表",
    "ipad": "ipad",
}


def normalize_text(value: str) -> str:
    text = " ".join((value or "").lower().split())
    for en, zh in _SYNONYM_MAP.items():
        text = text.replace(en, zh)
    return text


def _collect_text_fragments(value: Any, bucket: List[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            bucket.append(text)
        return
    if isinstance(value, (int, float, bool)):
        bucket.append(str(value))
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_text_fragments(item, bucket)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_fragments(item, bucket)


def build_search_text(record: Dict[str, Any]) -> str:
    """构建关键词匹配文本：只取当前商品自身的内容。

    闲鱼商品描述与标题合并存储（商品标题字段）。刻意排除以下字段，
    避免匹配到非当前商品的信息导致误命中：
    - 商品链接 URL（referPageArgs 携带搜索关键词，必然包含规则词）
    - 卖家发布的商品列表（卖家在售的其它商品，与本商品无关）
    - 搜索关键字 / 任务名称 / 价格参考等元信息
    """
    fragments: List[str] = []
    product_info = record.get("商品信息", {})

    _collect_text_fragments(product_info.get("商品标题"), fragments)
    _collect_text_fragments(product_info.get("商品标签"), fragments)

    return normalize_text(" ".join(fragments))


def _normalize_keywords(values: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw in values or []:
        text = normalize_text(str(raw).strip())
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _uses_ascii_token_match(keyword: str) -> bool:
    return bool(keyword) and _ASCII_TOKEN_KEYWORD_PATTERN.fullmatch(keyword) is not None


def _keyword_matches(keyword: str, normalized_text: str) -> bool:
    if not _uses_ascii_token_match(keyword):
        return keyword in normalized_text
    pattern = rf"(?<!{_ASCII_TOKEN_BOUNDARY}){re.escape(keyword)}(?!{_ASCII_TOKEN_BOUNDARY})"
    return re.search(pattern, normalized_text) is not None


def evaluate_keyword_rules(
    keywords: List[str],
    search_text: str,
    required_keywords: Optional[Iterable[str]] = None,
    optional_keywords: Optional[Iterable[str]] = None,
    optional_min_hits: Optional[int] = None,
) -> Dict[str, Any]:
    """双组关键词评估。

    - required_keywords: 必含关键词，商品文本必须全部命中（AND）。
    - optional_keywords: 可选关键词，命中数量 >= optional_min_hits 即可（可手动指定命中几个）。
    - keywords: 旧版单组 OR 规则（向后兼容），仅在未配置 required/optional 时作为可选组使用，
      命中任一即推荐（等价 optional_min_hits=1）。
    """
    normalized_text = normalize_text(search_text)
    normalized_required = _normalize_keywords(required_keywords)
    normalized_optional = _normalize_keywords(optional_keywords)

    # 兼容旧调用：无新字段时，旧 keywords 按 OR（可选组，命中任一即推荐）
    if not normalized_required and not normalized_optional:
        normalized_optional = _normalize_keywords(keywords)

    if not normalized_text:
        return {
            "analysis_source": "keyword",
            "is_recommended": False,
            "reason": "可匹配文本为空，关键词规则无法执行。",
            "matched_keywords": [],
            "keyword_hit_count": 0,
        }

    if not normalized_required and not normalized_optional:
        return {
            "analysis_source": "keyword",
            "is_recommended": False,
            "reason": "未配置关键词规则。",
            "matched_keywords": [],
            "keyword_hit_count": 0,
        }

    # 必含组：全部命中
    missing_required = [kw for kw in normalized_required if not _keyword_matches(kw, normalized_text)]
    required_ok = len(missing_required) == 0

    # 可选组：命中数量达标
    matched_optional = [kw for kw in normalized_optional if _keyword_matches(kw, normalized_text)]
    min_hits = optional_min_hits
    if min_hits is None:
        min_hits = 1 if normalized_optional else 0
    optional_ok = (len(matched_optional) >= min_hits) if normalized_optional else True

    matched_keywords = matched_optional + [kw for kw in normalized_required if kw in matched_optional or _keyword_matches(kw, normalized_text)]
    hit_count = len(matched_keywords)
    is_recommended = required_ok and optional_ok

    if not required_ok:
        reason = f"缺少必含关键词：{', '.join(missing_required)}"
    elif normalized_optional and len(matched_optional) < min_hits:
        reason = f"可选关键词命中 {len(matched_optional)}/{min_hits} 个，未达标。"
    elif is_recommended:
        reason = f"命中关键词：{', '.join(matched_keywords)}"
    else:
        reason = "未命中任何关键词。"

    return {
        "analysis_source": "keyword",
        "is_recommended": is_recommended,
        "reason": reason,
        "matched_keywords": matched_keywords,
        "keyword_hit_count": hit_count,
    }
