"""Community moderation — propose edits, vote, auto-apply.

Endpoints (mounted under /api):
- POST /api/reports/{rid}/edits           → propose a fake/ended/shift edit
- POST /api/reports/{rid}/edits/{eid}/vote → up/down vote; net ≥ 2 auto-applies

All heavy lifting lives in ``server`` (helpers, models). This router is
purely the HTTP relocation of the original endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import server as srv

router = APIRouter(tags=["moderation"])


@router.post("/reports/{rid}/edits", status_code=201)
async def propose_edit(
    rid: str, body: "srv.ReportEditIn", request: Request
):
    """Propose a community edit on a report (fake / ended / position shift)."""
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if body.kind == "shift" and (body.new_lat is None or body.new_lng is None):
        raise HTTPException(
            status_code=400, detail="Position requise pour un décalage"
        )
    edit = {
        "id": srv.new_id(),
        "kind": body.kind,
        "new_lat": body.new_lat,
        "new_lng": body.new_lng,
        "comment": body.comment,
        "proposer_id": u["user_id"],
        "proposer_name": u.get("name", ""),
        "created_at": srv.now_utc(),
        # Proposer auto-counts as a single upvote — same weight as anyone else.
        "upvotes": [u["user_id"]],
        "downvotes": [],
        "applied": False,
        "applied_at": None,
    }
    await srv.db.reports.update_one({"id": rid}, {"$push": {"edits": edit}})
    # Proposer earns 1 point for the implicit upvote.
    await srv.db.users.update_one(
        {"user_id": u["user_id"]}, {"$inc": {"points": 1}}
    )

    # Notify the original author (unless they're the proposer themselves).
    if r.get("author_id") and r["author_id"] != u["user_id"]:
        kind_label = {
            "fake": "faux", "ended": "terminé", "shift": "à décaler"
        }.get(body.kind, body.kind)
        try:
            await srv.send_push(
                recipients=[r["author_id"]],
                data={
                    "title": "Proposition sur votre signalement",
                    "message": f"{u.get('name', 'Un marin')} l'a marqué {kind_label}.",
                    "action_url": f"/report/{rid}",
                },
                idempotency_key=f"edit:{rid}:{edit['id']}",
            )
        except Exception as e:
            srv.logger.warning("push propose-edit failed: %s", e)

    fresh = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    return srv.serialize_report(fresh, u["user_id"])


@router.post("/reports/{rid}/edits/{eid}/vote")
async def vote_edit(
    rid: str, eid: str, body: "srv.ReportEditVoteIn", request: Request
):
    """Up/down-vote a proposed edit. Net vote >= 2 → auto-applies."""
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    edits = r.get("edits", [])
    target = next((e for e in edits if e["id"] == eid), None)
    if not target:
        raise HTTPException(status_code=404, detail="Edit not found")
    ups = target.get("upvotes", [])
    downs = target.get("downvotes", [])
    uid = u["user_id"]
    had_prior_vote = uid in ups or uid in downs
    # Reset existing vote, then apply the new one.
    ups = [x for x in ups if x != uid]
    downs = [x for x in downs if x != uid]
    if body.vote == "up":
        ups.append(uid)
    else:
        downs.append(uid)
    target["upvotes"] = ups
    target["downvotes"] = downs
    net = len(ups) - len(downs)

    # Reward voters (1 pt) — once per edit, not on every toggle.
    if not had_prior_vote and uid != target.get("proposer_id"):
        await srv.db.users.update_one(
            {"user_id": uid}, {"$inc": {"points": 1}}
        )

    just_applied = False
    if net >= 2 and not target.get("applied"):
        target["applied"] = True
        target["applied_at"] = srv.now_utc()
        just_applied = True
        # Reward the proposer when the community validates them.
        if target.get("proposer_id"):
            await srv.db.users.update_one(
                {"user_id": target["proposer_id"]}, {"$inc": {"points": 5}}
            )
        # Apply the side-effect on the parent report.
        update: dict = {}
        if target["kind"] == "fake":
            update["flagged_fake"] = True
        elif target["kind"] == "ended":
            update["status"] = "ended"
        elif target["kind"] == "shift":
            if (
                target.get("new_lat") is not None
                and target.get("new_lng") is not None
            ):
                update["lat"] = target["new_lat"]
                update["lng"] = target["new_lng"]
        if update:
            await srv.db.reports.update_one({"id": rid}, {"$set": update})
        # V1.2 — Phase 2 gamification: apply the new penalty rules on the
        # infirmed author (fake ≥2 votes = déclaré faux).
        from core import points as PT
        if target["kind"] == "fake" and r.get("author_id"):
            await PT.award_both(
                srv.db, r["author_id"],
                delta_points=PT.POINTS_FALSE_REPORT,
                delta_reliability=PT.RELIABILITY_FALSE,
                reason=PT.REASON_FALSE,
                report_id=rid,
            )
        elif target["kind"] == "ended" and r.get("author_id"):
            # "Ended" is a softer signal — light reliability hit only, mirrors
            # the historical -1 pos/neg penalty (-2 %). No grade impact.
            await PT.award_reliability(
                srv.db, r["author_id"],
                PT.RELIABILITY_INFIRM_LT1H,
                PT.REASON_INFIRM,
                report_id=rid,
            )

    await srv.db.reports.update_one(
        {"id": rid},
        {"$set": {"edits": edits}},
    )

    if just_applied and r.get("author_id") and r["author_id"] != uid:
        try:
            await srv.send_push(
                recipients=[r["author_id"]],
                data={
                    "title": "Proposition appliquée",
                    "message": "La communauté a validé un changement sur votre signalement.",
                    "action_url": f"/report/{rid}",
                },
                idempotency_key=f"applied:{rid}:{target['id']}",
            )
        except Exception as e:
            srv.logger.warning("push apply-edit failed: %s", e)

    fresh = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    return srv.serialize_report(fresh, uid)
