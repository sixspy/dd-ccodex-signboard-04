"""写入策略与风险闸。"""
from __future__ import annotations

import re
from fastapi import HTTPException

RESOLUTION_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$")

FAMILY_LABEL = {
    "landscape": "横屏族",
    "portrait": "竖屏族",
    "square": "方形族",
}


def resolution_family(resolution: str) -> str | None:
    """分辨率串 → 屏幕族（landscape/portrait/square）；无法解析返回 None。

    族判定唯一出处：写口闸、置可播闸、发布闸与台账页共用，不得各写一份。
    """
    m = RESOLUTION_RE.match((resolution or "").strip())
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w > h:
        return "landscape"
    if h > w:
        return "portrait"
    return "square"


def family_label(resolution: str) -> str:
    fam = resolution_family(resolution)
    return FAMILY_LABEL.get(fam, "未知族")


def assert_zone_risk_for_outdoor(zone_type: str, risk_level: int) -> None:
    if zone_type == "outdoor" and risk_level < 3:
        raise HTTPException(400, "室外分区风险等级至少为 3")


def assert_playlist_ready(status: str) -> None:
    if status != "ready":
        raise HTTPException(409, "仅可播清单可发布上屏")


def assert_window_open(status: str) -> None:
    if status != "open":
        raise HTTPException(409, "时段窗未开放，禁止发布")


def assert_screen_online(status: str) -> None:
    if status == "maintenance":
        raise HTTPException(409, "维保中的屏幕禁止发布")


def assert_asset_ready(status: str) -> None:
    if status != "ready":
        raise HTTPException(409, "仅可播素材可进入清单")


def assert_resolution_compatible(screen_res: str, asset_res: str) -> None:
    """族口径：素材族须等于屏幕族；任一分辨率不可解析视为不兼容。"""
    sf = resolution_family(screen_res)
    af = resolution_family(asset_res)
    if sf is None or af is None or sf != af:
        raise HTTPException(
            409,
            f"素材分辨率与屏幕族不兼容: 素材 {asset_res}({family_label(asset_res)}) "
            f"vs 屏幕 {screen_res}({family_label(screen_res)})",
        )


def assert_override_payload(effect: str, playlist_id, asset_id) -> None:
    if effect == "force_playlist" and not playlist_id:
        raise HTTPException(400, "强制清单须指定清单")
    if effect == "force_asset" and not asset_id:
        raise HTTPException(400, "强制单素材须指定素材")
    if effect == "force_blank" and (playlist_id or asset_id):
        raise HTTPException(400, "强制空屏不得附带清单或素材")


POLICY_NOTES = [
    "客户可见区发布须有变更历史可追溯",
    "紧急撤屏后正式发布版本不得静默回写",
    "单屏覆盖激活时求值优先覆盖条目",
    "影子草案升正前正式区零改",
    "维保屏幕只允许查看不可发布",
]
