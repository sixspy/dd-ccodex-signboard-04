"""播放清单。"""
from __future__ import annotations

import time
from fastapi import APIRouter, Header, HTTPException

from audit_svc import write_audit, write_history, write_rejection
from auth import current_user, require_writer
from db import connect, rows_to_list
from locks import acquire
from policies import (
    assert_asset_ready,
    assert_resolution_compatible,
    family_label,
    resolution_family,
)
from validators import require_code, require_playlist_status, require_positive_int, require_title, require_transition

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


def _target_screens(conn, playlist_id: int) -> list[dict]:
    """清单的目标屏幕族来源：当前正式发布（official=1）绑定的屏幕集合。"""
    return rows_to_list(
        conn.execute(
            """
            SELECT s.id, s.code, s.title, s.resolution
            FROM publications p JOIN screens s ON s.id=p.screen_id
            WHERE p.playlist_id=? AND p.official=1
            """,
            (playlist_id,),
        ).fetchall()
    )


def _incompatible_pairs(rows, targets) -> list[dict]:
    """逐对核算素材族 × 目标屏幕族，返回不兼容对清单。"""
    bad = []
    for r in rows:
        for s in targets:
            if resolution_family(r["resolution"]) != resolution_family(s["resolution"]):
                bad.append({"asset_code": r["code"], "asset_resolution": r["resolution"],
                            "screen_code": s["code"], "screen_resolution": s["resolution"]})
    return bad


@router.get("")
def list_playlists(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(conn.execute("SELECT * FROM playlists ORDER BY id DESC").fetchall())
        for r in rows:
            r["item_count"] = conn.execute(
                "SELECT COUNT(*) c FROM playlist_items WHERE playlist_id=?",
                (r["id"],),
            ).fetchone()["c"]
    return {"items": rows}


@router.get("/{playlist_id}")
def get_playlist(playlist_id: int, authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        pl = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if not pl:
            raise HTTPException(404, "清单不存在")
        items = rows_to_list(
            conn.execute(
                """
                SELECT i.*, a.code asset_code, a.title asset_title, a.kind, a.resolution
                FROM playlist_items i JOIN assets a ON a.id=i.asset_id
                WHERE i.playlist_id=? ORDER BY i.seq
                """,
                (playlist_id,),
            ).fetchall()
        )
        targets = _target_screens(conn, playlist_id)
    for t in targets:
        t["family"] = resolution_family(t["resolution"])
        t["family_label"] = family_label(t["resolution"])
    for i in items:
        i["family"] = resolution_family(i["resolution"])
        i["family_label"] = family_label(i["resolution"])
        i["compatible"] = (
            all(resolution_family(t["resolution"]) == i["family"] for t in targets)
            if targets else None
        )
    return {"playlist": dict(pl), "items": items, "target_screens": targets}


@router.post("")
def create_playlist(body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    code = require_code(body.get("code"), "清单编码")
    title = require_title(body.get("title"), "清单标题")
    status = require_playlist_status(body.get("status") or "draft")
    transition = require_transition(body.get("transition") or "cut")
    loop_flag = 1 if body.get("loop", True) else 0
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO playlists(code,title,status,transition,loop_flag,owner,created_at) VALUES(?,?,?,?,?,?,?)",
                (code, title, status, transition, loop_flag, user["username"], time.time()),
            )
            pid = cur.lastrowid
            conn.commit()
        except Exception as exc:
            raise HTTPException(409, f"清单编码冲突: {exc}") from exc
    write_history("playlist", pid, "create", f"创建清单 {code}", user["username"])
    write_audit(user["username"], "playlist.create", {"id": pid})
    return {"id": pid, "code": code}


@router.post("/{playlist_id}/items")
def add_item(playlist_id: int, body: dict, authorization: str | None = Header(default=None)):
    """甲路径写口闸：不兼容条目整笔拒写，正式条目册零增，只留拒写痕迹。

    同事务跨表账实：BEGIN IMMEDIATE 起事务，联查素材 × 目标屏幕族后再落条目。
    争用写口「同清单条目写入互斥」：锁钥 playlist_items:{playlist_id}，
    败方 409 只留痕，禁止成功落库；锁随 TTL 或显式释放核销。
    """
    user = current_user(authorization)
    require_writer(user)
    asset_id = require_positive_int(body.get("asset_id"), "素材编号")
    seq = require_positive_int(body.get("seq"), "序号", 1, 999)
    dwell = require_positive_int(body.get("dwell_sec", 10), "停留秒", 1, 3600)
    lock_key = f"playlist_items:{playlist_id}"
    try:
        acquire(lock_key, user["username"])
    except HTTPException:
        write_rejection(
            user["username"], "playlist_item.race_lost", "playlist", playlist_id,
            f"争用败北：{lock_key} 被他人持有，条目未写",
            {"playlist_id": playlist_id, "asset_id": asset_id, "seq": seq, "lock_key": lock_key},
        )
        raise
    rejection = None
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        pl = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if not pl:
            raise HTTPException(404, "清单不存在")
        asset = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, "素材不存在")
        assert_asset_ready(asset["status"])
        targets = _target_screens(conn, playlist_id)
        bad = _incompatible_pairs(
            [{"code": asset["code"], "resolution": asset["resolution"]}], targets
        )
        if bad:
            b = bad[0]
            rejection = {
                "detail": (
                    f"素材 {b['asset_code']}({b['asset_resolution']}) 与目标屏幕 "
                    f"{b['screen_code']}({b['screen_resolution']}) 族不兼容，整笔拒写"
                ),
                "payload": {"playlist_id": playlist_id, "asset_id": asset_id, "bad": bad},
            }
        else:
            try:
                conn.execute(
                    "INSERT INTO playlist_items(playlist_id,asset_id,seq,dwell_sec) VALUES(?,?,?,?)",
                    (playlist_id, asset_id, seq, dwell),
                )
                conn.commit()
            except Exception as exc:
                raise HTTPException(409, f"序号冲突: {exc}") from exc
    if rejection is not None:
        write_rejection(
            user["username"], "playlist_item.reject_resolution", "playlist", playlist_id,
            rejection["detail"], rejection["payload"],
        )
        raise HTTPException(409, rejection["detail"])
    write_history("playlist", playlist_id, "add_item", f"加入素材 {asset_id} seq={seq}", user["username"])
    return {"ok": True}


@router.patch("/{playlist_id}")
def patch_playlist(playlist_id: int, body: dict, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    rejection = None
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        pl = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if not pl:
            raise HTTPException(404, "清单不存在")
        status = require_playlist_status(body.get("status", pl["status"]))
        title = require_title(body.get("title", pl["title"]), "清单标题")
        transition = require_transition(body.get("transition", pl["transition"]))
        if status == "ready":
            cnt = conn.execute(
                "SELECT COUNT(*) c FROM playlist_items WHERE playlist_id=?",
                (playlist_id,),
            ).fetchone()["c"]
            if cnt < 1:
                raise HTTPException(409, "空清单不可置为可播")
            # 置可播闸：已上屏清单须逐条核算素材族 × 目标屏幕族
            targets = _target_screens(conn, playlist_id)
            if targets:
                rows = rows_to_list(
                    conn.execute(
                        """
                        SELECT a.code, a.resolution
                        FROM playlist_items i JOIN assets a ON a.id=i.asset_id
                        WHERE i.playlist_id=? ORDER BY i.seq
                        """,
                        (playlist_id,),
                    ).fetchall()
                )
                bad = _incompatible_pairs(rows, targets)
                if bad:
                    b = bad[0]
                    rejection = {
                        "detail": (
                            f"清单含不兼容条目 {b['asset_code']}({b['asset_resolution']}) "
                            f"vs 目标屏幕 {b['screen_code']}({b['screen_resolution']})，不可置可播"
                        ),
                        "payload": {"playlist_id": playlist_id, "bad": bad},
                    }
        if rejection is None:
            conn.execute(
                "UPDATE playlists SET title=?, status=?, transition=? WHERE id=?",
                (title, status, transition, playlist_id),
            )
            conn.commit()
    if rejection is not None:
        write_rejection(
            user["username"], "playlist.reject_ready", "playlist", playlist_id,
            rejection["detail"], rejection["payload"],
        )
        raise HTTPException(409, rejection["detail"])
    write_history("playlist", playlist_id, "patch", f"清单状态={status}", user["username"])
    return {"ok": True}
