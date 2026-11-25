"""Pure role-change rules (mirrored by RLS in the database)."""

import uuid

import pytest

from app.tenants.rules import RoleRuleError, check_invite, check_revoke, check_role_change

ME = uuid.uuid4()
OTHER = uuid.uuid4()


def change(actor_role, target_role, new_role, target_user=OTHER, target_status="active"):
    check_role_change(
        actor_role=actor_role,
        actor_user_id=ME,
        target_user_id=target_user,
        target_role=target_role,
        target_status=target_status,
        new_role=new_role,
    )


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
@pytest.mark.parametrize("new_role", ["owner", "admin", "member", "viewer"])
def test_nobody_changes_their_own_role(role, new_role):
    with pytest.raises(RoleRuleError):
        change(role, role, new_role, target_user=ME)


@pytest.mark.parametrize("actor", ["member", "viewer"])
def test_members_and_viewers_cannot_change_roles(actor):
    with pytest.raises(RoleRuleError):
        change(actor, "viewer", "member")


def test_owner_can_promote_and_demote():
    change("owner", "member", "admin")
    change("owner", "admin", "viewer")


def test_admin_can_move_between_member_and_viewer():
    change("admin", "member", "viewer")
    change("admin", "viewer", "member")


@pytest.mark.parametrize(
    "target_role,new_role",
    [("member", "admin"), ("admin", "member"), ("owner", "member"), ("member", "owner")],
)
def test_admin_limits(target_role, new_role):
    with pytest.raises(RoleRuleError):
        change("admin", target_role, new_role)


def test_nobody_grants_owner():
    with pytest.raises(RoleRuleError):
        change("owner", "admin", "owner")


def test_owner_role_cannot_be_changed():
    with pytest.raises(RoleRuleError):
        change("owner", "owner", "admin")


def test_revoked_member_role_cannot_change():
    with pytest.raises(RoleRuleError):
        change("owner", "member", "admin", target_status="revoked")


def test_revoke_rules():
    check_revoke(actor_role="owner", actor_user_id=ME, target_user_id=OTHER, target_role="admin")
    check_revoke(actor_role="admin", actor_user_id=ME, target_user_id=OTHER, target_role="viewer")
    for actor, target, target_user in [
        ("admin", "admin", OTHER),
        ("admin", "owner", OTHER),
        ("owner", "owner", ME),
        ("member", "viewer", OTHER),
        ("admin", "admin", ME),
    ]:
        with pytest.raises(RoleRuleError):
            check_revoke(
                actor_role=actor, actor_user_id=ME, target_user_id=target_user, target_role=target
            )


def test_invite_rules():
    check_invite(actor_role="owner", invite_role="admin")
    check_invite(actor_role="admin", invite_role="member")
    for actor, role in [("admin", "admin"), ("owner", "owner"), ("member", "viewer")]:
        with pytest.raises(RoleRuleError):
            check_invite(actor_role=actor, invite_role=role)
