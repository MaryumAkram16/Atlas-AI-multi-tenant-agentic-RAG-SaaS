"""Role rules, checked in the API for clear errors and mirrored by RLS
policies (migration 0001) so they hold for direct database access too."""

from uuid import UUID

from app.tenants.roles import MANAGERS


class RoleRuleError(Exception):
    """The actor may not perform this membership change."""


# Roles each manager role may assign / act on.
_ASSIGNABLE = {"owner": {"admin", "member", "viewer"}, "admin": {"member", "viewer"}}


def _require_manager(actor_role: str) -> None:
    if actor_role not in MANAGERS:
        raise RoleRuleError("only owners and admins can manage members")


def check_role_change(
    *,
    actor_role: str,
    actor_user_id: UUID,
    target_user_id: UUID,
    target_role: str,
    target_status: str,
    new_role: str,
) -> None:
    if target_user_id == actor_user_id:
        raise RoleRuleError("you cannot change your own role")
    _require_manager(actor_role)
    if target_status != "active":
        raise RoleRuleError("membership is revoked")
    if target_role not in _ASSIGNABLE[actor_role]:
        raise RoleRuleError(f"{actor_role}s cannot change the role of a {target_role}")
    if new_role not in _ASSIGNABLE[actor_role]:
        raise RoleRuleError(f"{actor_role}s cannot grant the {new_role} role")


def check_revoke(
    *, actor_role: str, actor_user_id: UUID, target_user_id: UUID, target_role: str
) -> None:
    if target_user_id == actor_user_id:
        raise RoleRuleError("you cannot revoke your own membership")
    _require_manager(actor_role)
    if target_role not in _ASSIGNABLE[actor_role]:
        raise RoleRuleError(f"{actor_role}s cannot revoke a {target_role}")


def check_invite(*, actor_role: str, invite_role: str) -> None:
    _require_manager(actor_role)
    if invite_role not in _ASSIGNABLE[actor_role]:
        raise RoleRuleError(f"{actor_role}s cannot invite a {invite_role}")
