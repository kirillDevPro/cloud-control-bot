"""Russian translation catalog (one module per locale).

Flat ``{key: value}`` mappings. Keys MUST stay in sync with the other
locales — src.bot.i18n.catalog assembles them and the i18n tests enforce
that every locale defines the same keys."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # menu
    'menu.monitoring': '📊 Мониторинг',
    'menu.servers': '🖥️ Серверы',
    'menu.balance': '💰 Баланс',
    'menu.settings': '⚙️ Настройки',
    'menu.placeholder': 'Выберите действие...',
    # start
    'start.welcome': (
        '<b>🎉 Добро пожаловать в систему мониторинга серверов!</b>\n'
        '\n'
        'Этот бот поможет вам отслеживать состояние ваших серверов и управлять ими через Telegram.\n'
        '\n'
        '<b>Доступные функции:</b>\n'
        '📊 <b>Мониторинг</b> - просмотр статуса всех серверов\n'
        '🖥️ <b>Серверы</b> - управление серверами (добавление, удаление)\n'
        '💰 <b>Баланс</b> - информация о балансе провайдера\n'
        '⚙️ <b>Настройки</b> - язык и параметры мониторинга\n'
        '\n'
        'Используйте кнопки меню ниже для навигации 👇'
    ),
    # common
    'common.back': '◀️ Назад',
    'common.refresh': '🔄 Обновить',
    'common.refreshed': '✅ Обновлено',
    'common.no_data': 'Нет данных',
    'common.invalid_data_format': '❌ Некорректный формат данных',
    'common.server_not_found': '❌ Сервер не найден',
    'common.page_change_error': '❌ Ошибка при переходе на страницу',
    'common.unknown_operation': '❌ Неизвестная операция',
    # kb
    'kb.statistics': '📊 Статистика',
    'kb.manage': '⚙️ Управление',
    'kb.back_to_providers': '◀️ К провайдерам',
    'kb.restart': '🔄 Перезапустить',
    'kb.stop': '⏹️ Остановить',
    'kb.start': '▶️ Запустить',
    'kb.shutdown_acpi': '🌙 Выключить (ACPI)',
    'kb.confirm': '✅ Подтвердить',
    'kb.cancel': '❌ Отмена',
    'kb.history': '📊 История',
    'kb.period_7': '7 дней',
    'kb.period_30': '30 дней',
    # mon
    'mon.empty': (
        '📊 <b>Мониторинг серверов</b>\n'
        '\n'
        'Список серверов пуст.\n'
        'Добавьте серверы для мониторинга.'
    ),
    'mon.dashboard_title': '📊 <b>Общий мониторинг серверов</b>',
    'mon.list_title': '📊 <b>Мониторинг серверов</b>',
    'mon.section_servers': '━━━ <b>Серверы</b> ━━━',
    'mon.total_servers': '<b>Всего серверов:</b> {count}',
    'mon.online': '🟢 Онлайн: {count}',
    'mon.offline': '🔴 Офлайн: {count}',
    'mon.unknown': '❓ Неизвестно: {count}',
    'mon.status_inline': '🟢 Онлайн: {online} | 🔴 Офлайн: {offline} | ❓ Неизвестно: {unknown}',
    'mon.section_finance': '━━━ <b>Финансы</b> ({count} пров.) ━━━',
    'mon.finance_balance': '💰 Баланс: ${amount:,.2f}',
    'mon.finance_expenses': '📉 Расходы/мес: ${amount:,.2f}',
    'mon.section_stats_24h': '━━━ <b>Статистика за 24 часа</b> ━━━',
    'mon.total_pings': '<b>Всего пингов:</b> {value}',
    'mon.successful': '<b>Успешно:</b> {value} 🟢',
    'mon.errors': '<b>Ошибки:</b> {value} 🔴',
    'mon.timeout': '<b>Timeout:</b> {value} ⏱️',
    'mon.avg_uptime': '<b>Средний Uptime:</b> {value:.2f}%',
    'mon.no_ping_data': 'Нет данных о пингах',
    'mon.section_by_provider': '━━━ <b>По провайдерам</b> ━━━',
    'mon.choose_server': 'Выберите сервер для просмотра деталей 👇',
    # status
    'status.online': 'Онлайн',
    'status.offline': 'Офлайн',
    'status.unknown': 'Неизвестно',
    # power
    'power.on': 'ВКЛ',
    'power.off': 'ВЫКЛ',
    # details
    'details.status_label': '<b>Статус:</b>',
    'details.provider_label': '<b>Провайдер:</b>',
    'details.ip_label': '<b>IP:</b>',
    'details.region_label': '<b>Регион:</b>',
    'details.plan_label': '<b>План:</b>',
    'details.os_label': '<b>ОС:</b>',
    'details.resources_label': '<b>Ресурсы:</b>',
    'details.disk_suffix': 'GB Диск',
    'details.last_ping_label': '<b>Последний пинг:</b>',
    'details.response_time_label': '<b>Время отклика:</b>',
    'details.monitoring_label': '<b>Мониторинг:</b>',
    'details.monitoring_on': 'Включён',
    'details.monitoring_off': 'Выключен',
    'details.stats_24h_header': '📊 <b>Статистика за 24 часа</b>',
    'details.recent_problems': '🔴 <b>Последние проблемы:</b>',
    # time
    'time.just_now': 'только что',
    'time.min_ago': '{n} мин назад',
    'time.hours_ago': '{n} ч назад',
    'time.na': 'н/д',
    # stats
    'stats.title': '📊 <b>Статистика: {name}</b>',
    'stats.section_1h': '━━━ <b>За 1 час</b> ━━━',
    'stats.section_24h': '━━━ <b>За 24 часа</b> ━━━',
    'stats.section_7d': '━━━ <b>За 7 дней</b> ━━━',
    # srv
    'srv.manage_title': '🖥️ <b>Управление серверами</b>',
    'srv.empty': (
        '🖥️ <b>Управление серверами</b>\n'
        '\n'
        'Список серверов пуст.\n'
        'Добавьте серверы для управления.'
    ),
    'srv.choose_provider': 'Выберите провайдера для просмотра серверов 👇',
    'srv.servers_provider_title': '🖥️ <b>Серверы • {provider}</b>',
    'srv.choose_server': 'Выберите сервер для управления 👇',
    'srv.confirm_stop_title': '⚠️ <b>Подтверждение остановки</b>',
    'srv.confirm_stop_q': 'Вы действительно хотите остановить сервер:',
    'srv.confirm_stop_warn': (
        '⚠️ <b>Внимание:</b> Сервер будет недоступен до следующего запуска.\n'
        'Все запущенные процессы будут остановлены.'
    ),
    'srv.confirm_shutdown_title': '🌙 <b>Подтверждение выключения (ACPI)</b>',
    'srv.confirm_shutdown_q': 'Вы действительно хотите корректно выключить сервер:',
    'srv.confirm_shutdown_warn': (
        'ℹ️ <b>Корректное выключение:</b> ОС получит сигнал на корректное завершение.\n'
        'Сервер будет недоступен до следующего запуска.'
    ),
    'srv.confirm_reboot_title': '⚠️ <b>Подтверждение перезагрузки</b>',
    'srv.confirm_reboot_q': 'Вы действительно хотите перезагрузить сервер:',
    'srv.confirm_reboot_warn': (
        '⚠️ <b>Внимание:</b> Сервер будет недоступен на время перезагрузки (1-2 минуты).\n'
        'Все активные подключения будут разорваны.'
    ),
    'srv.confirm_generic_title': '⚠️ <b>Подтверждение операции</b>',
    'srv.confirm_generic_server': 'Сервер: <b>{name}</b>',
    'srv.confirm_generic_action': 'Операция: {action}',
    'srv.op_success_title': '✅ <b>Операция выполнена</b>',
    'srv.op_success_body': 'Сервер <b>{name}</b> {action}.',
    'srv.op_success_hint': (
        'ℹ️ <i>Изменения вступят в силу через 30-60 секунд.\n'
        "Используйте кнопку 'Обновить' для проверки.</i>"
    ),
    'srv.op_error_title': '❌ <b>Ошибка {action}</b>',
    'srv.op_error_body': 'Не удалось выполнить операцию для сервера <b>{name}</b>.',
    'srv.op_error_details': '<b>Детали:</b> {error}',
    'srv.op_error_retry': 'Попробуйте позже или обратитесь к администратору.',
    # provider error details (localized exception text; full technical detail stays in logs)
    'error.invalid_token': 'Недействительный API-токен {provider} — проверьте учётные данные в файле .env.',
    'error.permission': 'Недостаточно прав для операции: {operation}.',
    'error.not_found': '{resource_type} с ID «{resource_id}» не найден.',
    'error.rate_limit': 'Превышен лимит запросов к API {provider} — попробуйте чуть позже.',
    'error.server_side': 'Ошибка на стороне {provider} — временная проблема, попробуйте позже.',
    'error.conflict': 'Невозможно выполнить «{operation}»: сервер в состоянии «{state}».',
    'error.locked': 'Сервер {resource_id} занят — выполняется другая операция.',
    'error.provider_api': 'Ошибка связи с API {provider} — временная проблема, попробуйте позже.',
    # action
    'action.start.done': 'запущен',
    'action.stop.done': 'остановлен',
    'action.reboot.done': 'перезагружен',
    'action.shutdown.done': 'выключен',
    'action.generic.done': 'обработан',
    'action.start.err': 'запуска',
    'action.stop.err': 'остановки',
    'action.reboot.err': 'перезагрузки',
    'action.shutdown.err': 'выключения',
    'action.generic.err': 'операции',
    # srv
    'srv.provider_unavailable': '❌ Провайдер {provider} недоступен',
    'srv.no_servers_for_provider': '❌ Серверы для {provider} не найдены',
    'srv.loading_data': '⏳ Получаю данные...',
    'srv.starting': '⏳ Запускаю сервер...',
    'srv.stopping': '⏳ Останавливаю сервер...',
    'srv.rebooting': '⏳ Перезагружаю сервер...',
    'srv.shutting_down': '⏳ Выключаю сервер (ACPI)...',
    'srv.performing_operation': '⏳ Выполняю операцию...',
    'srv.operation_cancelled': '❌ Операция отменена',
    'srv.refreshing_data': '⏳ Обновляю данные...',
    # bal
    'bal.provider_not_found': '❌ <b>Провайдер не найден</b>',
    'bal.error_empty_data': 'Ошибка: пустые данные',
    'bal.error_data_format': 'Ошибка формата данных',
    'bal.error_unknown_command': 'Ошибка: неизвестная команда',
    'bal.main_title': '💰 <b>Баланс облачных провайдеров</b>',
    'bal.no_providers': '❌ <i>Нет доступных провайдеров</i>',
    'bal.add_api_keys': '💡 Добавьте API ключи в файл .env',
    'bal.available_funds': '📊 <b>Доступные средства:</b>',
    'bal.postpaid_suffix': '(постоплата)',
    'bal.monthly_expenses': '📉 <b>Расходы за текущий месяц:</b>',
    'bal.unavailable': '⚠️ <b>Недоступно:</b>',
    'bal.no_api_suffix': '(нет API)',
    'bal.choose_provider': '💡 Выберите провайдера для детального просмотра',
    'bal.history_title_provider': '📊 <b>История баланса {emoji} {provider} ({period} дней)</b>',
    'bal.history_title_all': '📊 <b>История баланса ({period} дней)</b>',
    'bal.history_insufficient': '❌ <i>Данных за этот период недостаточно</i>',
    'bal.history_wait': '💡 Подождите несколько дней для накопления статистики.',
    'bal.history_only_provider': '💡 История показывает данные только для {provider}',
    'bal.history_all_providers': '💡 История показывает данные по всем провайдерам',
    'bal.settings_title': '⚙️ <b>Настройки баланса</b>',
    'bal.settings_threshold': '💵 <b>Порог уведомления:</b> ${value:.2f}',
    'bal.settings_threshold_hint': '   <i>При падении ниже этого значения будет отправлено уведомление</i>',
    'bal.settings_interval': '⏱️ <b>Интервал проверки:</b> {hours:.1f} ч',
    'bal.settings_interval_hint': '   <i>Частота автоматической проверки баланса</i>',
    'bal.settings_how_to': '💡 <b>Как изменить:</b>',
    'bal.settings_env_line': 'Настройки задаются в файле <code>.env</code>:',
    'bal.settings_restart': '<i>После изменения необходим перезапуск бота</i>',
    'bal.detail_unavailable': '⚠️ <b>Баланс недоступен через API</b>',
    'bal.detail_no_api_body': '{provider} не предоставляет API для получения информации о балансе.',
    'bal.detail_check_manually': '💡 Проверьте баланс вручную в панели управления провайдера.',
    'bal.detail_postpaid_costs': '💵 <b>Затраты за текущий месяц:</b> ${value:.2f}',
    'bal.detail_postpaid_hint': '💡 <i>AWS использует постоплату - счёт формируется в конце месяца</i>',
    'bal.detail_available_balance': '💰 <b>Доступный баланс:</b> ${value:.2f}',
    'bal.detail_account_balance': '   ├─ Баланс аккаунта: ${value:.2f}',
    'bal.detail_pending': '   └─ К списанию: ${value:.2f}',
    'bal.detail_burn': '📉 <b>Средний расход:</b> ${value:.2f}/день',
    'bal.detail_burn_monthly': '   └─ ~${value:.2f}/мес',
    'bal.detail_burn_insufficient': '📉 <b>Средний расход:</b> недостаточно данных',
    'bal.detail_burn_insufficient_hint': '   └─ <i>(мин. 2 проверки за 12 часов)</i>',
    'bal.detail_forecast_period': '   └─ ~{period}',
    'bal.detail_forecast_depleted': '⏳ <b>Прогноз:</b> баланс исчерпан',
    'bal.detail_forecast_none': '⏳ <b>Прогноз:</b> —',
    'bal.detail_trend_label': '<b>Тренд:</b>',
    'bal.detail_last_deposit': '📅 <b>Последний депозит:</b>',
    'bal.detail_deposit_date': '   • Дата: {date} UTC',
    'bal.detail_deposit_amount': '   • Сумма: ${value:.2f}',
    'bal.detail_last_check': '⏰ <b>Последняя проверка:</b> {timestamp}',
    # trend
    'trend.increasing': 'растёт',
    'trend.decreasing': 'падает',
    'trend.stable': 'стабильно',
    'trend.unknown': 'неизвестно',
    # period
    'period.years_months': '{years} г. {months} мес.',
    'period.years': '{years} г.',
    'period.months': '{months} мес.',
    # settings
    'settings.title': '⚙️ <b>Настройки</b>',
    'settings.language_current': '🌐 <b>Язык:</b> {current}',
    'settings.choose_language': '🌐 Выберите язык:',
    'settings.language_changed': '✅ Язык переключён на русский',
    'settings.language_not_saved': '⚠️ Язык изменён на эту сессию, но не удалось сохранить (после перезапуска может сброситься).',
    'settings.menu_updated': '🌐 Меню обновлено.',
    # admin
    'admin.denied_message': (
        '⛔️ <b>Доступ запрещён</b>\n'
        '\n'
        'Этот бот доступен только администраторам.'
    ),
    'admin.denied_short': '⛔️ Доступ запрещён',
    # cmd
    'cmd.start_desc': 'Запустить бота',
    'cmd.language_desc': 'Сменить язык',
    # notif
    'notif.server_down.title': '🔴 <b>Сервер недоступен</b>',
    'notif.server_down.body': 'Сервер <b>{name}</b> ({ip}) перестал отвечать на пинг.',
    'notif.error_label': '<b>Ошибка:</b> {error}',
    'notif.server_up.title': '🟢 <b>Сервер восстановлен</b>',
    'notif.server_up.body': 'Сервер <b>{name}</b> ({ip}) снова доступен.',
    'notif.response_time_label': '<b>Время отклика:</b> {ms} ms',
    'notif.low_balance.title': '🔴 <b>Низкий баланс {provider}</b>',
    'notif.low_balance.body': 'Текущий баланс <b>${balance:.2f}</b> ниже порога <b>${threshold:.2f}</b>.',
    'notif.low_balance.depleted': '⚠️ <b>Баланс исчерпан!</b>',
    'notif.low_balance.top_up': '💡 Пополните баланс в личном кабинете {provider}.',
    'notif.critical.title': '🔴 <b>Критическая ошибка: {error_type}</b>',
    'notif.critical.check_logs': '⚠️ Проверьте логи приложения для дополнительной информации.',
    'notif.provider_outage.title': '⚠️ <b>Провайдер недоступен: {provider}</b>',
    'notif.provider_outage.body': 'Не отвечает уже {duration} ({checks}).',
    'notif.provider_outage.last_error': '<b>Последняя ошибка:</b> {error}',
    'notif.provider_outage.footer': 'Похоже на временные проблемы на стороне провайдера. Сообщу, когда доступность восстановится.',
    # outage
    'outage.duration_hours': '~{hours:.1f} ч',
    'outage.duration_minutes': '~{minutes} мин',
    # notif
    'notif.provider_recovered.title': '✅ <b>Провайдер восстановлен: {provider}</b>',
    'notif.provider_recovered.body': 'Снова доступен. Был недоступен {duration}.',
    'notif.server_added.title': '🟢 <b>Новый сервер обнаружен</b>',
    'notif.server_added.body': 'Обнаружен новый сервер <b>{name}</b> ({ip}) у провайдера <b>{provider}</b>.',
    'notif.server_added.region': '<b>Регион:</b> {region}',
    'notif.server_added.monitoring_started': '✅ Мониторинг запущен автоматически.',
    'notif.server_removed.title': '🔴 <b>Сервер удален</b>',
    'notif.server_removed.body': (
        'Сервер <b>{name}</b> ({ip}) больше не существует у провайдера <b>{provider}</b>.\n'
        '\n'
        '⛔ Мониторинг остановлен.\n'
        '🗑️ Статистика удалена.'
    ),
    # alert
    'alert.provider_api.title': '{provider} API',
    'alert.providers_unavailable.title': 'Провайдеры недоступны',
    'alert.providers_unavailable.body': (
        'Все облачные провайдеры недоступны!\n'
        '\n'
        'Провайдеры: {providers}\n'
        '\n'
        'Проверьте:\n'
        '- API ключи в .env файле\n'
        '- Подключение к интернету\n'
        '- Статус API провайдеров'
    ),
    'alert.servers_fetch_failed.body': 'Не удалось получить список серверов: {error}',
    'alert.worker_abandoned.title': 'Мониторинг сервера остановлен',
    'alert.worker_abandoned.body': 'Воркер мониторинга сервера {label} несколько раз подряд аварийно завершался и был остановлен. Сервер временно не мониторится — будет автоматическая повторная попытка позже. Проверьте сервер и сеть.',
    'alert.core_unavailable.title': 'Ядро мониторинга недоступно',
    'alert.core_unavailable.body': 'Процесс Manager (хранит статусы серверов) не отвечает. Обновление статусов и часть мониторинга нарушены. Вероятно, потребуется перезапуск бота.',
    'alert.monitoring_stopped.title': 'Мониторинг полностью остановлен',
    'alert.queue_overflow.title': 'Очередь результатов переполняется',
    'alert.queue_overflow.body': 'Очередь результатов пинга заполнена на ~{ratio:.0f}% уже несколько проверок подряд — обработчик результатов, похоже, завис или умер. Статистика и уведомления могут теряться.',
    'alert.db_failure.title': 'Ошибка записи статистики',
    'alert.db_failure.body': 'Запись статистики пинга в базу не удаётся (повторяющиеся ошибки). Отброшено ~{dropped} записей, чтобы не переполнить память. Мониторинг и уведомления работают, статистика теряется. Проверьте место на диске и БД.',
    'alert.task_gaveup.body': 'Фоновая задача «{name}» неоднократно неожиданно завершалась ({restarts} перезапусков подряд) и больше НЕ перезапускается. Требуется вмешательство — перезапустите бота.',
    'alert.task_exited.body': 'Фоновая задача «{name}» неожиданно завершилась без ошибки (она должна работать постоянно) и была перезапущена.',
    'alert.task_crashed.body': 'Фоновая задача «{name}» аварийно завершилась и была перезапущена.',
    'alert.task_error_label': 'Ошибка: {error}',
    'alert.task_event.type': 'Фоновая задача: {name}',
    'alert.task_stalled.title': 'Фоновая задача зависла: {name}',
    'alert.task_stalled.body': 'Фоновая задача «{name}» не подаёт признаков прогресса уже ~{minutes} мин (она запущена, но, похоже, зависла). Автоперезапуск зависшей задачи ненадёжен — вероятно, потребуется перезапуск бота. Проверьте логи.',
}


PLURALS: dict[str, list[str]] = {
    # srv
    'srv.cooldown_wait': [
        '⚠️ Подождите ещё {n} секунду перед следующей операцией',
        '⚠️ Подождите ещё {n} секунды перед следующей операцией',
        '⚠️ Подождите ещё {n} секунд перед следующей операцией',
    ],
    # bal
    'bal.forecast_days': [
        '⏳ <b>Прогноз:</b> ~{n} день',
        '⏳ <b>Прогноз:</b> ~{n} дня',
        '⏳ <b>Прогноз:</b> ~{n} дней',
    ],
    'bal.history_more': [
        '<i>... и ещё {n} запись</i>',
        '<i>... и ещё {n} записи</i>',
        '<i>... и ещё {n} записей</i>',
    ],
    # notif
    'notif.low_balance.forecast': [
        '⏳ <b>Прогноз:</b> ~{n} день до исчерпания',
        '⏳ <b>Прогноз:</b> ~{n} дня до исчерпания',
        '⏳ <b>Прогноз:</b> ~{n} дней до исчерпания',
    ],
    # plural
    'plural.checks_in_row': [
        '{n} проверка подряд',
        '{n} проверки подряд',
        '{n} проверок подряд',
    ],
    # alert
    'alert.no_servers_monitored.body': [
        'Не мониторится {n} сервер (нет живых воркеров) уже несколько проверок подряд. Проверьте бота и логи.',
        'Не мониторятся {n} сервера (нет живых воркеров) уже несколько проверок подряд. Проверьте бота и логи.',
        'Не мониторятся {n} серверов (нет живых воркеров) уже несколько проверок подряд. Проверьте бота и логи.',
    ],
}
