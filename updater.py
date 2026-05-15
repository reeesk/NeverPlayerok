from colorama import Fore
from logging import getLogger

logger = getLogger("universal.updater")


def check_for_updates():
    """Auto-update is intentionally disabled in this fork."""
    logger.info(f"{Fore.YELLOW}Авто-обновление отключено для playerok-neverboost.")
