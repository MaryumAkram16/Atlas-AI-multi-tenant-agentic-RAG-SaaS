from typing import Literal

Role = Literal["owner", "admin", "member", "viewer"]
InviteRole = Literal["admin", "member", "viewer"]
ROLES: tuple[str, ...] = ("owner", "admin", "member", "viewer")
MANAGERS = frozenset({"owner", "admin"})
