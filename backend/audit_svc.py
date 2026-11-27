"""审计与辅助查询。"""
from __future__ import annotations

import json
import time
from fastapi import APIRouter, Header

from auth import current_user
from db import connect, rows_to_list

router = APIRouter(prefix="/api/audit", tags=["audit"])


def write_audit(actor: str, action: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(actor,action,payload,created_at) VALUES(?,?,?,?)",
            (actor, action, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        conn.commit()


def write_history(entity_kind: str, entity_id: int, action: str, detail: str, actor: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO change_history(entity_kind,entity_id,action,detail,actor,created_at) VALUES(?,?,?,?,?,?)",
            (entity_kind, entity_id, action, detail, actor, time.time()),
        )
        conn.commit()


def write_rejection(
    actor: str,
    action: str,
    entity_kind: str,
    entity_id: int,
    detail: str,
    payload: dict,
) -> None:
    """拒写/争用败北留痕：审计日志与变更历史同源各记一笔，正式数据零改。"""
    now = time.time()
    blob = json.dumps(payload, ensure_ascii=False)
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(actor,action,payload,created_at) VALUES(?,?,?,?)",
            (actor, action, blob, now),
        )
        conn.execute(
            "INSERT INTO change_history(entity_kind,entity_id,action,detail,actor,created_at) VALUES(?,?,?,?,?,?)",
            (entity_kind, entity_id, action, detail, actor, now),
        )
        conn.commit()


@router.get("/recent")
def recent(limit: int = 50, authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return {"items": rows_to_list(rows)}
