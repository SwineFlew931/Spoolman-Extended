"""Reboot and shut down the host the reader is attached to.

Spoolman has no way to restart its own machine, which matters most in the one
situation where a terminal is least convenient: the server is misbehaving, or an
SD card is about to be swapped and the filesystem should be stopped cleanly
first. This lives here rather than in Spoolman because Spoolman's Python is kept
stock, and because this service already runs as the operator's own user.

What bounds this is ACTIONS below: a closed mapping, so no value a caller sends
can name a command that is not in it. That is the real guard, and it has to be,
because the service user often already has blanket NOPASSWD sudo -- the
Raspberry Pi OS default -- in which case a sudoers drop-in restricts nothing.

The drop-in in nfcwriter/sudoers/ is still worth installing: on a host where the
service user does *not* have full sudo, it is what makes these two commands work
and nothing else. Whether it is in place is discovered rather than assumed --
`permitted` asks sudo, so a GUI does not offer a button that would only fail.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess

from nfcwriter import config

logger = logging.getLogger(__name__)

# The argument each action passes to systemctl. Deliberately a closed mapping:
# nothing a caller sends can widen it, and the sudoers drop-in grants exactly
# these two and no other verb.
ACTIONS = {
    "reboot": "reboot",
    "shutdown": "poweroff",
}

# Long enough for the HTTP response to reach the browser before systemd starts
# stopping units, short enough that the click feels like it did something.
GRACE_SECONDS = 0.5


def _systemctl() -> str:
    """The absolute path sudo will be asked about.

    sudoers matches on the path, so a bare name would not match the rule.
    """
    return shutil.which("systemctl") or "/usr/bin/systemctl"


def _command(action: str) -> list[str]:
    return ["sudo", "-n", _systemctl(), ACTIONS[action]]


def permitted(action: str) -> bool:
    """Whether this user may run the action right now, without a password.

    `sudo -n -l <command>` exits non-zero when the command is not permitted or
    when sudo would need to ask for anything, which is exactly the question a
    caller wants answered. It runs nothing.
    """
    if action not in ACTIONS:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, closed action set
            ["sudo", "-n", "-l", _systemctl(), ACTIONS[action]],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("could not ask sudo about %s", action, exc_info=True)
        return False
    return result.returncode == 0


def available() -> dict[str, bool]:
    """Which actions this host will actually accept."""
    if not config.POWER_ENABLED:
        return dict.fromkeys(ACTIONS, False)
    return {action: permitted(action) for action in ACTIONS}


async def trigger(action: str) -> None:
    """Run the action, after a pause long enough to answer the caller first."""
    await asyncio.sleep(GRACE_SECONDS)
    command = _command(action)
    logger.info("running %s", " ".join(command))
    try:
        subprocess.Popen(command)  # noqa: S603 - fixed argv, no shell, closed action set
    except (OSError, subprocess.SubprocessError):
        # Nothing useful to tell the caller by now: it has its 200 and the
        # browser may already be gone. The log is the only place left.
        logger.exception("failed to run %s", " ".join(command))
