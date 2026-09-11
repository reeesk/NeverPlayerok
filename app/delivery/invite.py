import re
from dataclasses import dataclass


INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Invite:
    code: str

    @property
    def url(self) -> str:
        return f"https://discord.gg/{self.code}"


def extract_invite(text: str) -> Invite | None:
    match = INVITE_RE.search(str(text or ""))
    if match:
        return Invite(match.group(1))
    return None
