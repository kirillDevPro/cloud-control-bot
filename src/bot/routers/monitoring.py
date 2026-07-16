"""Monitoring router for dashboard, server list, details, and statistics views."""

import logging
from multiprocessing.managers import DictProxy

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from ...storage import ServersRepository, SqliteStatisticsRepository
from ...storage.balance import BalanceRepository
from ...providers.manager import ProviderManager
from ..filters import MainMenuButton
from ..i18n import _
from ..keyboards import (
    get_monitoring_keyboard,
    get_server_details_keyboard,
    get_server_stats_keyboard,
)
from ..utils import (
    safe_edit_message,
    handle_telegram_errors,
    apply_shared_status,
    show_screen,
)
from ..utils.server_lookup import resolve_server
from ..formatters import (
    format_monitoring_dashboard,
    format_servers_list,
    format_server_details,
    format_statistics,
)

logger = logging.getLogger(__name__)

# Create the router for monitoring
monitoring_router = Router(name="monitoring")



@monitoring_router.message(MainMenuButton("menu.monitoring"))
async def cmd_monitoring(
    message: Message,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    shared_state: DictProxy,
    balance_repo: BalanceRepository,
    provider_manager: ProviderManager,
) -> None:
    """
    Handle the monitoring reply-keyboard button.

    Sends a dashboard with overall monitoring statistics through
    ``show_screen`` so it becomes this chat's single tracked live section
    screen. The user's tap message is not deleted.

    Args:
        message: Incoming message
        servers_repo: Server repository
        stats_repo: Statistics repository
        shared_state: Shared server state
        balance_repo: Balance repository
        provider_manager: Provider manager

    Returns:
        None.
    """
    # Fetch all servers
    servers = servers_repo.get_all()

    # Refresh server status from shared_state
    apply_shared_status(servers, shared_state)

    # Format the dashboard
    text = format_monitoring_dashboard(
        servers, shared_state, stats_repo, balance_repo, provider_manager
    )

    # Send as the single live section screen (deletes this chat's previous one).
    # No inline keyboard: the dashboard is a terminal view.
    await show_screen(message, text)


@monitoring_router.callback_query(F.data.startswith("monitor_page_"))
@handle_telegram_errors
async def callback_monitor_page(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Handle pagination of the monitoring server list.

    Args:
        callback: Callback query whose data contains the requested page.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    # Extract the page number from callback_data
    if callback.data == "monitor_page_info":
        # This is the page-number button - ignore it
        await callback.answer()
        return

    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer(_("common.page_change_error"))
        return

    # Fetch all servers
    servers = servers_repo.get_all()

    # Refresh server status
    apply_shared_status(servers, shared_state)

    # Format the message
    text = format_servers_list(servers, shared_state, page=page)

    # Safely update the message
    await safe_edit_message(callback, text, get_monitoring_keyboard(servers, page=page))

    await callback.answer()


@monitoring_router.callback_query(F.data.startswith("monitor_refresh_"))
@handle_telegram_errors
async def callback_monitor_refresh(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Refresh the current monitoring server-list page in place.

    Args:
        callback: Callback query whose data contains the current page.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    # Extract the page number
    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        page = 0

    # Fetch all servers
    servers = servers_repo.get_all()

    # Refresh server status
    apply_shared_status(servers, shared_state)

    # Format the message
    text = format_servers_list(servers, shared_state, page=page)

    # Safely update the message
    await safe_edit_message(callback, text, get_monitoring_keyboard(servers, page=page))

    await callback.answer(_("common.refreshed"))


@monitoring_router.callback_query(F.data.startswith("monitor_details_"))
@handle_telegram_errors
async def callback_monitor_details(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    shared_state: DictProxy,
) -> None:
    """Show monitoring details for a single server in the current screen.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.
        stats_repo: Statistics repository.
        shared_state: Shared worker state keyed by server composite key.

    Returns:
        None.
    """
    server = await resolve_server(callback, servers_repo, "monitor_details_")
    if not server:
        return

    # Get the current state (keyed by the server's composite_key)
    state = shared_state.get(server.composite_key, {})

    # Get statistics for the last 24 hours
    stats_24h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24)

    # Get the last 5 errors (failed/timeout pings)
    recent_errors = stats_repo.get_recent_errors(server.id, server.effective_alias, limit=5)

    # Format the message
    text = format_server_details(server, state, stats_24h, recent_errors)

    # Safely update the message (keyed by the server's composite_key)
    await safe_edit_message(callback, text, get_server_details_keyboard(server.composite_key))

    await callback.answer()


@monitoring_router.callback_query(F.data.startswith("monitor_stats_"))
@handle_telegram_errors
async def callback_monitor_stats(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
) -> None:
    """Show full statistics for a single server in the current screen.

    Args:
        callback: Callback query carrying an encoded server composite key.
        servers_repo: Server repository.
        stats_repo: Statistics repository.

    Returns:
        None.
    """
    server = await resolve_server(callback, servers_repo, "monitor_stats_")
    if not server:
        return

    # Get statistics for different time windows
    stats_1h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=1)
    stats_24h = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24)
    stats_7d = stats_repo.get_recent_statistics(server.id, server.effective_alias, hours=24 * 7)

    # Format the message
    text = format_statistics(server, stats_1h, stats_24h, stats_7d)

    # Safely update the message (keyed by the server's composite_key)
    await safe_edit_message(callback, text, get_server_stats_keyboard(server.composite_key))

    await callback.answer()


@monitoring_router.callback_query(F.data == "monitor_back")
@handle_telegram_errors
async def callback_monitor_back(
    callback: CallbackQuery, servers_repo: ServersRepository, shared_state: DictProxy
) -> None:
    """Return from monitoring details or statistics to the server list.

    Args:
        callback: Callback query from the back button.
        servers_repo: Server repository.
        shared_state: Shared worker state used to refresh server status.

    Returns:
        None.
    """
    # Fetch all servers
    servers = servers_repo.get_all()

    # Refresh server status
    apply_shared_status(servers, shared_state)

    # Format the message
    text = format_servers_list(servers, shared_state, page=0)

    # Safely update the message
    await safe_edit_message(callback, text, get_monitoring_keyboard(servers, page=0))

    await callback.answer()
