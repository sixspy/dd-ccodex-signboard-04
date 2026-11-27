"""写入短锁，防并发双写。"""
from __future__ import annotations

import time
from fastapi import APIRouter, Header, HTTPException

from auth import current_user, require_writer
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])


def acquire(lock_key: str, holder: str, ttl_sec: int = 20) -> None:
    """原子取锁：单条 upsert 以持有者/过期为条件，影响行数定胜负，不留双成窗口。"""
    now = time.time()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO write_locks(lock_key,holder,expires_at) VALUES(?,?,?) "
            "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at "
            "WHERE write_locks.expires_at<=? OR write_locks.holder=?",
            (lock_key, holder, now + ttl_sec, now, holder),
        )
        won = cur.rowcount > 0
        holder_now = None
        if not won:
            row = conn.execute(
                "SELECT holder FROM write_locks WHERE lock_key=?", (lock_key,)
            ).fetchone()
            holder_now = row["holder"] if row else "unknown"
        conn.commit()
    if not won:
        raise HTTPException(409, f"资源锁定中：{holder_now}")


def release(lock_key: str, holder: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM write_locks WHERE lock_key=? AND holder=?",
            (lock_key, holder),
        )
        conn.commit()


@router.post("/acquire")
def api_acquire(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    key = (body.get("lock_key") or "").strip()
    if not key:
        raise HTTPException(400, "缺少 lock_key")
    acquire(key, user["username"], int(body.get("ttl_sec") or 20))
    return {"ok": True, "lock_key": key, "holder": user["username"]}


@router.post("/release")
def api_release(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    key = (body.get("lock_key") or "").strip()
    release(key, user["username"])
    return {"ok": True}
