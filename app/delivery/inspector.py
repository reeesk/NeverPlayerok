from dataclasses import dataclass
import logging

import httpx

from app.delivery.invite import Invite

logger = logging.getLogger("neverboost-playerok.invites")


@dataclass(frozen=True)
class InviteInspection:
    valid: bool
    server_name: str | None = None
    join_requests: bool = False


async def inspect_invite(invite: Invite) -> InviteInspection:
    logger.info("Проверка Discord-инвайта: %s", invite.url)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://discord.com/api/v9/invites/{invite.code}?with_counts=true",
                headers={"User-Agent": "NeverPlayerok/1.0"},
            )
        if response.status_code != 200:
            logger.info("Discord-инвайт отклонён: HTTP %s", response.status_code)
            return InviteInspection(False)
        payload = response.json()
        guild = payload.get("guild") or {}
        features = guild.get("features") or []
        result = InviteInspection(
            valid=bool(guild.get("id")),
            server_name=str(guild.get("name") or "Discord-сервер"),
            join_requests="MEMBER_VERIFICATION_MANUAL_APPROVAL" in features,
        )
        logger.info("Discord-инвайт принят: server=%s join_requests=%s", result.server_name, result.join_requests)
        return result
    except (httpx.HTTPError, ValueError, TypeError):
        logger.exception("Ошибка проверки Discord-инвайта")
        return InviteInspection(False)
