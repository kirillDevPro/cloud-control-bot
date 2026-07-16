"""Shared callback_data -> Server resolution for the router layer.

Both the monitoring and servers routers decode a callback's composite server key and look
the server up; this is the single copy they share. ``parse_server_key`` decodes and
validates the key (handling the hashed form for long AWS keys); ``resolve_server`` builds
on it to fetch the Server, answering the user and returning None on any failure.
"""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery

from ...models import Server
from ...storage import ServersRepository
from ..i18n import _
from .callback_data import decode_callback_data

logger = logging.getLogger(__name__)


def parse_server_key(callback_data: str | None, prefix: str = "") -> str | None:
    """Safely extract the composite server key from callback_data.

    Handles both plain keys and the hashed form used for long AWS keys, and guards against a
    None/short/malformed payload.

    Args:
        callback_data: Callback data string (may be None).
        prefix: Prefix to strip before decoding.

    Returns:
        str | None: The full server key (e.g. "hetzner_prod:12345"), or None on error.
    """
    try:
        server_key = decode_callback_data(callback_data, prefix)
        if not server_key:
            logger.error(f"Failed to decode callback_data: {callback_data}")
            return None
        if ":" not in server_key:
            logger.error(f"Invalid server_key format (missing ':'): {server_key}")
            return None
        return server_key
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"Failed to parse server_key from '{callback_data}': {e}", exc_info=True)
        return None


async def resolve_server(
    callback: CallbackQuery, servers_repo: ServersRepository, prefix: str
) -> Server | None:
    """Decode callback_data, validate the key, and look up a server.

    On any failure it answers the user (a localized toast) and returns None.

    Args:
        callback: Callback query carrying encoded server data.
        servers_repo: Server repository used for the composite-key lookup.
        prefix: callback_data prefix to strip before decoding.

    Returns:
        Server | None: The resolved server, or None if the key is invalid or not found.
    """
    server_key = parse_server_key(callback.data, prefix)
    if not server_key:
        await callback.answer(_("common.invalid_data_format"))
        return None

    server = servers_repo.get_by_composite_key(server_key)
    if not server:
        await callback.answer(_("common.server_not_found"))
        return None

    return server
