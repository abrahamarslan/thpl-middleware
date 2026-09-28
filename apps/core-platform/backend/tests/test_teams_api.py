"""Departments, job titles, team types/roles, teams and memberships — over the real API and database."""

import datetime as dt

from sqlalchemy import select

from app.modules.roles.model import Role
from app.modules.teams.model import Department

DEPT = {"department_code": "OPS", "department_name": "Operations"}


async def role_of(db, org, code) -> Role:
    return await db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == code))


async def make(client, headers, path, body):
    response = await client.post(path, headers=headers, json=body)
    assert response.status_code == 201, (path, response.text)
    return response.json()["data"]


# ── departments: a tree maintained by one routine ───────────────────────────

async def test_departments_form_a_tree_with_maintained_bounds(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    ops = await make(client, h, "/api/departments", DEPT)
    fleet = await make(client, h, "/api/departments", {"department_code": "FLEET", "department_name": "Fleet",
                                                       "parent": ops["uuid"]})
    await make(client, h, "/api/departments", {"department_code": "LM", "department_name": "Last mile",
                                               "parent": fleet["uuid"]})

    tree = (await client.get("/api/departments/tree", headers=h, params={"organization": w.branch_a.org_code})).json()["data"]
    assert [n["code"] for n in tree] == ["OPS"]
    assert [c["code"] for c in tree[0]["children"]] == ["FLEET"]
    assert [c["code"] for c in tree[0]["children"][0]["children"]] == ["LM"]
    assert [n["depth"] for n in (tree[0], tree[0]["children"][0], tree[0]["children"][0]["children"][0])] == [0, 1, 2]

    sub = (await client.get(f"/api/departments/{ops['uuid']}/subtree", headers=h)).json()["data"]
    assert {d["department_code"] for d in sub} == {"FLEET", "LM"}


async def test_a_department_cannot_be_moved_under_itself_or_a_descendant(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    ops = await make(client, h, "/api/departments", DEPT)
    child = await make(client, h, "/api/departments", {"department_code": "FLEET", "department_name": "Fleet",
                                                       "parent": ops["uuid"]})
    refused = await client.post(f"/api/departments/{ops['uuid']}/move", headers=h,
                                json={"parent": child["uuid"], "row_version": ops["row_version"]})
    assert refused.status_code == 422 and "descendants" in refused.json()["msg"]
    # ... and the tree is unchanged.
    tree = (await client.get("/api/departments/tree", headers=h)).json()["data"]
    assert [n["code"] for n in tree if n["code"] == "OPS"]


async def test_a_department_can_be_moved_and_becomes_a_root_again(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    ops = await make(client, h, "/api/departments", DEPT)
    fleet = await make(client, h, "/api/departments", {"department_code": "FLEET", "department_name": "Fleet"})
    moved = await client.post(f"/api/departments/{fleet['uuid']}/move", headers=h,
                              json={"parent": ops["uuid"], "row_version": fleet["row_version"]})
    assert moved.status_code == 200 and moved.json()["data"]["parent_id"] == ops["id"]
    assert moved.json()["data"]["depth"] == 1
    again = await client.post(f"/api/departments/{fleet['uuid']}/move", headers=h,
                              json={"parent": None, "row_version": moved.json()["data"]["row_version"]})
    assert again.json()["data"]["parent_id"] is None and again.json()["data"]["depth"] == 0


async def test_a_department_code_can_be_reused_after_deletion_but_not_while_live(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    first = await make(client, h, "/api/departments", DEPT)
    dup = await client.post("/api/departments", headers=h, json=DEPT)
    assert dup.status_code == 409

    gone = await client.delete(f"/api/departments/{first['uuid']}", headers=h, params={"reason": "reorganised"})
    assert gone.status_code == 200
    reused = await client.post("/api/departments", headers=h, json=DEPT)
    assert reused.status_code == 201, "history must not block a live code"


async def test_a_department_with_children_or_teams_cannot_be_deleted(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    ops = await make(client, h, "/api/departments", DEPT)
    await make(client, h, "/api/departments", {"department_code": "FLEET", "department_name": "Fleet",
                                               "parent": ops["uuid"]})
    refused = await client.delete(f"/api/departments/{ops['uuid']}", headers=h, params={"reason": "cleanup"})
    assert refused.status_code == 422 and "child department" in refused.json()["msg"]


async def test_the_database_refuses_a_parent_from_another_organization(tree_world, db):
    """The composite FK is the second wall: even code that skips the service cannot cross organizations."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    client, w = tree_world
    parent = await make(client, w.auth(w.admin_b, w.branch_b), "/api/departments", DEPT)
    child = await make(client, w.auth(w.admin_a, w.branch_a), "/api/departments",
                       {"department_code": "FLEET", "department_name": "Fleet"})
    row = await db.scalar(select(Department).where(Department.id == child["id"]))
    row.parent_id = parent["id"]                       # a parent of ANOTHER organization
    row.is_root = False
    with pytest.raises(IntegrityError, match="fk_departments_parent"):
        await db.flush()
    await db.rollback()


async def test_departments_live_inside_their_tenant(worlds):
    client, acme, globex = worlds
    dept = await make(client, acme.auth(acme.admin, **{"X-Organization-Code": "ACME-HQ"}), "/api/departments", DEPT)
    seen = await client.get(f"/api/departments/{dept['uuid']}", headers=globex.auth(globex.admin))
    assert seen.status_code == 404


async def test_a_department_scoped_grant_covers_that_department_only(tree_world, db):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    ops = await make(client, h, "/api/departments", DEPT)
    fin = await make(client, h, "/api/departments", {"department_code": "FIN", "department_name": "Finance"})
    head = await role_of(db, w.branch_a, "department_head")
    granted = await client.post(f"/api/users/{w.member_a.id}/roles", headers=h, json={
        "role": str(head.id), "scope_type": "department", "department_id": ops["id"]})
    assert granted.status_code == 201, granted.text

    mine = w.auth(w.member_a, w.branch_a)
    ok = await client.patch(f"/api/departments/{ops['uuid']}", headers=mine,
                            json={"description": "Runs the fleet", "row_version": ops["row_version"]})
    assert ok.status_code == 200, ok.text
    other = await client.patch(f"/api/departments/{fin['uuid']}", headers=mine,
                               json={"description": "nope", "row_version": fin["row_version"]})
    assert other.status_code == 403, "a department-scoped grant does not leak to the department next door"
    # ... and it does not become an organization-wide permission either.
    assert (await client.post("/api/departments", headers=mine, json={
        "department_code": "NEW", "department_name": "New"})).status_code == 403


async def test_job_titles_belong_to_a_department_of_the_same_organization(tree_world):
    client, w = tree_world
    ha, hb = w.auth(w.admin_a, w.branch_a), w.auth(w.admin_b, w.branch_b)
    dept_b = await make(client, hb, "/api/departments", DEPT)
    refused = await client.post("/api/job-titles", headers=ha, json={
        "job_code": "RIDER", "title": "Rider", "department": dept_b["uuid"]})
    assert refused.status_code == 422 and "different organization" in refused.json()["msg"]

    dept_a = await make(client, ha, "/api/departments", DEPT)
    title = await make(client, ha, "/api/job-titles", {"job_code": "RIDER", "title": "Rider",
                                                       "department": dept_a["uuid"], "band_level": 2})
    assert title["department_id"] == dept_a["id"]
    listed = (await client.get("/api/job-titles", headers=ha, params={"q": "rid"})).json()["data"]
    assert [t["job_code"] for t in listed["items"]] == ["RIDER"]


# ── teams and membership ────────────────────────────────────────────────────

async def team_setup(client, h):
    team_type = await make(client, h, "/api/team-types", {"type_code": "DELIVERY", "type_name": "Delivery"})
    team = await make(client, h, "/api/teams", {"team_code": "GDH-1", "team_name": "Godhra 1",
                                                "team_type": team_type["uuid"]})
    return team_type, team


async def test_teams_form_a_tree_under_a_team_type(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    team_type, team = await team_setup(client, h)
    sub = await make(client, h, "/api/teams", {"team_code": "GDH-1A", "team_name": "Godhra 1A",
                                               "team_type": team_type["uuid"], "parent": team["uuid"]})
    assert sub["depth"] == 1
    tree = (await client.get("/api/teams/tree", headers=h, params={"organization": w.branch_a.org_code})).json()["data"]
    assert tree[0]["code"] == "GDH-1" and tree[0]["children"][0]["code"] == "GDH-1A"

    in_use = await client.delete(f"/api/team-types/{team_type['uuid']}", headers=h, params={"reason": "cleanup"})
    assert in_use.status_code == 422 and "team(s)" in in_use.json()["msg"]


async def test_a_member_is_added_approved_and_can_leave_and_rejoin(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    _, team = await team_setup(client, h)

    added = await client.post(f"/api/teams/{team['uuid']}/members", headers=h, json={"user_id": w.member_a.id})
    assert added.status_code == 201, added.text
    member = added.json()["data"]
    assert member["approval_status"] == "approved" and member["approved_by"] == w.admin_a.id

    dup = await client.post(f"/api/teams/{team['uuid']}/members", headers=h, json={"user_id": w.member_a.id})
    assert dup.status_code == 409

    left = await client.delete(f"/api/teams/{team['uuid']}/members/{member['uuid']}", headers=h,
                               params={"reason": "moved to another team"})
    assert left.status_code == 200 and left.json()["data"]["valid_until"] is not None
    open_now = (await client.get(f"/api/teams/{team['uuid']}/members", headers=h)).json()["data"]["items"]
    assert open_now == []
    history = (await client.get(f"/api/teams/{team['uuid']}/members", headers=h,
                                params={"include_ended": True})).json()["data"]["items"]
    assert len(history) == 1

    rejoined = await client.post(f"/api/teams/{team['uuid']}/members", headers=h, json={"user_id": w.member_a.id})
    assert rejoined.status_code == 201, "leaving is history; it must not block rejoining"


async def test_a_user_has_one_primary_team_at_a_time(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    team_type, first = await team_setup(client, h)
    second = await make(client, h, "/api/teams", {"team_code": "GDH-2", "team_name": "Godhra 2",
                                                  "team_type": team_type["uuid"]})
    a = await client.post(f"/api/teams/{first['uuid']}/members", headers=h,
                          json={"user_id": w.member_a.id, "is_primary": True})
    b = await client.post(f"/api/teams/{second['uuid']}/members", headers=h,
                          json={"user_id": w.member_a.id, "is_primary": True})
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    mine = (await client.get("/api/me/teams", headers=w.auth(w.member_a, w.branch_a))).json()["data"]
    assert {m["team_code"]: m["is_primary"] for m in mine} == {"GDH-1": False, "GDH-2": True}


async def test_nobody_approves_their_own_membership(tree_world, db):
    client, w = tree_world
    _, team = await team_setup(client, w.auth(w.admin_a, w.branch_a))
    manager = await role_of(db, w.branch_a, "team_manager")
    granted = await client.post(f"/api/users/{w.member_a.id}/roles", headers=w.auth(w.admin_a, w.branch_a), json={
        "role": str(manager.id), "scope_type": "organization", "organization": w.branch_a.org_code})
    assert granted.status_code == 201

    mine = w.auth(w.member_a, w.branch_a)          # a team manager: may assign AND approve
    self_add = await client.post(f"/api/teams/{team['uuid']}/members", headers=mine, json={"user_id": w.member_a.id})
    assert self_add.status_code == 201
    row = self_add.json()["data"]
    assert row["approval_status"] == "pending", "an actor who is the member never approves on the spot"

    self_approve = await client.post(f"/api/teams/{team['uuid']}/members/{row['uuid']}/approve", headers=mine)
    assert self_approve.status_code == 403
    by_admin = await client.post(f"/api/teams/{team['uuid']}/members/{row['uuid']}/approve",
                                 headers=w.auth(w.admin_a, w.branch_a), json={"notes": "welcome"})
    assert by_admin.status_code == 200 and by_admin.json()["data"]["approval_status"] == "approved"


async def test_a_team_role_carries_permissions_only_while_the_membership_is_in_force(tree_world, db):
    """team_roles.rbac_role_id: the member holds that role SCOPED TO THE TEAM — and loses it on leaving."""
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    team_type, team = await team_setup(client, h)
    sibling = await make(client, h, "/api/teams", {"team_code": "GDH-2", "team_name": "Godhra 2",
                                                   "team_type": team_type["uuid"]})
    manager = await role_of(db, w.branch_a, "team_manager")
    lead = await make(client, h, "/api/team-roles", {
        "role_code": "LEAD", "role_name": "Team lead", "team_type": team_type["uuid"],
        "rbac_role": str(manager.id), "is_default": True})
    assert lead["rbac_role_id"] == manager.id

    added = await client.post(f"/api/teams/{team['uuid']}/members", headers=h, json={"user_id": w.member_a.id})
    assert added.status_code == 201 and added.json()["data"]["team_role_id"] == lead["id"]   # the type's default role

    mine = w.auth(w.member_a, w.branch_a)
    own = await client.patch(f"/api/teams/{team['uuid']}", headers=mine,
                             json={"description": "our team", "row_version": team["row_version"]})
    assert own.status_code == 200, own.text
    theirs = await client.patch(f"/api/teams/{sibling['uuid']}", headers=mine,
                                json={"description": "not ours", "row_version": sibling["row_version"]})
    assert theirs.status_code == 403, "the grant is scoped to the team the member belongs to"
    grants = (await client.get("/api/me/permissions", headers=mine)).json()["data"]["grants"]
    assert {g["scope"] for g in grants} == {"organization", "team"}

    member = added.json()["data"]
    await client.delete(f"/api/teams/{team['uuid']}/members/{member['uuid']}", headers=h, params={"reason": "left"})
    after = await client.patch(f"/api/teams/{team['uuid']}", headers=mine,
                               json={"description": "again", "row_version": own.json()["data"]["row_version"]})
    assert after.status_code == 403, "leaving the team ends the grant — nothing to clean up"


async def test_an_expired_membership_grants_nothing(tree_world, db):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    team_type, team = await team_setup(client, h)
    manager = await role_of(db, w.branch_a, "team_manager")
    await make(client, h, "/api/team-roles", {"role_code": "LEAD", "role_name": "Lead",
                                              "team_type": team_type["uuid"], "rbac_role": str(manager.id),
                                              "is_default": True})
    past = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    added = await client.post(f"/api/teams/{team['uuid']}/members", headers=h, json={
        "user_id": w.member_a.id, "valid_from": past.isoformat(),
        "valid_until": (past + dt.timedelta(days=1)).isoformat()})
    assert added.status_code == 201, added.text
    grants = (await client.get("/api/me/permissions", headers=w.auth(w.member_a, w.branch_a))).json()["data"]["grants"]
    assert [g["scope"] for g in grants] == ["organization"]


async def test_a_team_role_cannot_map_to_a_role_you_could_not_grant(tree_world, db):
    client, w = tree_world
    h_member = w.auth(w.member_a, w.branch_a)
    owner = await role_of(db, w.branch_a, "owner")
    refused = await client.post("/api/team-roles", headers=h_member, json={
        "role_code": "BOSS", "role_name": "Boss", "rbac_role": str(owner.id)})
    assert refused.status_code == 403                    # a member cannot even create team roles

    admin_tries = await client.post("/api/team-roles", headers=w.auth(w.admin_a, w.branch_a), json={
        "role_code": "BOSS", "role_name": "Boss", "rbac_role": str(owner.id)})
    assert admin_tries.status_code == 403, "only the owner-only permission holder may map a team role to `owner`"


async def test_a_team_role_for_another_team_type_is_refused(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    team_type, team = await team_setup(client, h)
    other_type = await make(client, h, "/api/team-types", {"type_code": "SUPPORT", "type_name": "Support"})
    role = await make(client, h, "/api/team-roles", {"role_code": "AGENT", "role_name": "Agent",
                                                     "team_type": other_type["uuid"]})
    refused = await client.post(f"/api/teams/{team['uuid']}/members", headers=h,
                                json={"user_id": w.member_a.id, "team_role": role["uuid"]})
    assert refused.status_code == 422 and "different team type" in refused.json()["msg"]


async def test_bulk_membership_is_authorized_per_item_and_all_or_nothing(tree_world):
    client, w = tree_world
    ha, hb = w.auth(w.admin_a, w.branch_a), w.auth(w.admin_b, w.branch_b)
    type_a, team_a = await team_setup(client, ha)
    type_b = await make(client, hb, "/api/team-types", {"type_code": "DELIVERY", "type_name": "Delivery"})
    team_b = await make(client, hb, "/api/teams", {"team_code": "GDH-B", "team_name": "B team",
                                                   "team_type": type_b["uuid"]})
    items = [{"team": team_a["uuid"], "user_id": w.member_a.id},
             {"team": team_b["uuid"], "user_id": w.member_a.id}]

    refused = await client.post("/api/teams/members/bulk", headers=ha, json={"items": items})
    assert refused.status_code == 403 and refused.json()["data"]["denied_indexes"] == [1]
    assert (await client.get(f"/api/teams/{team_a['uuid']}/members", headers=ha)).json()["data"]["items"] == []

    partial = await client.post("/api/teams/members/bulk", headers=ha, params={"partial": True}, json={"items": items})
    assert partial.status_code == 201, partial.text
    data = partial.json()["data"]
    assert len(data["added"]) == 1 and data["denied"] == [1]

    too_many = await client.post("/api/teams/members/bulk", headers=ha, json={"items": items * 101})
    assert too_many.status_code == 422


# ── employment ──────────────────────────────────────────────────────────────

async def test_employment_placement_and_the_reporting_line(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    dept = await make(client, h, "/api/departments", DEPT)
    title = await make(client, h, "/api/job-titles", {"job_code": "LEAD", "title": "Team lead",
                                                      "department": dept["uuid"]})
    base = {"personnel_type": "supervisor", "employment_type": "full_time", "date_of_joining": "2026-01-05"}
    boss = await make(client, h, "/api/hr/employment", {**base, "user_id": w.admin_a.id, "employee_code": "E-1",
                                                        "department": dept["uuid"], "job_title": title["uuid"]})
    report = await make(client, h, "/api/hr/employment", {
        **base, "user_id": w.member_a.id, "employee_code": "E-2", "reporting_manager_user_id": w.admin_a.id})

    dup = await client.post("/api/hr/employment", headers=h, json={**base, "user_id": w.member_a.id,
                                                                   "employee_code": "E-3"})
    assert dup.status_code == 409 and "current employment record" in dup.json()["msg"]

    loop = await client.patch(f"/api/hr/employment/{boss['id']}", headers=h, json={
        "reporting_manager_user_id": w.member_a.id, "row_version": boss["row_version"]})
    assert loop.status_code == 422 and "loop" in loop.json()["msg"]
    self_manager = await client.patch(f"/api/hr/employment/{report['id']}", headers=h, json={
        "reporting_manager_user_id": w.member_a.id, "row_version": report["row_version"]})
    assert self_manager.status_code == 422

    chart = (await client.get("/api/hr/org-chart", headers=h, params={"organization": w.branch_a.org_code})).json()["data"]
    assert [n["user_id"] for n in chart] == [w.admin_a.id]
    assert [n["user_id"] for n in chart[0]["reports"]] == [w.member_a.id]

    ended = await client.post(f"/api/hr/employment/{report['id']}/end", headers=h, json={
        "date_of_exit": "2026-08-01", "employment_status": "resigned", "row_version": report["row_version"]})
    assert ended.status_code == 200 and ended.json()["data"]["is_current"] is False
    chart = (await client.get("/api/hr/org-chart", headers=h, params={"organization": w.branch_a.org_code})).json()["data"]
    assert chart[0]["reports"] == []


async def test_employment_department_must_be_in_the_same_organization(tree_world):
    client, w = tree_world
    dept_b = await make(client, w.auth(w.admin_b, w.branch_b), "/api/departments", DEPT)
    refused = await client.post("/api/hr/employment", headers=w.auth(w.admin_a, w.branch_a), json={
        "user_id": w.member_a.id, "employee_code": "E-9", "personnel_type": "driver",
        "employment_type": "full_time", "date_of_joining": "2026-01-05", "department": dept_b["uuid"]})
    assert refused.status_code == 422 and "different organization" in refused.json()["msg"]


async def test_a_member_cannot_read_employment(tree_world):
    client, w = tree_world
    assert (await client.get("/api/hr/employment", headers=w.auth(w.member_a, w.branch_a))).status_code == 403


# ── addresses: a department sits where geo says it sits ─────────────────────

async def test_a_department_can_own_an_address_through_the_address_book(tree_world):
    client, w = tree_world
    h = w.auth(w.admin_a, w.branch_a)
    dept = await make(client, h, "/api/departments", DEPT)
    attached = await client.post("/api/addresses", headers=h, json={
        "owner_type": "department", "owner_id": dept["id"], "link_type": "office", "label": "Head office",
        "new_place": {"kind": "office", "street": "1 Main Road", "city": "Godhra", "postal_code": "389001"},
        "custom_attributes": {"floor": "3", "room": "12"}})
    assert attached.status_code == 201, attached.text
    listed = (await client.get("/api/addresses", headers=h,
                               params={"owner_type": "department", "owner_id": dept["id"]})).json()["data"]
    assert listed and listed[0]["custom_attributes"] == {"floor": "3", "room": "12"}
