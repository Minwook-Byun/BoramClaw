from __future__ import annotations

from statistics import mean
from typing import Any


FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "naver.com",
    "daum.net",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
}


def _to_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def assess_collection_risk(
    *,
    tenant: dict[str, Any],
    artifacts_meta: list[dict[str, Any]],
    scope_audits: list[dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    artifact_count = len(artifacts_meta)
    unknown_count = sum(1 for row in artifacts_meta if str(row.get("doc_type", "")) == "unknown")
    rejected_count = sum(1 for row in scope_audits if str(row.get("decision", "")) == "reject")

    if artifact_count == 0:
        score += 0.55
        reasons.append("no_artifacts_collected")

    if unknown_count > 0:
        unknown_ratio = unknown_count / max(1, artifact_count)
        delta = min(0.30, 0.1 + (unknown_ratio * 0.4))
        score += delta
        reasons.append(f"unknown_doc_ratio:{unknown_ratio:.2f}")

    if rejected_count > 0:
        delta = min(0.2, 0.05 * rejected_count)
        score += delta
        reasons.append(f"scope_rejections:{rejected_count}")

    if artifact_count > 200:
        score += 0.2
        reasons.append("large_collection_over_200")
    elif artifact_count > 80:
        score += 0.1
        reasons.append("large_collection_over_80")

    confidences = [float(row.get("confidence", 0.0) or 0.0) for row in artifacts_meta]
    if confidences:
        avg_conf = mean(confidences)
        if avg_conf < 0.55:
            score += 0.12
            reasons.append(f"low_classifier_confidence:{avg_conf:.2f}")

    required_doc_types = {"business_registration", "tax_invoice", "investment_decision"}
    present_doc_types = {str(row.get("doc_type", "")) for row in artifacts_meta}
    missing_required = sorted(list(required_doc_types - present_doc_types))
    if missing_required:
        score += 0.1
        reasons.append("missing_core_docs:" + ",".join(missing_required))

    recipients = tenant.get("email_recipients", [])
    if isinstance(recipients, list):
        for raw in recipients:
            email = str(raw).strip().lower()
            if "@" not in email:
                continue
            domain = email.split("@", 1)[1]
            if domain in FREE_EMAIL_DOMAINS:
                score += 0.08
                reasons.append(f"free_mail_recipient:{domain}")
                break

    score = max(0.0, min(1.0, score))
    level = _to_level(score)
    return {"score": round(score, 4), "level": level, "reasons": reasons}
