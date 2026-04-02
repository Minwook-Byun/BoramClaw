from __future__ import annotations

from pathlib import Path
from typing import Iterable


DEFAULT_DOC_TYPES = [
    "business_registration",
    "ir_deck",
    "tax_invoice",
    "social_insurance",
    "investment_decision",
    "unknown",
]


DOC_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business_registration": (
        "business_registration",
        "business-registration",
        "biz_registration",
        "사업자등록증",
        "사업자 등록증",
        "사업자등록",
    ),
    "ir_deck": (
        "ir_deck",
        "ir deck",
        "pitch",
        "investor deck",
        "투자제안서",
        "ir",
        "deck",
    ),
    "tax_invoice": (
        "tax_invoice",
        "invoice",
        "세금계산서",
        "tax",
        "vat",
    ),
    "social_insurance": (
        "social_insurance",
        "4대보험",
        "4대 보험",
        "고용보험",
        "국민연금",
        "건강보험",
        "산재보험",
    ),
    "investment_decision": (
        "investment_decision",
        "board_minutes",
        "의사결정",
        "투자결정",
        "결재",
        "minutes",
        "approval",
    ),
}


def _tokenize(text: str) -> str:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


def classify_text(text: str) -> tuple[str, float]:
    normalized = _tokenize(text)
    if not normalized:
        return "unknown", 0.0

    best_doc_type = "unknown"
    best_score = 0.0
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            kw = _tokenize(keyword)
            if kw and kw in normalized:
                score += 1.0
        if score > best_score:
            best_doc_type = doc_type
            best_score = score

    if best_doc_type == "unknown":
        return best_doc_type, 0.0

    # keyword count를 confidence로 정규화한다.
    confidence = min(0.99, 0.55 + (best_score * 0.15))
    return best_doc_type, round(confidence, 2)


def _read_lightweight_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in {".txt", ".md", ".csv", ".json", ".log"}:
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return raw[:4000]


def classify_document(
    path: Path,
    *,
    include_ocr: bool = False,
    extra_hints: Iterable[str] | None = None,
) -> tuple[str, float]:
    hints = [path.name]
    if extra_hints:
        hints.extend([str(item) for item in extra_hints if str(item).strip()])
    doc_type, confidence = classify_text(" ".join(hints))
    if doc_type != "unknown":
        return doc_type, confidence

    if include_ocr:
        text = _read_lightweight_text(path)
        if text:
            return classify_text(text)
    return "unknown", 0.0

