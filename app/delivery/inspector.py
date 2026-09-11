from dataclasses import dataclass

import httpx

from app.delivery.invite import Invite


@dataclass(frozen=True)
class InviteInspection:
    valid: bool
    server_name: str | None = None
    join_requests: bool = False


async def inspect_invite(invite: Invite) -> InviteInspection:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://discord.com/api/v9/invites/{invite.code}?with_counts=true",
                headers={"User-Agent": "NeverPlayerok/1.0"},
            )
        if response.status_code != 200:
            return InviteInspection(False)
        payload = response.json()
        guild = payload.get("guild") or {}
        features = guild.get("features") or []
        return InviteInspection(
            valid=bool(guild.get("id")),
            server_name=str(guild.get("name") or "Discord-сервер"),
            join_requests="MEMBER_VERIFICATION_MANUAL_APPROVAL" in features,
        )
    except (httpx.HTTPError, ValueError, TypeError):
        return InviteInspection(False)
