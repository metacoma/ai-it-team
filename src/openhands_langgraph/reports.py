from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

JsonDict = dict[str, Any]


class RoleReportBase(BaseModel):
    """Typed role report footer emitted by specialist roles.

    The report is intentionally permissive (`extra=allow`) while the workflow is
    migrating from prose summaries to strict role-specific contracts. LangGraph
    uses this as structured evidence for Team Lead context, not as a semantic
    decision engine.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str = "1.0"
    role: str
    report_id: str | None = None
    role_instance: str | None = None
    action: str | None = None
    summary: str | None = None
    risk_level: str | None = None
    blocking: bool = False
    blocking_summary: list[str] = Field(default_factory=list)
    # P0/P1: shared validation contract between roles. Any role may refine it,
    # but Scout/Research/Senior Staff/Architect should usually discover/shape it
    # and QA/Reviewer/Publisher should consume it.
    validation_profile: JsonDict = Field(default_factory=dict)
    report_quality: JsonDict = Field(default_factory=dict)


class ScoutReport(RoleReportBase):
    role: Literal["scout"] = "scout"
    facts: JsonDict = Field(default_factory=dict)
    research_required: bool | None = None
    research_domains: list[JsonDict | str] = Field(default_factory=list)
    research_questions: list[str] = Field(default_factory=list)
    unknowns: list[JsonDict | str] = Field(default_factory=list)
    validation_questions: list[JsonDict | str] = Field(default_factory=list)
    routing_hints: JsonDict = Field(default_factory=dict)


class ResearchReport(RoleReportBase):
    role: Literal["research"] = "research"
    domains: list[JsonDict | str] = Field(default_factory=list)
    findings: list[JsonDict | str] = Field(default_factory=list)


class SeniorStaffReport(RoleReportBase):
    role: Literal["senior_staff_engineer"] = "senior_staff_engineer"
    target_runtime_contract: JsonDict = Field(default_factory=dict)
    assumption_ledger: list[JsonDict | str] = Field(default_factory=list)
    strategy: JsonDict = Field(default_factory=dict)
    root_cause: str | None = None
    fix_scope: str | None = None
    files_to_change: list[str] = Field(default_factory=list)
    files_inspected: list[str] = Field(default_factory=list)
    validation_strategy: str | JsonDict | None = None
    confidence: str | None = None
    architect_waiver_candidate: bool | None = None
    routing_hints: JsonDict = Field(default_factory=dict)


class ArchitectReport(RoleReportBase):
    role: Literal["architect"] = "architect"
    plan: JsonDict = Field(default_factory=dict)


class CoderReport(RoleReportBase):
    role: Literal["coder"] = "coder"
    change_set_id: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    implementation: JsonDict = Field(default_factory=dict)
    self_validation: JsonDict = Field(default_factory=dict)
    ready_for_qa: bool | None = None


class QAReport(RoleReportBase):
    role: Literal["qa"] = "qa"
    validated_change_set_id: str | None = None
    validation: JsonDict = Field(default_factory=dict)
    qa_recommendation: JsonDict = Field(default_factory=dict)
    ready_for_review: bool | None = None
    required_targets_passed: bool | None = None
    blocking_gaps: list[JsonDict | str] = Field(default_factory=list)
    accepted_gaps: list[JsonDict | str] = Field(default_factory=list)


class ReviewerReport(RoleReportBase):
    role: Literal["reviewer"] = "reviewer"
    reviewed_change_set_id: str | None = None
    reviewed_qa_report_id: str | None = None
    review: JsonDict = Field(default_factory=dict)
    validation_review: JsonDict = Field(default_factory=dict)


class PublisherReport(RoleReportBase):
    role: Literal["publisher"] = "publisher"
    published_change_set_id: str | None = None
    publish: JsonDict = Field(default_factory=dict)
    pr_checks: JsonDict = Field(default_factory=dict)
    publication: JsonDict = Field(default_factory=dict)
    pr_feedback: JsonDict = Field(default_factory=dict)
    repository_mutation_guard: JsonDict = Field(default_factory=dict)
    publisher_recommendation: JsonDict = Field(default_factory=dict)


_REPORT_MODELS = {
    "scout": ScoutReport,
    "research": ResearchReport,
    "senior_staff_engineer": SeniorStaffReport,
    "architect": ArchitectReport,
    "coder": CoderReport,
    "qa": QAReport,
    "reviewer": ReviewerReport,
    "publisher": PublisherReport,
}


def compact_validation_profile(profile: JsonDict | None) -> JsonDict:
    """Return the Team Lead-facing slice of a validation profile.

    A validation profile is the contract of required build/test/runtime targets
    discovered from CI, README, scripts, and task context. It is not a policy
    decision by itself; Team Lead decides whether gaps are acceptable.
    """
    if not isinstance(profile, dict) or not profile:
        return {}
    targets = profile.get("required_targets") or profile.get("targets") or []
    compact_targets: list[Any] = []
    if isinstance(targets, list):
        for target in targets[:12]:
            if not isinstance(target, dict):
                compact_targets.append(target)
                continue
            compact_targets.append({
                key: target.get(key)
                for key in (
                    "name", "required", "required_by", "category", "status",
                    "commands", "environment", "setup", "env", "source"
                )
                if target.get(key) is not None
            })
    return {
        key: value
        for key, value in {
            "profile_id": profile.get("profile_id"),
            "source_reports": profile.get("source_reports"),
            "ci_workflows": profile.get("ci_workflows"),
            "runtime_services": profile.get("runtime_services"),
            "startup_scripts": profile.get("startup_scripts"),
            "required_env": profile.get("required_env"),
            "required_targets": compact_targets,
            "notes": profile.get("notes"),
        }.items()
        if value not in (None, [], {})
    }


def report_required_target_gaps(profile: JsonDict | None, validation: JsonDict | None) -> list[JsonDict]:
    """Compare a QA validation object with a validation profile.

    This is an observability helper, not an enforcement engine. It exposes gaps
    to Team Lead in a structured way so Team Lead can decide whether to retry QA,
    accept risk, or ask a human.
    """
    if not isinstance(profile, dict) or not isinstance(validation, dict):
        return []
    required = profile.get("required_targets") or profile.get("targets") or []
    observed = validation.get("targets") or []
    if not isinstance(required, list) or not isinstance(observed, list):
        return []
    observed_by_name: dict[str, JsonDict] = {}
    for item in observed:
        if isinstance(item, dict) and item.get("name"):
            observed_by_name[str(item["name"]).lower()] = item
    gaps: list[JsonDict] = []
    for target in required:
        if not isinstance(target, dict):
            continue
        name = str(target.get("name") or "").strip()
        if not name:
            continue
        is_required = target.get("required")
        if is_required is None:
            is_required = bool(target.get("required_by"))
        if not is_required:
            continue
        observed_target = observed_by_name.get(name.lower())
        if observed_target is None:
            gaps.append({"target": name, "status": "missing", "blocking_candidate": True, "reason": "required target from validation_profile is absent from QA validation.targets"})
            continue
        status = str(observed_target.get("status") or "").lower()
        if status not in {"passed", "success", "ok"}:
            gaps.append({"target": name, "status": status or "unknown", "blocking_candidate": True, "reason": "required target did not pass", "observed": observed_target})
    return gaps


def compact_report_summary(report: JsonDict) -> JsonDict:
    """Return a short report slice for Team Lead context packs."""
    if not isinstance(report, dict):
        return {}
    role = str(report.get("role") or "").lower()
    base: JsonDict = {
        "report_id": report.get("report_id"),
        "role": role,
        "action": report.get("action"),
        "summary": report.get("summary"),
        "risk_level": report.get("risk_level"),
        "blocking": report.get("blocking"),
    }
    if isinstance(report.get("validation_profile"), dict) and report.get("validation_profile"):
        base["validation_profile"] = compact_validation_profile(report.get("validation_profile"))
    if isinstance(report.get("report_quality"), dict) and report.get("report_quality"):
        base["report_quality"] = report.get("report_quality")
    if role == "scout":
        facts = report.get("facts") if isinstance(report.get("facts"), dict) else {}
        research_domains = report.get("research_domains") or facts.get("research_domains") or []
        research_questions = report.get("research_questions") or facts.get("research_questions") or []
        unknowns = report.get("unknowns") or facts.get("unknowns") or []
        validation_questions = report.get("validation_questions") or facts.get("validation_questions") or []
        research_required = report.get("research_required")
        if research_required is None:
            research_required = bool(research_domains or research_questions)
        base["facts"] = {
            "ci_failure": facts.get("ci_failure"),
            "relevant_files": facts.get("relevant_files"),
            "documented_commands": facts.get("documented_commands"),
            "research_required": research_required,
            "research_domains": research_domains,
            "research_questions": research_questions,
            "unknowns": unknowns,
            "validation_questions": validation_questions,
            "routing_hints": report.get("routing_hints") or facts.get("routing_hints"),
        }
        profile = report.get("validation_profile") or facts.get("validation_profile")
        if isinstance(profile, dict) and profile:
            base["facts"]["validation_profile"] = compact_validation_profile(profile)
    elif role == "senior_staff_engineer":
        base["root_cause"] = report.get("root_cause")
        base["fix_scope"] = report.get("fix_scope")
        base["files_to_change"] = report.get("files_to_change")
        base["validation_strategy"] = report.get("validation_strategy")
        base["confidence"] = report.get("confidence") or report.get("assumptions_confidence")
        base["architect_waiver_candidate"] = report.get("architect_waiver_candidate")
        base["routing_hints"] = report.get("routing_hints")
    elif role == "qa":
        validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
        targets = validation.get("targets") if isinstance(validation, dict) else None
        gaps = validation.get("gaps") if isinstance(validation, dict) else validation.get("validation_gaps") if isinstance(validation, dict) else None
        blocking_gaps = report.get("blocking_gaps") or _blocking_gaps_from_targets_and_gaps(targets, gaps)
        base["validated_change_set_id"] = report.get("validated_change_set_id")
        profile = report.get("validation_profile") if isinstance(report.get("validation_profile"), dict) else {}
        profile_gaps = report_required_target_gaps(profile, validation) if profile else []
        base["validation"] = {
            "overall_status": validation.get("overall_status"),
            "validation_level": validation.get("validation_level"),
            "build_ran": validation.get("build_ran"),
            "build_passed": validation.get("build_passed"),
            "tests_run": validation.get("tests_run"),
            "tests_passed": validation.get("tests_passed"),
            "targets": targets,
            "gaps": gaps,
            "blocking_gaps": blocking_gaps,
            "profile_gaps": profile_gaps,
            "required_targets_passed": report.get("required_targets_passed"),
        }
        base["qa_recommendation"] = report.get("qa_recommendation")
    elif role == "reviewer":
        review = report.get("review") if isinstance(report.get("review"), dict) else {}
        base["reviewed_change_set_id"] = report.get("reviewed_change_set_id")
        base["reviewed_qa_report_id"] = report.get("reviewed_qa_report_id")
        base["review"] = {
            "qa_evidence_accepted": review.get("qa_evidence_accepted"),
            "publisher_ready": review.get("publisher_ready"),
            "findings": review.get("findings"),
            "required_fixes": review.get("required_fixes"),
        }
        if report.get("validation_review"):
            base["validation_review"] = report.get("validation_review")
    elif role == "coder":
        base["change_set_id"] = report.get("change_set_id")
        base["files_changed"] = report.get("files_changed")
        base["ready_for_qa"] = report.get("ready_for_qa")
    elif role == "publisher":
        base["published_change_set_id"] = report.get("published_change_set_id")
        base["publish"] = report.get("publish")
        if report.get("pr_checks"):
            base["pr_checks"] = report.get("pr_checks")
        if report.get("publication"):
            base["publication"] = report.get("publication")
        if report.get("pr_feedback"):
            base["pr_feedback"] = report.get("pr_feedback")
        if report.get("repository_mutation_guard"):
            base["repository_mutation_guard"] = report.get("repository_mutation_guard")
        if report.get("publisher_recommendation"):
            base["publisher_recommendation"] = report.get("publisher_recommendation")
    return {k: v for k, v in base.items() if v is not None}



def _blocking_gaps_from_targets_and_gaps(targets: Any, gaps: Any) -> list[Any]:
    """Compact helper for Team Lead context only.

    This does not decide workflow policy; it merely exposes likely-blocking QA
    evidence in a structured place so Team Lead can make the subjective decision.
    """
    blocking: list[Any] = []
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, dict):
                continue
            required = target.get("required")
            if required is None:
                required = bool(target.get("required_by"))
            status = str(target.get("status") or "").strip().lower()
            if required and status in {"skipped", "not_run", "not-run", "excluded", "syntax_only", "not_validated", "missing", "failed", "error"}:
                blocking.append(target)
    if isinstance(gaps, list):
        for gap in gaps:
            if isinstance(gap, dict) and (gap.get("blocking_candidate") is True or gap.get("blocking") is True):
                blocking.append(gap)
    return blocking

def parse_role_report(role: str, *, answer: str = "", summary: JsonDict | None = None, role_instance: str | None = None, fallback_report_id: str | None = None) -> tuple[JsonDict | None, str | None]:
    """Extract and validate FINAL_ROLE_REPORT_JSON from answer/summary.

    Returns (report, source). If no explicit report exists, create a compact
    compatibility report from the existing RoleSummary so Team Lead can still see
    a normalized shape while prompts are migrated.
    """
    role_key = str(role or "").strip().lower()
    explicit = _extract_explicit_report(answer or "")
    if explicit is None and isinstance(summary, dict):
        maybe = summary.get("role_report") or summary.get("report")
        if isinstance(maybe, dict):
            explicit = maybe
    if isinstance(explicit, dict):
        explicit.setdefault("schema_version", "1.0")
        explicit.setdefault("role", role_key)
        if role_instance:
            explicit.setdefault("role_instance", role_instance)
        if fallback_report_id:
            explicit.setdefault("report_id", fallback_report_id)
        validated = _validate_report(role_key, explicit)
        if validated is not None:
            return validated, "final_role_report_json"
        # Keep malformed explicit reports visible for Team Lead debugging.
        explicit.setdefault("parse_warning", "explicit role report did not match typed model; kept as tolerant dict")
        return explicit, "final_role_report_json_tolerant"

    if isinstance(summary, dict):
        report = _compat_report_from_summary(role_key, summary, role_instance=role_instance, report_id=fallback_report_id)
        return report, "summary_compat"
    return None, None


def _validate_report(role: str, data: JsonDict) -> JsonDict | None:
    model = _REPORT_MODELS.get(role, RoleReportBase)
    try:
        parsed = model.model_validate(data)
    except ValidationError:
        try:
            parsed = RoleReportBase.model_validate(data)
        except ValidationError:
            return None
    return parsed.model_dump(mode="json")


def _compat_report_from_summary(role: str, summary: JsonDict, *, role_instance: str | None, report_id: str | None) -> JsonDict:
    base: JsonDict = {
        "schema_version": "1.0-compat",
        "role": role,
        "role_instance": role_instance,
        "report_id": report_id,
        "action": summary.get("action"),
        "summary": summary.get("summary"),
        "risk_level": summary.get("risk_level"),
        "blocking": bool(summary.get("blocking", False)),
        "blocking_summary": summary.get("blocking_summary") if isinstance(summary.get("blocking_summary"), list) else [],
        "source": "summary_compat",
    }
    profile = summary.get("validation_profile")
    if isinstance(profile, dict):
        base["validation_profile"] = profile
    if role == "qa":
        validation = summary.get("validation") or summary.get("validation_evidence")
        if isinstance(validation, dict):
            base["validation"] = validation
    elif role == "reviewer":
        review = summary.get("validation_review") or summary.get("review_validation")
        if isinstance(review, dict):
            base["validation_review"] = review
            base["review"] = {"qa_evidence_accepted": True if review else None}
    elif role == "coder":
        if summary.get("files_changed"):
            base["files_changed"] = summary.get("files_changed")
    return {k: v for k, v in base.items() if v is not None}


def _extract_explicit_report(text: str) -> JsonDict | None:
    if not text:
        return None
    markers = ["FINAL_ROLE_REPORT_JSON", "ROLE_REPORT_JSON"]
    for marker in markers:
        idx = text.rfind(marker)
        if idx >= 0:
            tail = text[idx + len(marker):]
            obj = _first_json_object(tail)
            if obj is not None:
                return obj
    return None


def _first_json_object(text: str) -> JsonDict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = text[start: idx + 1]
                raw = re.sub(r"^```json\s*|```$", "", raw.strip(), flags=re.I | re.M)
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None
