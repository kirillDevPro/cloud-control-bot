"""English translation catalog (one module per locale).

Flat ``{key: value}`` mappings. Keys MUST stay in sync with the other
locales — src.bot.i18n.catalog assembles them and the i18n tests enforce
that every locale defines the same keys."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # menu
    'menu.monitoring': '📊 Monitoring',
    'menu.servers': '🖥️ Servers',
    'menu.balance': '💰 Balance',
    'menu.settings': '⚙️ Settings',
    'menu.placeholder': 'Choose an action...',
    # start
    'start.welcome': (
        '<b>🎉 Welcome to the server monitoring system!</b>\n'
        '\n'
        'This bot helps you track the status of your servers and manage them via Telegram.\n'
        '\n'
        '<b>Available features:</b>\n'
        '📊 <b>Monitoring</b> — view the status of all servers\n'
        '🖥️ <b>Servers</b> — manage servers (add, remove)\n'
        '💰 <b>Balance</b> — provider balance information\n'
        '⚙️ <b>Settings</b> — language and monitoring options\n'
        '\n'
        'Use the menu buttons below to navigate 👇'
    ),
    # common
    'common.back': '◀️ Back',
    'common.refresh': '🔄 Refresh',
    'common.refreshed': '✅ Refreshed',
    'common.no_data': 'No data',
    'common.invalid_data_format': '❌ Invalid data format',
    'common.server_not_found': '❌ Server not found',
    'common.page_change_error': '❌ Failed to switch page',
    'common.unknown_operation': '❌ Unknown operation',
    # kb
    'kb.statistics': '📊 Statistics',
    'kb.manage': '⚙️ Manage',
    'kb.back_to_providers': '◀️ To providers',
    'kb.restart': '🔄 Restart',
    'kb.stop': '⏹️ Stop',
    'kb.start': '▶️ Start',
    'kb.shutdown_acpi': '🌙 Shut down (ACPI)',
    'kb.confirm': '✅ Confirm',
    'kb.cancel': '❌ Cancel',
    'kb.history': '📊 History',
    'kb.period_7': '7 days',
    'kb.period_30': '30 days',
    # mon
    'mon.empty': (
        '📊 <b>Server monitoring</b>\n'
        '\n'
        'The server list is empty.\n'
        'Add servers to start monitoring.'
    ),
    'mon.dashboard_title': '📊 <b>Overall server monitoring</b>',
    'mon.list_title': '📊 <b>Server monitoring</b>',
    'mon.section_servers': '━━━ <b>Servers</b> ━━━',
    'mon.total_servers': '<b>Total servers:</b> {count}',
    'mon.online': '🟢 Online: {count}',
    'mon.offline': '🔴 Offline: {count}',
    'mon.unknown': '❓ Unknown: {count}',
    'mon.status_inline': '🟢 Online: {online} | 🔴 Offline: {offline} | ❓ Unknown: {unknown}',
    'mon.section_finance': '━━━ <b>Finances</b> ({count} prov.) ━━━',
    'mon.finance_balance': '💰 Balance: ${amount:,.2f}',
    'mon.finance_expenses': '📉 Expenses/mo: ${amount:,.2f}',
    'mon.section_stats_24h': '━━━ <b>Statistics (24 hours)</b> ━━━',
    'mon.total_pings': '<b>Total pings:</b> {value}',
    'mon.successful': '<b>Successful:</b> {value} 🟢',
    'mon.errors': '<b>Errors:</b> {value} 🔴',
    'mon.timeout': '<b>Timeout:</b> {value} ⏱️',
    'mon.avg_uptime': '<b>Average uptime:</b> {value:.2f}%',
    'mon.no_ping_data': 'No ping data',
    'mon.section_by_provider': '━━━ <b>By provider</b> ━━━',
    'mon.choose_server': 'Choose a server to view details 👇',
    # status
    'status.online': 'ONLINE',
    'status.offline': 'OFFLINE',
    'status.unknown': 'UNKNOWN',
    # power
    'power.on': 'ON',
    'power.off': 'OFF',
    # details
    'details.status_label': '<b>Status:</b>',
    'details.provider_label': '<b>Provider:</b>',
    'details.ip_label': '<b>IP:</b>',
    'details.region_label': '<b>Region:</b>',
    'details.plan_label': '<b>Plan:</b>',
    'details.os_label': '<b>OS:</b>',
    'details.resources_label': '<b>Resources:</b>',
    'details.disk_suffix': 'GB Disk',
    'details.last_ping_label': '<b>Last ping:</b>',
    'details.response_time_label': '<b>Response time:</b>',
    'details.monitoring_label': '<b>Monitoring:</b>',
    'details.monitoring_on': 'Enabled',
    'details.monitoring_off': 'Disabled',
    'details.stats_24h_header': '📊 <b>Statistics (24 hours)</b>',
    'details.recent_problems': '🔴 <b>Recent problems:</b>',
    # time
    'time.just_now': 'just now',
    'time.min_ago': '{n} min ago',
    'time.hours_ago': '{n} h ago',
    'time.na': 'n/a',
    # stats
    'stats.title': '📊 <b>Statistics: {name}</b>',
    'stats.section_1h': '━━━ <b>Last 1 hour</b> ━━━',
    'stats.section_24h': '━━━ <b>Last 24 hours</b> ━━━',
    'stats.section_7d': '━━━ <b>Last 7 days</b> ━━━',
    # srv
    'srv.manage_title': '🖥️ <b>Server management</b>',
    'srv.empty': (
        '🖥️ <b>Server management</b>\n'
        '\n'
        'The server list is empty.\n'
        'Add servers to manage them.'
    ),
    'srv.choose_provider': 'Choose a provider to view servers 👇',
    'srv.servers_provider_title': '🖥️ <b>Servers • {provider}</b>',
    'srv.choose_server': 'Choose a server to manage 👇',
    'srv.confirm_stop_title': '⚠️ <b>Confirm stop</b>',
    'srv.confirm_stop_q': 'Do you really want to stop the server:',
    'srv.confirm_stop_warn': (
        '⚠️ <b>Warning:</b> The server will be unavailable until the next start.\n'
        'All running processes will be stopped.'
    ),
    'srv.confirm_shutdown_title': '🌙 <b>Confirm shutdown (ACPI)</b>',
    'srv.confirm_shutdown_q': 'Do you really want to gracefully shut down the server:',
    'srv.confirm_shutdown_warn': (
        'ℹ️ <b>Graceful shutdown:</b> The OS will receive a signal to shut down cleanly.\n'
        'The server will be unavailable until the next start.'
    ),
    'srv.confirm_reboot_title': '⚠️ <b>Confirm reboot</b>',
    'srv.confirm_reboot_q': 'Do you really want to reboot the server:',
    'srv.confirm_reboot_warn': (
        '⚠️ <b>Warning:</b> The server will be unavailable during the reboot (1-2 minutes).\n'
        'All active connections will be dropped.'
    ),
    'srv.confirm_generic_title': '⚠️ <b>Confirm operation</b>',
    'srv.confirm_generic_server': 'Server: <b>{name}</b>',
    'srv.confirm_generic_action': 'Operation: {action}',
    'srv.op_success_title': '✅ <b>Operation completed</b>',
    'srv.op_success_body': 'Server <b>{name}</b> has been {action}.',
    'srv.op_success_hint': (
        'ℹ️ <i>Changes take effect in 30-60 seconds.\n'
        "Use the 'Refresh' button to check.</i>"
    ),
    'srv.op_error_title': '❌ <b>{action} failed</b>',
    'srv.op_error_body': 'The operation for server <b>{name}</b> could not be completed.',
    'srv.op_error_details': '<b>Details:</b> {error}',
    'srv.op_error_retry': 'Try again later or contact the administrator.',
    # provider error details (localized exception text; full technical detail stays in logs)
    'error.invalid_token': 'Invalid {provider} API token — check the credentials in your .env file.',
    'error.permission': 'Insufficient permissions for the operation: {operation}.',
    'error.not_found': '{resource_type} with ID «{resource_id}» not found.',
    'error.rate_limit': '{provider} API rate limit exceeded — please try again shortly.',
    'error.server_side': '{provider} API error on the provider side — a temporary issue, try again later.',
    'error.conflict': 'Cannot perform «{operation}»: the server is in state «{state}».',
    'error.locked': 'Server {resource_id} is busy — another operation is in progress.',
    'error.provider_api': 'Error communicating with the {provider} API — a temporary problem, please try again later.',
    # action
    'action.start.done': 'started',
    'action.stop.done': 'stopped',
    'action.reboot.done': 'rebooted',
    'action.shutdown.done': 'shut down',
    'action.generic.done': 'processed',
    'action.start.err': 'Start',
    'action.stop.err': 'Stop',
    'action.reboot.err': 'Reboot',
    'action.shutdown.err': 'Shutdown',
    'action.generic.err': 'Operation',
    # srv
    'srv.provider_unavailable': '❌ Provider {provider} is unavailable',
    'srv.no_servers_for_provider': '❌ No servers found for {provider}',
    'srv.loading_data': '⏳ Fetching data...',
    'srv.starting': '⏳ Starting the server...',
    'srv.stopping': '⏳ Stopping the server...',
    'srv.rebooting': '⏳ Rebooting the server...',
    'srv.shutting_down': '⏳ Shutting down the server (ACPI)...',
    'srv.performing_operation': '⏳ Performing the operation...',
    'srv.operation_cancelled': '❌ Operation cancelled',
    'srv.refreshing_data': '⏳ Refreshing data...',
    # bal
    'bal.provider_not_found': '❌ <b>Provider not found</b>',
    'bal.error_empty_data': 'Error: empty data',
    'bal.error_data_format': 'Error: data format',
    'bal.error_unknown_command': 'Error: unknown command',
    'bal.main_title': '💰 <b>Cloud provider balances</b>',
    'bal.no_providers': '❌ <i>No providers available</i>',
    'bal.add_api_keys': '💡 Add API keys to the .env file',
    'bal.available_funds': '📊 <b>Available funds:</b>',
    'bal.postpaid_suffix': '(postpaid)',
    'bal.monthly_expenses': '📉 <b>Current month expenses:</b>',
    'bal.unavailable': '⚠️ <b>Unavailable:</b>',
    'bal.no_api_suffix': '(no API)',
    'bal.choose_provider': '💡 Choose a provider for details',
    'bal.history_title_provider': '📊 <b>Balance history {emoji} {provider} ({period} days)</b>',
    'bal.history_title_all': '📊 <b>Balance history ({period} days)</b>',
    'bal.history_insufficient': '❌ <i>Not enough data for this period</i>',
    'bal.history_wait': '💡 Wait a few days to accumulate statistics.',
    'bal.history_only_provider': '💡 History shows data for {provider} only',
    'bal.history_all_providers': '💡 History shows data across all providers',
    'bal.settings_title': '⚙️ <b>Balance settings</b>',
    'bal.settings_threshold': '💵 <b>Notification threshold:</b> ${value:.2f}',
    'bal.settings_threshold_hint': '   <i>A notification is sent when the balance drops below this value</i>',
    'bal.settings_interval': '⏱️ <b>Check interval:</b> {hours:.1f} h',
    'bal.settings_interval_hint': '   <i>How often the balance is checked automatically</i>',
    'bal.settings_how_to': '💡 <b>How to change:</b>',
    'bal.settings_env_line': 'Settings are defined in the <code>.env</code> file:',
    'bal.settings_restart': '<i>A bot restart is required after changing</i>',
    'bal.detail_unavailable': '⚠️ <b>Balance unavailable via API</b>',
    'bal.detail_no_api_body': '{provider} does not provide an API to fetch balance information.',
    'bal.detail_check_manually': "💡 Check the balance manually in the provider's dashboard.",
    'bal.detail_postpaid_costs': '💵 <b>Current month costs:</b> ${value:.2f}',
    'bal.detail_postpaid_hint': '💡 <i>AWS uses postpaid billing — the invoice is issued at month end</i>',
    'bal.detail_available_balance': '💰 <b>Available balance:</b> ${value:.2f}',
    'bal.detail_account_balance': '   ├─ Account balance: ${value:.2f}',
    'bal.detail_pending': '   └─ Pending charges: ${value:.2f}',
    'bal.detail_burn': '📉 <b>Average spend:</b> ${value:.2f}/day',
    'bal.detail_burn_monthly': '   └─ ~${value:.2f}/mo',
    'bal.detail_burn_insufficient': '📉 <b>Average spend:</b> not enough data',
    'bal.detail_burn_insufficient_hint': '   └─ <i>(min. 2 checks in 12 hours)</i>',
    'bal.detail_forecast_period': '   └─ ~{period}',
    'bal.detail_forecast_depleted': '⏳ <b>Forecast:</b> balance depleted',
    'bal.detail_forecast_none': '⏳ <b>Forecast:</b> —',
    'bal.detail_trend_label': '<b>Trend:</b>',
    'bal.detail_last_deposit': '📅 <b>Last deposit:</b>',
    'bal.detail_deposit_date': '   • Date: {date} UTC',
    'bal.detail_deposit_amount': '   • Amount: ${value:.2f}',
    'bal.detail_last_check': '⏰ <b>Last check:</b> {timestamp}',
    # trend
    'trend.increasing': 'rising',
    'trend.decreasing': 'falling',
    'trend.stable': 'stable',
    'trend.unknown': 'unknown',
    # period
    'period.years_months': '{years}y {months}mo',
    'period.years': '{years}y',
    'period.months': '{months}mo',
    # settings
    'settings.title': '⚙️ <b>Settings</b>',
    'settings.language_current': '🌐 <b>Language:</b> {current}',
    'settings.choose_language': '🌐 Choose a language:',
    'settings.language_changed': '✅ Language switched to English',
    'settings.language_not_saved': '⚠️ Language changed for this session, but could not be saved (it may reset after a restart).',
    'settings.menu_updated': '🌐 The menu has been updated.',
    # admin
    'admin.denied_message': (
        '⛔️ <b>Access denied</b>\n'
        '\n'
        'This bot is available to administrators only.'
    ),
    'admin.denied_short': '⛔️ Access denied',
    # cmd
    'cmd.start_desc': 'Start the bot',
    'cmd.language_desc': 'Change language',
    # notif
    'notif.server_down.title': '🔴 <b>Server unavailable</b>',
    'notif.server_down.body': 'Server <b>{name}</b> ({ip}) stopped responding to ping.',
    'notif.error_label': '<b>Error:</b> {error}',
    'notif.server_up.title': '🟢 <b>Server recovered</b>',
    'notif.server_up.body': 'Server <b>{name}</b> ({ip}) is reachable again.',
    'notif.response_time_label': '<b>Response time:</b> {ms} ms',
    'notif.low_balance.title': '🔴 <b>Low balance {provider}</b>',
    'notif.low_balance.body': 'Current balance <b>${balance:.2f}</b> is below the threshold <b>${threshold:.2f}</b>.',
    'notif.low_balance.depleted': '⚠️ <b>Balance depleted!</b>',
    'notif.low_balance.top_up': '💡 Top up your balance in the {provider} dashboard.',
    'notif.critical.title': '🔴 <b>Critical error: {error_type}</b>',
    'notif.critical.check_logs': '⚠️ Check the application logs for more information.',
    'notif.provider_outage.title': '⚠️ <b>Provider unavailable: {provider}</b>',
    'notif.provider_outage.body': 'No response for {duration} ({checks}).',
    'notif.provider_outage.last_error': '<b>Last error:</b> {error}',
    'notif.provider_outage.footer': "This looks like a temporary provider-side issue. I'll let you know when it recovers.",
    # outage
    'outage.duration_hours': '~{hours:.1f} h',
    'outage.duration_minutes': '~{minutes} min',
    # notif
    'notif.provider_recovered.title': '✅ <b>Provider recovered: {provider}</b>',
    'notif.provider_recovered.body': 'Available again. It was down for {duration}.',
    'notif.server_added.title': '🟢 <b>New server detected</b>',
    'notif.server_added.body': 'A new server <b>{name}</b> ({ip}) was found at provider <b>{provider}</b>.',
    'notif.server_added.region': '<b>Region:</b> {region}',
    'notif.server_added.monitoring_started': '✅ Monitoring started automatically.',
    'notif.server_removed.title': '🔴 <b>Server removed</b>',
    'notif.server_removed.body': (
        'Server <b>{name}</b> ({ip}) no longer exists at provider <b>{provider}</b>.\n'
        '\n'
        '⛔ Monitoring stopped.\n'
        '🗑️ Statistics deleted.'
    ),
    # alert
    'alert.provider_api.title': '{provider} API',
    'alert.providers_unavailable.title': 'Providers unavailable',
    'alert.providers_unavailable.body': (
        'All cloud providers are unavailable!\n'
        '\n'
        'Providers: {providers}\n'
        '\n'
        'Check:\n'
        '- API keys in the .env file\n'
        '- Internet connection\n'
        '- Provider API status'
    ),
    'alert.servers_fetch_failed.body': 'Failed to fetch the server list: {error}',
    'alert.worker_abandoned.title': 'Server monitoring stopped',
    'alert.worker_abandoned.body': 'The monitoring worker for server {label} crashed repeatedly and was stopped. The server is temporarily not monitored — it will be retried automatically later. Check the server and network.',
    'alert.core_unavailable.title': 'Monitoring core unavailable',
    'alert.core_unavailable.body': 'The Manager process (which stores server statuses) is not responding. Status updates and part of monitoring are broken. A bot restart will likely be required.',
    'alert.monitoring_stopped.title': 'Monitoring completely stopped',
    'alert.queue_overflow.title': 'Results queue overflowing',
    'alert.queue_overflow.body': 'The ping results queue has been ~{ratio:.0f}% full for several checks in a row — the results processor seems hung or dead. Statistics and notifications may be lost.',
    'alert.db_failure.title': 'Statistics write error',
    'alert.db_failure.body': 'Writing ping statistics to the database keeps failing (repeated errors). ~{dropped} records were dropped to avoid exhausting memory. Monitoring and notifications work, statistics are being lost. Check disk space and the database.',
    'alert.task_gaveup.body': 'Background task «{name}» exited unexpectedly several times ({restarts} restarts in a row) and is NO longer restarted. Intervention required — restart the bot.',
    'alert.task_exited.body': 'Background task «{name}» exited unexpectedly without an error (it is meant to run continuously) and was restarted.',
    'alert.task_crashed.body': 'Background task «{name}» crashed and was restarted.',
    'alert.task_error_label': 'Error: {error}',
    'alert.task_event.type': 'Background task: {name}',
    'alert.task_stalled.title': 'Background task stalled: {name}',
    'alert.task_stalled.body': 'Background task «{name}» has shown no progress for ~{minutes} min (it is running but appears stuck). Auto-restarting a stalled task is unreliable — a bot restart will likely be required. Check the logs.',
}


PLURALS: dict[str, list[str]] = {
    # srv
    'srv.cooldown_wait': [
        '⚠️ Wait {n} more second before the next operation',
        '⚠️ Wait {n} more seconds before the next operation',
    ],
    # bal
    'bal.forecast_days': [
        '⏳ <b>Forecast:</b> ~{n} day',
        '⏳ <b>Forecast:</b> ~{n} days',
    ],
    'bal.history_more': [
        '<i>... and {n} more record</i>',
        '<i>... and {n} more records</i>',
    ],
    # notif
    'notif.low_balance.forecast': [
        '⏳ <b>Forecast:</b> ~{n} day until depletion',
        '⏳ <b>Forecast:</b> ~{n} days until depletion',
    ],
    # plural
    'plural.checks_in_row': [
        '{n} check in a row',
        '{n} checks in a row',
    ],
    # alert
    'alert.no_servers_monitored.body': [
        '{n} server is not being monitored (no live workers) for several checks in a row. Check the bot and the logs.',
        '{n} servers are not being monitored (no live workers) for several checks in a row. Check the bot and the logs.',
    ],
}
