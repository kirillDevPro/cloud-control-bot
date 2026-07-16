"""Router for per-server service-check configuration (TCP/HTTP/SSL) from chat.

Reached from the "Checks (N)" button on a server's control screen. Lets an admin list,
add (via a small FSM wizard), toggle, and delete checks. All persistence goes through the
    service-checks store; additions and toggles mark a check dirty so the background task picks
    them up promptly, while deleted checks are pruned from task state on a later cycle.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...background_tasks.service_checks import mark_check_dirty
from ...models.service_check import CheckDefinition, CheckType
from ...providers.manager import ProviderManager
from ...storage import ServersRepository, SqliteStatisticsRepository
from ...storage.service_checks_store import add_check, delete_check, get_checks, update_check
from ..filters.menu import MAIN_MENU_LABELS
from ..formatters import format_check_detail, format_checks_list
from ..formatters.servers import format_server_control_details
from ..i18n import _
from ..keyboards import (
    get_check_delete_confirm_keyboard,
    get_check_detail_keyboard,
    get_check_input_cancel_keyboard,
    get_check_type_keyboard,
    get_checks_list_keyboard,
    get_main_menu_keyboard,
    get_server_control_keyboard,
)
from ..utils import decode_callback_data, handle_telegram_errors, safe_edit_message, show_screen
from ..utils.rich import blocks
from ..utils.server_lookup import resolve_server
from .servers import _fetch_power_status, _server_supports_graceful

logger = logging.getLogger(__name__)

checks_router = Router(name="checks")

# A skip token an admin can send to leave an optional wizard field unset.
_SKIP_TOKEN = "-"


class CheckForm(StatesGroup):
    """FSM states for the add-check wizard.

    The active type is stored in FSM data; the port state is shared between TCP (required)
    and SSL (optional, default 443), branching on that stored type.
    """

    waiting_for_port = State()
    waiting_for_url = State()
    waiting_for_keyword = State()
    waiting_for_expected_status = State()
    waiting_for_warn_days = State()


def _parse_check_ref(callback_data: str | None, prefix: str) -> tuple[str | None, str | None]:
    """Decode a ``{prefix}{server_key}|{check_id}`` callback into its parts.

    A SEPARATE parser from the power-operation one: it must never route a check action into
    the paid power-operation dispatch.

    Args:
        callback_data: The callback data string.
        prefix: The prefix to strip before decoding.

    Returns:
        tuple[str | None, str | None]: (server_key, check_id), or (None, None) on error.
    """
    decoded = decode_callback_data(callback_data, prefix)
    if not decoded or "|" not in decoded:
        return None, None
    server_key, check_id = decoded.split("|", 1)
    if ":" not in server_key:
        return None, None
    return server_key, check_id


def _find_check(server_key: str, check_id: str) -> CheckDefinition | None:
    """Return a server's check by id, or None when it no longer exists.

    Args:
        server_key: The server's composite key.
        check_id: The check to find.

    Returns:
        CheckDefinition | None: The check, or None.
    """
    for check in get_checks(server_key):
        if check.check_id == check_id:
            return check
    return None


def _parse_bounded_int(raw: str, low: int, high: int) -> int | None:
    """Parse an integer within [low, high] inclusive, or None if unparseable/out of range.

    Args:
        raw: The user-typed value (already stripped).
        low: Inclusive lower bound.
        high: Inclusive upper bound.

    Returns:
        int | None: The parsed in-range value, or None when invalid.
    """
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if low <= value <= high else None


async def _show_checks_list(
    callback: CallbackQuery, servers_repo: ServersRepository, server_key: str
) -> None:
    """Render the checks-list screen for a server (edits the current message in place).

    Args:
        callback: The callback whose message is edited.
        servers_repo: Server repository.
        server_key: The server's composite key.

    Returns:
        None.
    """
    server = servers_repo.get_by_composite_key(server_key)
    if not server:
        await callback.answer(_("common.server_not_found"))
        return
    checks = get_checks(server_key)
    await safe_edit_message(
        callback, format_checks_list(server, checks), get_checks_list_keyboard(server_key, checks)
    )


@checks_router.callback_query(F.data.startswith("chk_list_"))
@handle_telegram_errors
async def callback_checks_list(
    callback: CallbackQuery, servers_repo: ServersRepository, state: FSMContext
) -> None:
    """Open a server's service-check list.

    Also the add-check wizard's Cancel target, so it clears any in-progress FSM state —
    otherwise a mid-wizard Cancel would leave the modal open and swallow the admin's next
    free-text message as a stale wizard input.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        state: FSM context (cleared here in case a wizard was mid-flight).

    Returns:
        None.
    """
    await state.clear()
    server = await resolve_server(callback, servers_repo, "chk_list_")
    if not server:
        return
    await _show_checks_list(callback, servers_repo, server.composite_key)
    await callback.answer()


@checks_router.callback_query(F.data.startswith("chk_back_"))
@handle_telegram_errors
async def callback_checks_back(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    provider_manager: ProviderManager,
) -> None:
    """Return from the checks list to the server control screen.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        provider_manager: Provider manager (for the live power status).

    Returns:
        None.
    """
    server = await resolve_server(callback, servers_repo, "chk_back_")
    if not server:
        return
    power_status = await _fetch_power_status(provider_manager, server)
    supports_graceful = _server_supports_graceful(provider_manager, server)
    await safe_edit_message(
        callback,
        format_server_control_details(server, power_status),
        get_server_control_keyboard(
            server.composite_key,
            power_status,
            supports_graceful,
            check_count=len(get_checks(server.composite_key)),
        ),
    )
    await callback.answer()


@checks_router.callback_query(F.data.startswith("chk_add_"))
@handle_telegram_errors
async def callback_check_add(callback: CallbackQuery, servers_repo: ServersRepository) -> None:
    """Show the check-type choice (TCP / HTTP / SSL).

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.

    Returns:
        None.
    """
    server = await resolve_server(callback, servers_repo, "chk_add_")
    if not server:
        return
    await safe_edit_message(
        callback, _("checks.prompt.choose_type"), get_check_type_keyboard(server.composite_key)
    )
    await callback.answer()


async def _start_wizard(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    state: FSMContext,
    prefix: str,
    check_type: CheckType,
    first_state: State,
    prompt_key: str,
) -> None:
    """Begin the add-check wizard for a type: set state + data and show the first prompt.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        state: FSM context.
        prefix: The callback prefix to strip.
        check_type: The type of check being added.
        first_state: The FSM state to enter.
        prompt_key: The i18n key for the first prompt.

    Returns:
        None.
    """
    server = await resolve_server(callback, servers_repo, prefix)
    if not server:
        return
    await state.set_state(first_state)
    await state.update_data(server_key=server.composite_key, check_type=check_type.value)
    await safe_edit_message(
        callback, _(prompt_key), get_check_input_cancel_keyboard(server.composite_key)
    )
    await callback.answer()


@checks_router.callback_query(F.data.startswith("chk_ntcp_"))
@handle_telegram_errors
async def callback_new_tcp(
    callback: CallbackQuery, servers_repo: ServersRepository, state: FSMContext
) -> None:
    """Start the TCP add-check wizard by asking for a port.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        state: FSM context populated by the wizard.

    Returns:
        None.
    """
    await _start_wizard(
        callback, servers_repo, state, "chk_ntcp_", CheckType.TCP,
        CheckForm.waiting_for_port, "checks.prompt.port",
    )


@checks_router.callback_query(F.data.startswith("chk_nhttp_"))
@handle_telegram_errors
async def callback_new_http(
    callback: CallbackQuery, servers_repo: ServersRepository, state: FSMContext
) -> None:
    """Start the HTTP add-check wizard by asking for a URL.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        state: FSM context populated by the wizard.

    Returns:
        None.
    """
    await _start_wizard(
        callback, servers_repo, state, "chk_nhttp_", CheckType.HTTP,
        CheckForm.waiting_for_url, "checks.prompt.url",
    )


@checks_router.callback_query(F.data.startswith("chk_nssl_"))
@handle_telegram_errors
async def callback_new_ssl(
    callback: CallbackQuery, servers_repo: ServersRepository, state: FSMContext
) -> None:
    """Start the SSL add-check wizard by asking for a port, defaulting to 443.

    Args:
        callback: Callback query carrying the encoded server key.
        servers_repo: Server repository.
        state: FSM context populated by the wizard.

    Returns:
        None.
    """
    await _start_wizard(
        callback, servers_repo, state, "chk_nssl_", CheckType.SSL,
        CheckForm.waiting_for_port, "checks.prompt.ssl_port",
    )


@checks_router.callback_query(F.data.startswith("chk_show_"))
@handle_telegram_errors
async def callback_check_show(callback: CallbackQuery, servers_repo: ServersRepository,
                              stats_repo: SqliteStatisticsRepository) -> None:
    """Show a single check's detail screen.

    Args:
        callback: Callback query carrying the encoded server_key|check_id.
        servers_repo: Server repository.
        stats_repo: Statistics repository (for the check's stats + SSL state).

    Returns:
        None.
    """
    server_key, check_id = _parse_check_ref(callback.data, "chk_show_")
    if not server_key or not check_id:
        await callback.answer(_("common.invalid_data_format"))
        return
    if await _render_detail(callback, servers_repo, stats_repo, server_key, check_id):
        await callback.answer()


async def _render_detail(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
    server_key: str,
    check_id: str,
) -> bool:
    """Render a check's detail screen in place.

    Args:
        callback: Callback whose message is edited.
        servers_repo: Server repository.
        stats_repo: Statistics repository (stats + SSL state).
        server_key: The server's composite key.
        check_id: The check to render.

    Returns:
        bool: True if rendered; False if the server/check was gone (caller already answered).
    """
    server = servers_repo.get_by_composite_key(server_key)
    check = _find_check(server_key, check_id)
    if not server or not check:
        await callback.answer(_("checks.not_found"))
        return False
    all_stats = await asyncio.to_thread(
        stats_repo.get_check_statistics, server.id, server.effective_alias, 24
    )
    stats = all_stats.get(check_id)
    ssl_state = (
        await asyncio.to_thread(
            stats_repo.get_ssl_state, server.id, server.effective_alias, check_id
        )
        if check.type == CheckType.SSL
        else None
    )
    await safe_edit_message(
        callback,
        format_check_detail(server, check, stats, ssl_state),
        get_check_detail_keyboard(server_key, check_id, check.enabled),
    )
    return True


@checks_router.callback_query(F.data.startswith("chk_tog_"))
@handle_telegram_errors
async def callback_check_toggle(callback: CallbackQuery, servers_repo: ServersRepository,
                                stats_repo: SqliteStatisticsRepository) -> None:
    """Toggle a check's enabled flag and re-render its detail.

    Args:
        callback: Callback query carrying the encoded server_key|check_id.
        servers_repo: Server repository.
        stats_repo: Statistics repository (to re-render the detail).

    Returns:
        None.
    """
    server_key, check_id = _parse_check_ref(callback.data, "chk_tog_")
    if not server_key or not check_id:
        await callback.answer(_("common.invalid_data_format"))
        return
    check = _find_check(server_key, check_id)
    if not check:
        await callback.answer(_("checks.not_found"))
        return
    persisted = await asyncio.to_thread(
        update_check, server_key, check_id, enabled=not check.enabled
    )
    # A re-enabled check should run and be re-evaluated promptly.
    mark_check_dirty(server_key, check_id)
    await _render_detail(callback, servers_repo, stats_repo, server_key, check_id)
    if persisted:
        await callback.answer()
    else:
        await callback.answer(_("checks.not_saved"), show_alert=True)


@checks_router.callback_query(F.data.startswith("chk_delyes_"))
@handle_telegram_errors
async def callback_check_delete_confirmed(
    callback: CallbackQuery,
    servers_repo: ServersRepository,
    stats_repo: SqliteStatisticsRepository,
) -> None:
    """Delete a check (config + stored state) and return to the list.

    Args:
        callback: Callback query carrying the encoded server_key|check_id.
        servers_repo: Server repository.
        stats_repo: Statistics repository (to drop the check's stored state).

    Returns:
        None.
    """
    server_key, check_id = _parse_check_ref(callback.data, "chk_delyes_")
    if not server_key or not check_id:
        await callback.answer(_("common.invalid_data_format"))
        return
    server = servers_repo.get_by_composite_key(server_key)
    persisted = await asyncio.to_thread(delete_check, server_key, check_id)
    if server and persisted:
        # Drop the check's stored history/errors/SSL state ONLY after the config delete
        # durably persisted — otherwise a failed config write would restore the check on
        # restart with its history already erased. The task's in-memory alert and schedule
        # state self-heals next cycle (it prunes keys not in the live config).
        await _delete_check_state(stats_repo, server.id, server.effective_alias, check_id)
    await _show_checks_list(callback, servers_repo, server_key)
    await callback.answer(_("checks.deleted") if persisted else _("checks.not_saved"))


async def _delete_check_state(
    stats_repo: SqliteStatisticsRepository, server_id: str, provider_alias: str, check_id: str
) -> None:
    """Delete a check's stored DB state off the event loop.

    Args:
        stats_repo: Statistics repository.
        server_id: Server ID.
        provider_alias: Provider alias.
        check_id: Check ID.

    Returns:
        None.
    """

    await asyncio.to_thread(stats_repo.delete_check_state, server_id, provider_alias, check_id)


@checks_router.callback_query(F.data.startswith("chk_del_"))
@handle_telegram_errors
async def callback_check_delete(callback: CallbackQuery) -> None:
    """Show the delete-confirmation for a check.

    Registered AFTER chk_delyes_ is irrelevant (prefixes are disjoint), but note chk_del_ is
    NOT a string-prefix of chk_delyes_ (position 7 differs), so routing is unambiguous.

    Args:
        callback: Callback query carrying the encoded server_key|check_id.

    Returns:
        None.
    """
    server_key, check_id = _parse_check_ref(callback.data, "chk_del_")
    if not server_key or not check_id:
        await callback.answer(_("common.invalid_data_format"))
        return
    await safe_edit_message(
        callback, _("checks.delete_confirm"), get_check_delete_confirm_keyboard(server_key, check_id)
    )
    await callback.answer()


# --- FSM wizard message handlers ---


async def _menu_tap(message: Message, state: FSMContext) -> bool:
    """Handle a main-menu tap during a wizard input state.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        bool: True if the message was a menu tap (handled: state cleared, menu shown).
    """
    if message.text in MAIN_MENU_LABELS:
        await state.clear()
        await show_screen(message, _("checks.cancelled"), get_main_menu_keyboard())
        return True
    return False


async def _finish(message: Message, state: FSMContext, server_key: str, check: CheckDefinition,
                  persisted: bool) -> None:
    """Finish an add attempt: mark the check dirty and show the updated list.

    Args:
        message: The message that completed the wizard.
        state: FSM context (cleared here).
        server_key: The server's composite key.
        check: The fully-built check to add.
        persisted: Whether the earlier ``add_check`` call durably persisted.

    Returns:
        None.
    """
    mark_check_dirty(server_key, check.check_id)
    await state.clear()
    checks = get_checks(server_key)
    added = _("checks.added") if persisted else _("checks.not_saved_notice")
    body = blocks(added, _("checks.list.prompt") if checks else _("checks.list.empty"))
    await show_screen(message, body, get_checks_list_keyboard(server_key, checks))


@checks_router.message(CheckForm.waiting_for_port)
async def on_port_input(message: Message, state: FSMContext) -> None:
    """Handle the port input for a TCP (required) or SSL (optional, default 443) check.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        None.
    """
    if await _menu_tap(message, state):
        return
    data = await state.get_data()
    server_key = data["server_key"]
    check_type = CheckType(data["check_type"])
    raw = (message.text or "").strip()

    if check_type == CheckType.SSL and raw == _SKIP_TOKEN:
        port: int | None = 443
    else:
        port = _parse_bounded_int(raw, 1, 65535)
        if port is None:
            await show_screen(message, _("checks.invalid.port"),
                              get_check_input_cancel_keyboard(server_key))
            return

    if check_type == CheckType.TCP:
        check = CheckDefinition(type=CheckType.TCP, port=port)
        persisted = await asyncio.to_thread(add_check, server_key, check)
        await _finish(message, state, server_key, check, persisted)
        return

    # SSL: keep the port, ask for the optional warn-days override next.
    await state.update_data(port=port)
    await state.set_state(CheckForm.waiting_for_warn_days)
    await show_screen(message, _("checks.prompt.warn_days"),
                      get_check_input_cancel_keyboard(server_key))


@checks_router.message(CheckForm.waiting_for_url)
async def on_url_input(message: Message, state: FSMContext) -> None:
    """Handle the URL input for an HTTP check.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        None.
    """
    if await _menu_tap(message, state):
        return
    data = await state.get_data()
    server_key = data["server_key"]
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")) or len(url) > 500:
        await show_screen(message, _("checks.invalid.url"),
                          get_check_input_cancel_keyboard(server_key))
        return
    await state.update_data(url=url)
    await state.set_state(CheckForm.waiting_for_keyword)
    await show_screen(message, _("checks.prompt.keyword"),
                      get_check_input_cancel_keyboard(server_key))


@checks_router.message(CheckForm.waiting_for_keyword)
async def on_keyword_input(message: Message, state: FSMContext) -> None:
    """Handle the optional response-body keyword for an HTTP check.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        None.
    """
    if await _menu_tap(message, state):
        return
    data = await state.get_data()
    server_key = data["server_key"]
    raw = (message.text or "").strip()
    keyword = None if raw == _SKIP_TOKEN or not raw else raw
    if keyword is not None and len(keyword) > 200:
        await show_screen(message, _("checks.invalid.keyword"),
                          get_check_input_cancel_keyboard(server_key))
        return
    await state.update_data(keyword=keyword)
    await state.set_state(CheckForm.waiting_for_expected_status)
    await show_screen(message, _("checks.prompt.status"),
                      get_check_input_cancel_keyboard(server_key))


@checks_router.message(CheckForm.waiting_for_expected_status)
async def on_status_input(message: Message, state: FSMContext) -> None:
    """Handle the optional expected HTTP status (default 200), then save the HTTP check.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        None.
    """
    if await _menu_tap(message, state):
        return
    data = await state.get_data()
    server_key = data["server_key"]
    raw = (message.text or "").strip()
    if raw == _SKIP_TOKEN or not raw:
        expected_status: int | None = None
    else:
        expected_status = _parse_bounded_int(raw, 100, 599)
        if expected_status is None:
            await show_screen(message, _("checks.invalid.status"),
                              get_check_input_cancel_keyboard(server_key))
            return
    check = CheckDefinition(
        type=CheckType.HTTP,
        url=data["url"],
        keyword=data.get("keyword"),
        expected_status=expected_status,
    )
    persisted = await asyncio.to_thread(add_check, server_key, check)
    await _finish(message, state, server_key, check, persisted)


@checks_router.message(CheckForm.waiting_for_warn_days)
async def on_warn_days_input(message: Message, state: FSMContext) -> None:
    """Handle the optional SSL warn-days override (default: the global setting), then save.

    Args:
        message: The incoming message.
        state: FSM context.

    Returns:
        None.
    """
    if await _menu_tap(message, state):
        return
    data = await state.get_data()
    server_key = data["server_key"]
    raw = (message.text or "").strip()
    if raw == _SKIP_TOKEN or not raw:
        warn_days: int | None = None
    else:
        warn_days = _parse_bounded_int(raw, 1, 365)
        if warn_days is None:
            await show_screen(message, _("checks.invalid.warn_days"),
                              get_check_input_cancel_keyboard(server_key))
            return
    check = CheckDefinition(type=CheckType.SSL, port=data.get("port", 443), warn_days=warn_days)
    persisted = await asyncio.to_thread(add_check, server_key, check)
    await _finish(message, state, server_key, check, persisted)
