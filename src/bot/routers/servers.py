"""Server-management router for provider selection and power operations."""

import asyncio
import logging
import threading
import time
from multiprocessing.managers import DictProxy

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from ...models import Server
from ...providers.base import BaseProvider
from ...storage import ServersRepository, SqliteStatisticsRepository
from ...providers.manager import ProviderManager
from ..filters import MainMenuButton
from ..i18n import _, localize_error, plural
from ..keyboards import (
    get_servers_management_keyboard,
    get_server_control_keyboard,
    get_confirmation_keyboard,
    get_provider_selection_keyboard,
)
from ..utils import (
    safe_edit_message,
    handle_telegram_errors,
    decode_callback_data,
    apply_shared_status,
    show_screen,
)
from ..formatters import (
    format_provider_selection,
    format_servers_management_list,
    format_server_control_details,
    format_confirmation_message,
    format_operation_result,
)

logger = logging.getLogger(__name__)

# Create the router for server management
servers_router = Router(name="servers")

# Cooldown between operations (seconds)
OPERATION_COOLDOWN = 30

# Delay before returning to the control screen after a power operation (seconds)
OPERATION_RESULT_DELAY = 3

# Lock for atomic cooldown operations (prevents the TOCTOU race condition)
_cooldown_lock = threading.Lock()

# Per-composite_key timestamp of the last power operation. Bot-process-local: the
# cooldown is only consulted by bot handlers, never by workers, so it must NOT
# live in the worker-shared DictProxy. Keyed by composite_key (not bare id) to
# avoid cross-account collisions when two providers expose the same server id.
_operation_cooldowns: dict[str, float] = {}


def parse_server_key(callback_data: str, prefix: str = "") -> str | None:
    """Safely extract the composite server key from callback_data.

    Supports both plain keys and hashed ones (for long AWS keys).
    Returns the full server_key for use with get_by_composite_key().

    Args:
        callback_data: Callback data string.
        prefix: Prefix to strip before decoding.

    Returns:
        Full server_key (for example, "hetzner_prod:12345") or None on error.
    """
    try:
        # Decode callback_data (handles hashes for long keys)
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


def try_acquire_cooldown(server_key: str) -> tuple[bool, int]:
    """Atomically check the cooldown and set the operation time if allowed.

    Resolves a TOCTOU race condition: check and set run under a single Lock.
    If the cooldown has elapsed, immediately stores the new operation time.

    Args:
        server_key: Composite key of the server (alias:server_id).

    Returns:
        A tuple of ``(operation_allowed, seconds_until_allowed)``.
    """
    now = time.time()

    with _cooldown_lock:
        last_operation = _operation_cooldowns.get(server_key)

        if last_operation is None:
            # First operation - allow it and store the time
            _operation_cooldowns[server_key] = now
            return True, 0

        time_passed = now - last_operation

        if time_passed >= OPERATION_COOLDOWN:
            # Cooldown has elapsed - allow it and update the time
            _operation_cooldowns[server_key] = now
            return True, 0
        else:
            # Cooldown has not elapsed - reject
            remaining = int(OPERATION_COOLDOWN - time_passed)
            return False, remaining


def clear_operation_cooldown(server_key: str) -> None:
    """Reset the cooldown for a server, usually after a failed operation.

    Args:
        server_key: Composite key of the server (alias:server_id).

    Returns:
        None.
    """
    with _cooldown_lock:
        _operation_cooldowns.pop(server_key, None)


async def _resolve_server(
    callback: CallbackQuery, servers_repo: ServersRepository, prefix: str
) -> Server | None:
    """Decode callback_data, validate the key, and look up a server.

    On error it answers the user itself and returns None.

    Args:
        callback: Callback query carrying encoded server data.
        servers_repo: Server repository used for the composite-key lookup.
        prefix: callback_data prefix to strip before decoding.

    Returns:
        The resolved server, or None if the key is invalid or not found.
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


async def _fetch_power_status(provider_manager: ProviderManager, server: Server) -> str | None:
    """Fetch the current power_status of a server from its provider.

    Args:
        provider_manager: Cloud provider manager.
        server: Server to query by effective alias and provider id.

    Returns:
        The power_status string, or None when the provider is unavailable,
        errors, or returns no server.
    """
    provider = provider_manager.get_provider(server.effective_alias)
    if not provider:
        logger.warning(f"Provider {server.effective_alias} not available")
        return None

    try:
        api_server = await provider.get_server(server.id)
        return api_server.power_status if api_server else None
    except Exception as e:
        logger.error(
            f"Failed to get server data from {server.effective_alias}: {e}", exc_info=True
        )
        return None


def _server_supports_graceful(provider_manager: ProviderManager, server: Server) -> bool:
    """Check whether the server's provider supports graceful shutdown (ACPI).

    Used to conditionally show the graceful shutdown button in the control
    keyboard. If the provider is unavailable, returns False (button hidden).

    Args:
        provider_manager: Cloud provider manager.
        server: Server whose provider capability is checked.

    Returns:
        True if the provider supports graceful shutdown for this server.
    """
    provider = provider_manager.get_provider(server.effective_alias)
    return bool(provider and provider.supports_graceful_shutdown(server.id))


async def _acquire_cooldown_and_provider(
    callback: CallbackQuery,
    server: Server,
    provider_manager: ProviderManager,
) -> BaseProvider | None:
    """Atomically acquire the cooldown and resolve a power-operation provider.

    On failure it answers the user itself (and rolls back the cooldown if the
    provider is unavailable) and returns None.

    Args:
        callback: Callback query to answer on cooldown/provider failures.
        server: Server whose composite key is used for cooldown tracking.
        provider_manager: Cloud provider manager used to resolve the provider.

    Returns:
        The provider ready for the operation, or None when the operation should
        stop before calling a provider method.
    """
    can_execute, remaining = try_acquire_cooldown(server.composite_key)
    if not can_execute:
        await callback.answer(
            plural("srv.cooldown_wait", remaining),
            show_alert=True,
        )
        return None

    provider = provider_manager.get_provider(server.effective_alias)
    if not provider:
        # Reset the cooldown since the operation did not run
        clear_operation_cooldown(server.composite_key)
        await callback.answer(
            _("srv.provider_unavailable", provider=server.effective_alias), show_alert=True
        )
        return None

    return provider


async def _execute_power_action(
    callback: CallbackQuery,
    server: Server,
    provider: BaseProvider,
    action: str,
    *,
    loading_text: str,
) -> None:
    """Execute a power operation and render the control screen afterward.

    The cooldown must already be acquired by the caller (see _acquire_cooldown_and_provider).
    On failure/error it rolls back the cooldown.

    Args:
        callback: Callback query that owns the message being edited.
        server: Server receiving the operation.
        provider: The server's provider.
        action: Operation name ("start", "stop", "reboot", or "shutdown").
        loading_text: Loading-indicator text for callback.answer.

    Returns:
        None.
    """
    await callback.answer(loading_text)

    try:
        if action == "start":
            success = await provider.start_server(server.id)
        elif action == "stop":
            success = await provider.stop_server(server.id)
        elif action == "reboot":
            success = await provider.reboot_server(server.id)
        elif action == "shutdown":
            success = await provider.shutdown_server(server.id)
        else:
            # Defensive guard: action is validated upstream, so this is unreachable.
            # The query was already answered above, so a second answer would be a no-op.
            clear_operation_cooldown(server.composite_key)
            logger.warning(f"Unknown power action: {action}")
            return

        # Reset the cooldown if the operation failed
        if not success:
            clear_operation_cooldown(server.composite_key)

        # Format the result
        text = format_operation_result(action, server.get_display_name(), success)
        await safe_edit_message(callback, text)

        # After a few seconds return to the control screen
        await asyncio.sleep(OPERATION_RESULT_DELAY)

        # Fetch updated info via the already-known provider
        power_status: str | None = None
        try:
            api_server = await provider.get_server(server.id)
            if api_server:
                power_status = api_server.power_status
        except Exception as e:
            # power_status stays None (handled in format_server_control_details)
            logger.warning(f"Failed to get server status from {server.effective_alias}: {e}")

        text = format_server_control_details(server, power_status)
        await safe_edit_message(
            callback,
            text,
            get_server_control_keyboard(
                server.composite_key, power_status, provider.supports_graceful_shutdown(server.id)
            ),
        )
    except Exception as e:
        # Reset the cooldown on error
        clear_operation_cooldown(server.composite_key)
        logger.error(f"Failed to execute operation '{action}': {e}", exc_info=True)
        text = format_operation_result(action, server.get_display_name(), False, localize_error(e))
        await safe_edit_message(callback, text)


def _parse_confirm_action(callback_data: str, base_prefix: str) -> tuple[str | None, str | None]:
    """Extract the action and full prefix from confirmation callback_data.

    The stop, reboot, and shutdown operations are supported.

    Args:
        callback_data: Callback data of the form
            ``{base_prefix}{action}_...``.
        base_prefix: Base prefix ("server_confirm_" or "server_cancel_").

    Returns:
        A tuple of ``(action, prefix)``, or ``(None, None)`` for an unknown
        operation.
    """
    data = callback_data.removeprefix(base_prefix)
    for action in ("stop", "reboot", "shutdown"):
        if data.startswith(f"{action}_"):
            return action, f"{base_prefix}{action}_"
    return None, None


def _parse_alias_and_page(callback_data: str, prefix: str) -> tuple[str | None, int | None]:
    """Parse callback_data of the form ``{prefix}{alias}_{page}`` or ``{prefix}{page}``.

    An alias may contain underscores (e.g. hetzner_prod), so the last segment
    is treated as the page and everything before it as the alias.

    Args:
        callback_data: Callback data string.
        prefix: Prefix to strip.

    Returns:
        A tuple of ``(alias, page)``; page is None when the format is invalid.
    """
    suffix = callback_data.removeprefix(prefix)
    parts = suffix.rsplit("_", 1)  # Split from the right, at most once

    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    if len(parts) == 1 and parts[0].isdigit():
        return None, int(parts[0])
    return None, None


async def _render_servers_list(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    shared_state: DictProxy,
    provider_alias: str | None,
    page: int,
    answer_text: str,
) -> None:
    """Render the server list, optionally filtered by alias, into the message.

    Args:
        callback: Callback query that owns the message being edited.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.
        provider_alias: Alias to filter by, or None for all servers.
        page: Page number.
        answer_text: Text for the final callback.answer call.

    Returns:
        None.
    """
    all_servers = servers_repo.get_all()

    if provider_alias:
        servers = [s for s in all_servers if s.effective_alias == provider_alias]
    else:
        servers = all_servers

    apply_shared_status(servers, shared_state)

    text = format_servers_management_list(servers, page=page, provider_alias=provider_alias)
    await safe_edit_message(
        callback,
        text,
        get_servers_management_keyboard(servers, page=page, provider=provider_alias),
    )
    await callback.answer(answer_text)


@servers_router.message(MainMenuButton("menu.servers"))
async def cmd_servers(
    message: Message, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """
    Handle the servers reply-keyboard button.

    Sends the provider selection view through ``show_screen`` so it becomes
    this chat's single tracked live section screen. The user's tap message is
    not deleted.

    Args:
        message: Incoming message
        servers_repo: Servers repository
        shared_state: Shared server state

    Returns:
        None.
    """
    logger.info("Servers management command received")

    servers = servers_repo.get_all()
    apply_shared_status(servers, shared_state)

    text = format_provider_selection(servers)
    # Single live section screen: replaces this chat's previous one.
    await show_screen(message, text, get_provider_selection_keyboard(servers))


@servers_router.callback_query(F.data.startswith("provider_select_"))
@handle_telegram_errors
async def callback_provider_select(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Handle provider selection.

    Shows the list of servers for the selected provider (by alias).

    Args:
        callback: Callback query whose data contains the selected alias.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    # Parse the alias from callback_data: "provider_select_hetzner_prod" -> "hetzner_prod"
    # NOTE: do NOT answer the callback here - Telegram honors only the FIRST answer,
    # so an early answer would suppress the "no servers" alert below.
    provider_alias = callback.data.removeprefix("provider_select_")

    logger.info(f"Provider alias selected: {provider_alias}")

    # Filter servers by provider_alias (effective_alias accounts for legacy entries without an alias)
    all_servers = servers_repo.get_all()
    servers = [s for s in all_servers if s.effective_alias == provider_alias]

    if not servers:
        await callback.answer(
            _("srv.no_servers_for_provider", provider=provider_alias), show_alert=True
        )
        return

    apply_shared_status(servers, shared_state)

    text = format_servers_management_list(servers, page=0, provider_alias=provider_alias)
    await safe_edit_message(
        callback,
        text,
        get_servers_management_keyboard(servers, page=0, provider=provider_alias),
    )
    await callback.answer()


@servers_router.callback_query(F.data.startswith("servers_page_"))
@handle_telegram_errors
async def callback_servers_page(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Handle pagination of the management server list.

    Supports the callback_data formats:
    - servers_page_{page} - all servers
    - servers_page_{alias}_{page} - servers of a provider (alias may contain _)

    Args:
        callback: Callback query whose data contains the requested page.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    if callback.data == "servers_page_info":
        # This is the page-number button - ignore it
        await callback.answer()
        return

    provider_alias, page = _parse_alias_and_page(callback.data, "servers_page_")
    if page is None:
        await callback.answer(_("common.page_change_error"))
        return

    await _render_servers_list(callback, servers_repo, shared_state, provider_alias, page, "")


@servers_router.callback_query(F.data.startswith("servers_refresh_"))
@handle_telegram_errors
async def callback_servers_refresh(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Refresh the current management server-list page in place.

    Supports the callback_data formats:
    - servers_refresh_{page} - all servers
    - servers_refresh_{alias}_{page} - servers of a provider (alias may contain _)

    Args:
        callback: Callback query whose data contains the current page.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    provider_alias, page = _parse_alias_and_page(callback.data, "servers_refresh_")
    if page is None:
        # Invalid format - show the first page of all servers
        provider_alias, page = None, 0

    await _render_servers_list(
        callback, servers_repo, shared_state, provider_alias, page, _("common.refreshed")
    )


@servers_router.callback_query(F.data.startswith("server_control_"))
@handle_telegram_errors
async def callback_server_control(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    provider_manager: ProviderManager,
    shared_state: DictProxy,
) -> None:
    """Show details and power controls for a single server.

    Fetches current info from the corresponding provider and shows details
    and control buttons.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.
        stats_repo: Statistics repository.
        provider_manager: Cloud provider manager.
        shared_state: Shared worker state keyed by server composite key.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_control_")
    if not server:
        return

    # Show the loading indicator
    await callback.answer(_("srv.loading_data"))

    # Fetch current info from the provider
    power_status = await _fetch_power_status(provider_manager, server)

    # Get the current state from shared_state (use the server's composite_key)
    state = shared_state.get(server.composite_key, {})

    # Get 24-hour statistics and the last 5 ping results
    stats_24h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24)
    recent_errors = stats_repo.get_recent_errors(server.id, server.effective_alias, limit=5)

    text = format_server_control_details(server, power_status, state, stats_24h, recent_errors)
    supports_graceful = _server_supports_graceful(provider_manager, server)
    await safe_edit_message(
        callback,
        text,
        get_server_control_keyboard(server.composite_key, power_status, supports_graceful),
    )


@servers_router.callback_query(F.data.startswith("server_start_"))
@handle_telegram_errors
async def callback_server_start(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    provider_manager: ProviderManager,
) -> None:
    """Start a server without an additional confirmation step.

    Start is treated as a non-critical operation, but still uses the shared
    cooldown and provider-resolution path for power actions.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.
        provider_manager: Cloud provider manager.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_start_")
    if not server:
        return

    provider = await _acquire_cooldown_and_provider(
        callback, server, provider_manager
    )
    if not provider:
        return

    await _execute_power_action(
        callback, server, provider, "start", loading_text=_("srv.starting")
    )


@servers_router.callback_query(F.data.startswith("server_stop_"))
@handle_telegram_errors
async def callback_server_stop_request(
    callback: CallbackQuery, servers_repo: ServersRepository
) -> None:
    """Show the stop confirmation screen for a server.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_stop_")
    if not server:
        return

    text = format_confirmation_message("stop", server)
    await safe_edit_message(callback, text, get_confirmation_keyboard("stop", server.composite_key))

    await callback.answer()


@servers_router.callback_query(F.data.startswith("server_reboot_"))
@handle_telegram_errors
async def callback_server_reboot_request(
    callback: CallbackQuery, servers_repo: ServersRepository
) -> None:
    """Show the reboot confirmation screen for a server.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_reboot_")
    if not server:
        return

    text = format_confirmation_message("reboot", server)
    await safe_edit_message(
        callback, text, get_confirmation_keyboard("reboot", server.composite_key)
    )

    await callback.answer()


@servers_router.callback_query(F.data.startswith("server_shutdown_"))
@handle_telegram_errors
async def callback_server_shutdown_request(
    callback: CallbackQuery, servers_repo: ServersRepository
) -> None:
    """Show the graceful-shutdown confirmation screen for a server.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_shutdown_")
    if not server:
        return

    text = format_confirmation_message("shutdown", server)
    await safe_edit_message(
        callback, text, get_confirmation_keyboard("shutdown", server.composite_key)
    )

    await callback.answer()


@servers_router.callback_query(F.data.startswith("server_confirm_"))
@handle_telegram_errors
async def callback_server_confirm(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    provider_manager: ProviderManager,
) -> None:
    """Confirm and execute a stop, reboot, or graceful-shutdown operation.

    Args:
        callback: Callback query carrying the operation and server key.
        servers_repo: Server repository.
        provider_manager: Cloud provider manager.

    Returns:
        None.
    """
    # callback_data: server_confirm_{action}_{alias}:{server_id} or ..._#{hash}
    action, prefix = _parse_confirm_action(callback.data, "server_confirm_")
    if not action or not prefix:
        await callback.answer(_("common.unknown_operation"))
        return

    server = await _resolve_server(callback, servers_repo, prefix)
    if not server:
        return

    provider = await _acquire_cooldown_and_provider(
        callback, server, provider_manager
    )
    if not provider:
        return

    loading_texts = {
        "stop": _("srv.stopping"),
        "reboot": _("srv.rebooting"),
        "shutdown": _("srv.shutting_down"),
    }
    loading_text = loading_texts.get(action, _("srv.performing_operation"))
    await _execute_power_action(
        callback, server, provider, action, loading_text=loading_text
    )


@servers_router.callback_query(F.data.startswith("server_cancel_"))
@handle_telegram_errors
async def callback_server_cancel(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    provider_manager: ProviderManager,
) -> None:
    """Cancel a pending power-operation confirmation.

    Returns to the server control screen after acknowledging the cancellation.

    Args:
        callback: Callback query carrying the operation and server key.
        servers_repo: Server repository.
        provider_manager: Cloud provider manager.

    Returns:
        None.
    """
    # callback_data: server_cancel_{action}_{alias}:{server_id} or ..._#{hash}
    _action, prefix = _parse_confirm_action(callback.data, "server_cancel_")
    if not prefix:
        await callback.answer(_("common.unknown_operation"))
        return

    server = await _resolve_server(callback, servers_repo, prefix)
    if not server:
        return

    await callback.answer(_("srv.operation_cancelled"))

    # Fetch info from the provider API
    power_status = await _fetch_power_status(provider_manager, server)

    text = format_server_control_details(server, power_status)
    supports_graceful = _server_supports_graceful(provider_manager, server)
    await safe_edit_message(
        callback,
        text,
        get_server_control_keyboard(server.composite_key, power_status, supports_graceful),
    )


@servers_router.callback_query(F.data.startswith("server_refresh_"))
@handle_telegram_errors
async def callback_server_refresh(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    provider_manager: ProviderManager,
    shared_state: DictProxy,
) -> None:
    """Refresh one server's provider data and monitoring statistics.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.
        stats_repo: Statistics repository.
        provider_manager: Cloud provider manager.
        shared_state: Shared worker state keyed by server composite key.

    Returns:
        None.
    """
    server = await _resolve_server(callback, servers_repo, "server_refresh_")
    if not server:
        return

    # Show the loading indicator
    await callback.answer(_("srv.refreshing_data"))

    # Fetch current info from the provider API
    power_status = await _fetch_power_status(provider_manager, server)

    # Get the current state from shared_state (use the server's composite_key)
    state = shared_state.get(server.composite_key, {})

    # Get 24-hour statistics and the last 5 ping results
    stats_24h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24)
    recent_errors = stats_repo.get_recent_errors(server.id, server.effective_alias, limit=5)

    text = format_server_control_details(server, power_status, state, stats_24h, recent_errors)
    supports_graceful = _server_supports_graceful(provider_manager, server)
    await safe_edit_message(
        callback,
        text,
        get_server_control_keyboard(server.composite_key, power_status, supports_graceful),
    )


@servers_router.callback_query(F.data == "servers_back")
@handle_telegram_errors
async def callback_servers_back(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Return from the management server list to provider selection.

    Args:
        callback: Callback query from the back button.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    servers = servers_repo.get_all()
    apply_shared_status(servers, shared_state)

    text = format_provider_selection(servers)
    await safe_edit_message(callback, text, get_provider_selection_keyboard(servers))

    await callback.answer()
