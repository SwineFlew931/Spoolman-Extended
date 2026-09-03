"""Deployment configuration for the NFC integration.

Only settings that belong to the *installation* live here. Anything a user
should be able to change while the server is running belongs in
:mod:`spoolman.settings` instead, so that it is stored in the database and
editable from the settings page.

Notably the daemon's address is deliberately not a database setting: Spoolman
fetches it server-side, and a URL that any client could rewrite would turn this
endpoint into a request proxy.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_NFCD_URL = "http://127.0.0.1:7913"

# Seconds to wait on a request to nfcd. It answers from in-memory state, so
# anything slower than this means it is wedged rather than busy.
REQUEST_TIMEOUT = 5.0


def is_enabled() -> bool:
    """Get whether the NFC integration is enabled.

    Off unless explicitly turned on, so that an installation with no reader
    attached behaves exactly like upstream Spoolman.

    Returns:
        bool: Whether the NFC integration is enabled.

    """
    enabled = os.getenv("SPOOLMAN_NFC_ENABLED", "FALSE").upper()
    return enabled not in {"FALSE", "0"}


def get_nfcd_url() -> str:
    """Get the base URL of the nfcd reader daemon.

    Returns:
        str: The base URL, without a trailing slash.

    """
    return os.getenv("SPOOLMAN_NFCD_URL", DEFAULT_NFCD_URL).rstrip("/")
