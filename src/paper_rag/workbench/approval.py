from __future__ import annotations

from hashlib import sha256

from fastapi import HTTPException

from .schemas import ApprovalPayload, CandidateIngestRequest


def validate_candidate_ingest_approval(payload: CandidateIngestRequest) -> ApprovalPayload:
    approval = payload.approval
    if approval is None or approval.approved is not True:
        raise _approval_error("Candidate ingestion requires explicit approval.")
    if approval.operation != "discovery_candidate_ingest":
        raise _approval_error("Approval operation must be discovery_candidate_ingest.")
    if approval.candidate_ids != payload.candidate_ids:
        raise _approval_error("Approved candidate ids must match the ingest request.")
    if approval.destination not in {"real-library", "isolated-library"}:
        raise _approval_error("Approval destination must be real-library or isolated-library.")
    if not approval.side_effects:
        raise _approval_error("Approval must include side effects.")
    return approval


def build_request_boundary(tool_name: str, approval: ApprovalPayload) -> str:
    digest = sha256(
        f"{tool_name}|{approval.destination}|{','.join(map(str, approval.candidate_ids))}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    return f"workbench-{tool_name}-{digest}"


def _approval_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "ok": False,
            "tool": "discovery_candidate_ingest",
            "error": {
                "code": "APPROVAL_REQUIRED",
                "message": message,
                "retryable": False,
            },
        },
    )
