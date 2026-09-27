from __future__ import annotations

from typing import Any, Dict, Optional

from .domain import (ConflictError, DomainError, NotFoundError, ValidationError,
                     ensure_role, normalize_severity, require_number, require_text)
from .repository import Repository
from .rules import (AUDIT_ROLES, CREATE_ROLES, ENTITY, NOTICE_KIND,
                    NOTICE_REQUIRED_TARGETS, RECORD_ROLES, TITLE, VIEW_ROLES,
                    completion_blockers, escalation_required, priority_score,
                    response_deadline_hours, role_for_transition,
                    validate_transition)


class Service:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _view(self, role: str) -> None:
        ensure_role(role, VIEW_ROLES)

    def create_item(self, payload: Dict[str, Any], actor: str, role: str) -> Dict[str, Any]:
        ensure_role(role, CREATE_ROLES)
        actor = require_text(actor, "actor", 100)
        title = require_text(payload.get("title"), "title", 200)
        description = require_text(payload.get("description"), "description")
        severity = normalize_severity(payload.get("severity"))
        quantity = require_number(payload.get("quantity", 0), "quantity")
        threshold = require_number(payload.get("threshold", 1), "threshold", 0.000001)
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        item = self.repository.create_item(title, description, severity, quantity,
                                           threshold, external_ref, actor)
        self.repository.append_audit("create", ENTITY, item["id"], actor, {
            "title": title, "severity": severity, "quantity": quantity,
            "priority": priority_score(severity, quantity, threshold),
        })
        return self.enrich(item)

    def add_record(self, item_id: int, payload: Dict[str, Any], actor: str,
                   role: str) -> Dict[str, Any]:
        ensure_role(role, RECORD_ROLES)
        actor = require_text(actor, "actor", 100)
        kind = require_text(payload.get("kind"), "kind", 100)
        detail = require_text(payload.get("detail"), "detail")
        status = payload.get("status", "open")
        if status not in ("open", "closed"):
            raise ValueError("status必须是open或closed")
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        if kind == NOTICE_KIND and external_ref is None:
            raise ValidationError("交通通告必须提供编号external_ref")
        record = self.repository.add_record(item_id, kind, detail, status,
                                            external_ref, actor)
        self.repository.append_audit("record", ENTITY, item_id, actor, {
            "record_id": record["id"], "kind": kind, "status": status,
        })
        return record

    def close_record(self, item_id: int, record_id: int, actor: str,
                     role: str) -> Dict[str, Any]:
        ensure_role(role, RECORD_ROLES)
        actor = require_text(actor, "actor", 100)
        record = self.repository.close_record(item_id, record_id)
        self.repository.append_audit("record_close", ENTITY, item_id, actor, {
            "record_id": record["id"], "kind": record["kind"],
        })
        return record

    def _reject_decision(self, item_id: int, reason: str,
                         notice_ref: Optional[str], actor: str,
                         error: DomainError) -> None:
        self.repository.record_decision_failure(item_id, reason, notice_ref, actor)
        raise error

    def transition(self, item_id: int, target: str, expected_version: int,
                   actor: str, role: str,
                   notice_ref: Optional[str] = None) -> Dict[str, Any]:
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        validate_transition(item["status"], target)
        ensure_role(role, role_for_transition(target))
        if not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version必须是正整数")
        if target in NOTICE_REQUIRED_TARGETS:
            if notice_ref is None:
                raise ValidationError("限行或封闭决策必须提供交通通告编号notice_ref")
            notice_ref = require_text(notice_ref, "notice_ref", 100)
            notice = self.repository.get_notice(item_id, notice_ref)
            if notice is None:
                if self.repository.notice_exists_elsewhere(item_id, notice_ref):
                    self._reject_decision(item_id, "交通通告属于其他桥梁",
                                          notice_ref, actor,
                                          ConflictError("交通通告属于其他桥梁"))
                self._reject_decision(item_id, "交通通告不存在", notice_ref, actor,
                                      NotFoundError("交通通告不存在"))
            if notice["status"] != "open":
                self._reject_decision(item_id, "交通通告已关闭", notice_ref, actor,
                                      ConflictError("交通通告已关闭"))
        blockers = completion_blockers(target, self.repository.open_record_count(item_id))
        if blockers:
            raise ConflictError("；".join(blockers))
        updated = self.repository.transition_item(item_id, target, expected_version, actor)
        detail = {
            "from": item["status"], "to": target,
            "escalation_required": escalation_required(
                item["severity"], item["quantity"], item["threshold"]),
        }
        if notice_ref is not None:
            detail["notice_ref"] = notice_ref
        self.repository.append_audit("transition", ENTITY, item_id, actor, detail)
        return self.enrich(updated)

    def get_item(self, item_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        return self.enrich(self.repository.get_item(item_id))

    def list_items(self, role: str, status: Optional[str] = None) -> list:
        self._view(role)
        return [self.enrich(item) for item in self.repository.list_items(status)]

    def list_records(self, item_id: int, role: str) -> list:
        self._view(role)
        return self.repository.list_records(item_id)

    def audit(self, role: str, item_id: Optional[int] = None) -> list:
        ensure_role(role, AUDIT_ROLES)
        return self.repository.list_audit(item_id)

    @staticmethod
    def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(item)
        result["priority"] = priority_score(
            item["severity"], item["quantity"], item["threshold"])
        result["deadline_hours"] = response_deadline_hours(
            item["severity"], item["quantity"], item["threshold"])
        result["escalation_required"] = escalation_required(
            item["severity"], item["quantity"], item["threshold"])
        result["last_decision"] = None
        if item.get("last_decision_result"):
            result["last_decision"] = {
                "result": item["last_decision_result"],
                "reason": item["last_decision_reason"],
                "notice_ref": item["last_decision_notice_ref"],
                "actor": item["last_decision_actor"],
                "at": item["last_decision_at"],
            }
        return result
