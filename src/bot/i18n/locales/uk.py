"""Ukrainian translation catalog (one module per locale).

Flat ``{key: value}`` mappings. Keys MUST stay in sync with the other
locales — src.bot.i18n.catalog assembles them and the i18n tests enforce
that every locale defines the same keys."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # menu
    'menu.monitoring': '📊 Моніторинг',
    'menu.servers': '🖥️ Сервери',
    'menu.balance': '💰 Баланс',
    'menu.settings': '⚙️ Налаштування',
    'menu.placeholder': 'Оберіть дію...',
    # start
    'start.welcome': (
        '<b>🎉 Ласкаво просимо до системи моніторингу серверів!</b>\n'
        '\n'
        'Цей бот допоможе вам відстежувати стан ваших серверів та керувати ними через Telegram.\n'
        '\n'
        '<b>Доступні функції:</b>\n'
        '📊 <b>Моніторинг</b> - перегляд статусу всіх серверів\n'
        '🖥️ <b>Сервери</b> - керування серверами (додавання, видалення)\n'
        '💰 <b>Баланс</b> - інформація про баланс провайдера\n'
        '⚙️ <b>Налаштування</b> - мова та параметри моніторингу\n'
        '\n'
        'Використовуйте кнопки меню нижче для навігації 👇'
    ),
    # common
    'common.back': '◀️ Назад',
    'common.refresh': '🔄 Оновити',
    'common.refreshed': '✅ Оновлено',
    'common.no_data': 'Немає даних',
    'common.invalid_data_format': '❌ Некоректний формат даних',
    'common.server_not_found': '❌ Сервер не знайдено',
    'common.page_change_error': '❌ Помилка переходу на сторінку',
    'common.unknown_operation': '❌ Невідома операція',
    # kb
    'kb.statistics': '📊 Статистика',
    'kb.manage': '⚙️ Керування',
    'kb.back_to_providers': '◀️ До провайдерів',
    'kb.restart': '🔄 Перезапустити',
    'kb.stop': '⏹️ Зупинити',
    'kb.start': '▶️ Запустити',
    'kb.shutdown_acpi': '🌙 Вимкнути (ACPI)',
    'kb.confirm': '✅ Підтвердити',
    'kb.cancel': '❌ Скасувати',
    'kb.history': '📊 Історія',
    'kb.period_7': '7 днів',
    'kb.period_30': '30 днів',
    # mon
    'mon.empty': (
        '📊 <b>Моніторинг серверів</b>\n'
        '\n'
        'Список серверів порожній.\n'
        'Додайте сервери для моніторингу.'
    ),
    'mon.dashboard_title': '📊 <b>Загальний моніторинг серверів</b>',
    'mon.list_title': '📊 <b>Моніторинг серверів</b>',
    'mon.section_servers': '━━━ <b>Сервери</b> ━━━',
    'mon.total_servers': '<b>Усього серверів:</b> {count}',
    'mon.online': '🟢 Онлайн: {count}',
    'mon.offline': '🔴 Офлайн: {count}',
    'mon.unknown': '❓ Невідомо: {count}',
    'mon.status_inline': '🟢 Онлайн: {online} | 🔴 Офлайн: {offline} | ❓ Невідомо: {unknown}',
    'mon.section_finance': '━━━ <b>Фінанси</b> ({count} пров.) ━━━',
    'mon.finance_balance': '💰 Баланс: ${amount:,.2f}',
    'mon.finance_expenses': '📉 Витрати/міс: ${amount:,.2f}',
    'mon.section_stats_24h': '━━━ <b>Статистика за 24 години</b> ━━━',
    'mon.total_pings': '<b>Усього пінгів:</b> {value}',
    'mon.successful': '<b>Успішно:</b> {value} 🟢',
    'mon.errors': '<b>Помилки:</b> {value} 🔴',
    'mon.timeout': '<b>Тайм-аути:</b> {value} ⏱️',
    'mon.avg_uptime': '<b>Середній аптайм:</b> {value:.2f}%',
    'mon.no_ping_data': 'Немає даних про пінги',
    'mon.section_by_provider': '━━━ <b>За провайдерами</b> ━━━',
    'mon.choose_server': 'Оберіть сервер для перегляду деталей 👇',
    # status
    'status.online': 'Онлайн',
    'status.offline': 'Офлайн',
    'status.unknown': 'Невідомо',
    # power
    'power.on': 'УВІМК',
    'power.off': 'ВИМК',
    # details
    'details.status_label': '<b>Статус:</b>',
    'details.provider_label': '<b>Провайдер:</b>',
    'details.ip_label': '<b>IP:</b>',
    'details.region_label': '<b>Регіон:</b>',
    'details.plan_label': '<b>План:</b>',
    'details.os_label': '<b>ОС:</b>',
    'details.resources_label': '<b>Ресурси:</b>',
    'details.disk_suffix': 'GB Диск',
    'details.last_ping_label': '<b>Останній пінг:</b>',
    'details.response_time_label': '<b>Час відповіді:</b>',
    'details.monitoring_label': '<b>Моніторинг:</b>',
    'details.monitoring_on': 'Увімкнено',
    'details.monitoring_off': 'Вимкнено',
    'details.stats_24h_header': '📊 <b>Статистика за 24 години</b>',
    'details.recent_problems': '🔴 <b>Останні проблеми:</b>',
    # time
    'time.just_now': 'щойно',
    'time.min_ago': '{n} хв тому',
    'time.hours_ago': '{n} год тому',
    'time.na': 'н/д',
    # stats
    'stats.title': '📊 <b>Статистика: {name}</b>',
    'stats.section_1h': '━━━ <b>За 1 годину</b> ━━━',
    'stats.section_24h': '━━━ <b>За 24 години</b> ━━━',
    'stats.section_7d': '━━━ <b>За 7 днів</b> ━━━',
    # srv
    'srv.manage_title': '🖥️ <b>Керування серверами</b>',
    'srv.empty': (
        '🖥️ <b>Керування серверами</b>\n'
        '\n'
        'Список серверів порожній.\n'
        'Додайте сервери для керування.'
    ),
    'srv.choose_provider': 'Оберіть провайдера для перегляду серверів 👇',
    'srv.servers_provider_title': '🖥️ <b>Сервери • {provider}</b>',
    'srv.choose_server': 'Оберіть сервер для керування 👇',
    'srv.confirm_stop_title': '⚠️ <b>Підтвердження зупинки</b>',
    'srv.confirm_stop_q': 'Ви дійсно хочете зупинити сервер:',
    'srv.confirm_stop_warn': (
        '⚠️ <b>Увага:</b> Сервер буде недоступний до наступного запуску.\n'
        'Усі запущені процеси буде зупинено.'
    ),
    'srv.confirm_shutdown_title': '🌙 <b>Підтвердження вимкнення (ACPI)</b>',
    'srv.confirm_shutdown_q': 'Ви дійсно хочете коректно вимкнути сервер:',
    'srv.confirm_shutdown_warn': (
        'ℹ️ <b>Коректне вимкнення:</b> ОС отримає сигнал на коректне завершення.\n'
        'Сервер буде недоступний до наступного запуску.'
    ),
    'srv.confirm_reboot_title': '⚠️ <b>Підтвердження перезавантаження</b>',
    'srv.confirm_reboot_q': 'Ви дійсно хочете перезавантажити сервер:',
    'srv.confirm_reboot_warn': (
        '⚠️ <b>Увага:</b> Сервер буде недоступний під час перезавантаження (1-2 хвилини).\n'
        'Усі активні підключення буде розірвано.'
    ),
    'srv.confirm_generic_title': '⚠️ <b>Підтвердження операції</b>',
    'srv.confirm_generic_server': 'Сервер: <b>{name}</b>',
    'srv.confirm_generic_action': 'Операція: {action}',
    'srv.op_success_title': '✅ <b>Операцію виконано</b>',
    'srv.op_success_body': 'Сервер <b>{name}</b> {action}.',
    'srv.op_success_hint': (
        'ℹ️ <i>Зміни наберуть чинності за 30-60 секунд.\n'
        "Використовуйте кнопку 'Оновити' для перевірки.</i>"
    ),
    'srv.op_error_title': '❌ <b>Помилка {action}</b>',
    'srv.op_error_body': 'Не вдалося виконати операцію для сервера <b>{name}</b>.',
    'srv.op_error_details': '<b>Деталі:</b> {error}',
    'srv.op_error_retry': 'Спробуйте пізніше або зверніться до адміністратора.',
    # provider error details (localized exception text; full technical detail stays in logs)
    'error.invalid_token': 'Недійсний API-токен {provider} — перевірте облікові дані у файлі .env.',
    'error.permission': 'Недостатньо прав для операції: {operation}.',
    'error.not_found': '{resource_type} з ID «{resource_id}» не знайдено.',
    'error.rate_limit': 'Перевищено ліміт запитів до API {provider} — спробуйте трохи згодом.',
    'error.server_side': 'Помилка на боці {provider} — тимчасова проблема, спробуйте пізніше.',
    'error.conflict': 'Неможливо виконати «{operation}»: сервер у стані «{state}».',
    'error.locked': 'Сервер {resource_id} зайнятий — виконується інша операція.',
    'error.provider_api': 'Помилка під час звернення до API {provider} — тимчасова проблема, спробуйте пізніше.',
    # action
    'action.start.done': 'запущено',
    'action.stop.done': 'зупинено',
    'action.reboot.done': 'перезавантажено',
    'action.shutdown.done': 'вимкнено',
    'action.generic.done': 'оброблено',
    'action.start.err': 'запуску',
    'action.stop.err': 'зупинки',
    'action.reboot.err': 'перезавантаження',
    'action.shutdown.err': 'вимкнення',
    'action.generic.err': 'операції',
    # srv
    'srv.provider_unavailable': '❌ Провайдер {provider} недоступний',
    'srv.no_servers_for_provider': '❌ Сервери для {provider} не знайдено',
    'srv.loading_data': '⏳ Отримую дані...',
    'srv.starting': '⏳ Запускаю сервер...',
    'srv.stopping': '⏳ Зупиняю сервер...',
    'srv.rebooting': '⏳ Перезавантажую сервер...',
    'srv.shutting_down': '⏳ Вимикаю сервер (ACPI)...',
    'srv.performing_operation': '⏳ Виконую операцію...',
    'srv.operation_cancelled': '❌ Операцію скасовано',
    'srv.refreshing_data': '⏳ Оновлюю дані...',
    # bal
    'bal.provider_not_found': '❌ <b>Провайдера не знайдено</b>',
    'bal.error_empty_data': 'Помилка: порожні дані',
    'bal.error_data_format': 'Помилка формату даних',
    'bal.error_unknown_command': 'Помилка: невідома команда',
    'bal.main_title': '💰 <b>Баланс хмарних провайдерів</b>',
    'bal.no_providers': '❌ <i>Немає доступних провайдерів</i>',
    'bal.add_api_keys': '💡 Додайте API ключі у файл .env',
    'bal.available_funds': '📊 <b>Доступні кошти:</b>',
    'bal.postpaid_suffix': '(післяплата)',
    'bal.monthly_expenses': '📉 <b>Витрати за поточний місяць:</b>',
    'bal.unavailable': '⚠️ <b>Недоступно:</b>',
    'bal.no_api_suffix': '(немає API)',
    'bal.choose_provider': '💡 Оберіть провайдера для детального перегляду',
    'bal.history_title_provider': '📊 <b>Історія балансу {emoji} {provider} ({period} днів)</b>',
    'bal.history_title_all': '📊 <b>Історія балансу ({period} днів)</b>',
    'bal.history_insufficient': '❌ <i>Даних за цей період недостатньо</i>',
    'bal.history_wait': '💡 Зачекайте кілька днів для накопичення статистики.',
    'bal.history_only_provider': '💡 Історія показує дані лише для {provider}',
    'bal.history_all_providers': '💡 Історія показує дані за всіма провайдерами',
    'bal.settings_title': '⚙️ <b>Налаштування балансу</b>',
    'bal.settings_threshold': '💵 <b>Поріг сповіщення:</b> ${value:.2f}',
    'bal.settings_threshold_hint': '   <i>При падінні нижче цього значення буде надіслано сповіщення</i>',
    'bal.settings_interval': '⏱️ <b>Інтервал перевірки:</b> {hours:.1f} год',
    'bal.settings_interval_hint': '   <i>Частота автоматичної перевірки балансу</i>',
    'bal.settings_how_to': '💡 <b>Як змінити:</b>',
    'bal.settings_env_line': 'Налаштування задаються у файлі <code>.env</code>:',
    'bal.settings_restart': '<i>Після зміни потрібен перезапуск бота</i>',
    'bal.detail_unavailable': '⚠️ <b>Баланс недоступний через API</b>',
    'bal.detail_no_api_body': '{provider} не надає API для отримання інформації про баланс.',
    'bal.detail_check_manually': '💡 Перевірте баланс вручну в панелі керування провайдера.',
    'bal.detail_postpaid_costs': '💵 <b>Витрати за поточний місяць:</b> ${value:.2f}',
    'bal.detail_postpaid_hint': '💡 <i>AWS використовує післяплату - рахунок формується наприкінці місяця</i>',
    'bal.detail_available_balance': '💰 <b>Доступний баланс:</b> ${value:.2f}',
    'bal.detail_account_balance': '   ├─ Баланс акаунта: ${value:.2f}',
    'bal.detail_pending': '   └─ Очікувані списання: ${value:.2f}',
    'bal.detail_burn': '📉 <b>Середні витрати:</b> ${value:.2f}/день',
    'bal.detail_burn_monthly': '   └─ ~${value:.2f}/міс',
    'bal.detail_burn_insufficient': '📉 <b>Середні витрати:</b> недостатньо даних',
    'bal.detail_burn_insufficient_hint': '   └─ <i>(мін. 2 перевірки за 12 годин)</i>',
    'bal.detail_forecast_period': '   └─ ~{period}',
    'bal.detail_forecast_depleted': '⏳ <b>Прогноз:</b> баланс вичерпано',
    'bal.detail_forecast_none': '⏳ <b>Прогноз:</b> —',
    'bal.detail_trend_label': '<b>Тренд:</b>',
    'bal.detail_last_deposit': '📅 <b>Останній депозит:</b>',
    'bal.detail_deposit_date': '   • Дата: {date} UTC',
    'bal.detail_deposit_amount': '   • Сума: ${value:.2f}',
    'bal.detail_last_check': '⏰ <b>Остання перевірка:</b> {timestamp}',
    # trend
    'trend.increasing': 'зростає',
    'trend.decreasing': 'падає',
    'trend.stable': 'стабільно',
    'trend.unknown': 'невідомо',
    # period
    'period.years_months': '{years} р. {months} міс.',
    'period.years': '{years} р.',
    'period.months': '{months} міс.',
    # settings
    'settings.title': '⚙️ <b>Налаштування</b>',
    'settings.language_current': '🌐 <b>Мова:</b> {current}',
    'settings.choose_language': '🌐 Оберіть мову:',
    'settings.language_changed': '✅ Мову змінено на українську',
    'settings.language_not_saved': '⚠️ Мову змінено на цю сесію, але не вдалося зберегти (після перезапуску може скинутися).',
    'settings.menu_updated': '🌐 Меню оновлено.',
    # admin
    'admin.denied_message': (
        '⛔️ <b>Доступ заборонено</b>\n'
        '\n'
        'Цей бот доступний лише адміністраторам.'
    ),
    'admin.denied_short': '⛔️ Доступ заборонено',
    # cmd
    'cmd.start_desc': 'Запустити бота',
    'cmd.language_desc': 'Змінити мову',
    # notif
    'notif.server_down.title': '🔴 <b>Сервер недоступний</b>',
    'notif.server_down.body': 'Сервер <b>{name}</b> ({ip}) перестав відповідати на пінг.',
    'notif.error_label': '<b>Помилка:</b> {error}',
    'notif.server_up.title': '🟢 <b>Сервер відновлено</b>',
    'notif.server_up.body': 'Сервер <b>{name}</b> ({ip}) знову доступний.',
    'notif.response_time_label': '<b>Час відповіді:</b> {ms} ms',
    'notif.low_balance.title': '🔴 <b>Низький баланс {provider}</b>',
    'notif.low_balance.body': 'Поточний баланс <b>${balance:.2f}</b> нижчий за поріг <b>${threshold:.2f}</b>.',
    'notif.low_balance.depleted': '⚠️ <b>Баланс вичерпано!</b>',
    'notif.low_balance.top_up': '💡 Поповніть баланс в особистому кабінеті {provider}.',
    'notif.critical.title': '🔴 <b>Критична помилка: {error_type}</b>',
    'notif.critical.check_logs': '⚠️ Перевірте логи застосунку для додаткової інформації.',
    'notif.provider_outage.title': '⚠️ <b>Провайдер недоступний: {provider}</b>',
    'notif.provider_outage.body': 'Не відповідає вже {duration} ({checks}).',
    'notif.provider_outage.last_error': '<b>Остання помилка:</b> {error}',
    'notif.provider_outage.footer': 'Схоже на тимчасові проблеми на боці провайдера. Повідомлю, коли доступність відновиться.',
    # outage
    'outage.duration_hours': '~{hours:.1f} год',
    'outage.duration_minutes': '~{minutes} хв',
    # notif
    'notif.provider_recovered.title': '✅ <b>Провайдера відновлено: {provider}</b>',
    'notif.provider_recovered.body': 'Знову доступний. Був недоступний {duration}.',
    'notif.server_added.title': '🟢 <b>Виявлено новий сервер</b>',
    'notif.server_added.body': 'Виявлено новий сервер <b>{name}</b> ({ip}) у провайдера <b>{provider}</b>.',
    'notif.server_added.region': '<b>Регіон:</b> {region}',
    'notif.server_added.monitoring_started': '✅ Моніторинг запущено автоматично.',
    'notif.server_removed.title': '🔴 <b>Сервер видалено</b>',
    'notif.server_removed.body': (
        'Сервер <b>{name}</b> ({ip}) більше не існує у провайдера <b>{provider}</b>.\n'
        '\n'
        '⛔ Моніторинг зупинено.\n'
        '🗑️ Статистику видалено.'
    ),
    # alert
    'alert.provider_api.title': '{provider} API',
    'alert.providers_unavailable.title': 'Провайдери недоступні',
    'alert.providers_unavailable.body': (
        'Усі хмарні провайдери недоступні!\n'
        '\n'
        'Провайдери: {providers}\n'
        '\n'
        'Перевірте:\n'
        '- API ключі у файлі .env\n'
        '- Підключення до інтернету\n'
        '- Статус API провайдерів'
    ),
    'alert.servers_fetch_failed.body': 'Не вдалося отримати список серверів: {error}',
    'alert.worker_abandoned.title': 'Моніторинг сервера зупинено',
    'alert.worker_abandoned.body': 'Воркер моніторингу сервера {label} кілька разів поспіль аварійно завершувався і був зупинений. Сервер тимчасово не моніториться — буде автоматична повторна спроба пізніше. Перевірте сервер і мережу.',
    'alert.core_unavailable.title': 'Ядро моніторингу недоступне',
    'alert.core_unavailable.body': 'Процес Manager (зберігає статуси серверів) не відповідає. Оновлення статусів і частина моніторингу порушені. Імовірно, знадобиться перезапуск бота.',
    'alert.monitoring_stopped.title': 'Моніторинг повністю зупинено',
    'alert.queue_overflow.title': 'Черга результатів переповнюється',
    'alert.queue_overflow.body': 'Черга результатів пінгу заповнена на ~{ratio:.0f}% уже кілька перевірок поспіль — обробник результатів, схоже, завис або помер. Статистика та сповіщення можуть втрачатися.',
    'alert.db_failure.title': 'Помилка запису статистики',
    'alert.db_failure.body': 'Запис статистики пінгу в базу не вдається (повторювані помилки). Відкинуто ~{dropped} записів, щоб не переповнити пам’ять. Моніторинг і сповіщення працюють, статистика втрачається. Перевірте місце на диску та БД.',
    'alert.task_gaveup.body': 'Фонове завдання «{name}» неодноразово несподівано завершувалося ({restarts} перезапусків поспіль) і більше НЕ перезапускається. Потрібне втручання — перезапустіть бота.',
    'alert.task_exited.body': 'Фонове завдання «{name}» несподівано завершилося без помилки (воно має працювати постійно) і було перезапущено.',
    'alert.task_crashed.body': 'Фонове завдання «{name}» аварійно завершилося і було перезапущено.',
    'alert.task_error_label': 'Помилка: {error}',
    'alert.task_event.type': 'Фонове завдання: {name}',
    'alert.task_stalled.title': 'Фонове завдання зависло: {name}',
    'alert.task_stalled.body': 'Фонове завдання «{name}» не подає ознак прогресу вже ~{minutes} хв (воно запущене, але, схоже, зависло). Автоперезапуск завислого завдання ненадійний — імовірно, знадобиться перезапуск бота. Перевірте логи.',
}


PLURALS: dict[str, list[str]] = {
    # srv
    'srv.cooldown_wait': [
        '⚠️ Зачекайте ще {n} секунду перед наступною операцією',
        '⚠️ Зачекайте ще {n} секунди перед наступною операцією',
        '⚠️ Зачекайте ще {n} секунд перед наступною операцією',
    ],
    # bal
    'bal.forecast_days': [
        '⏳ <b>Прогноз:</b> ~{n} день',
        '⏳ <b>Прогноз:</b> ~{n} дні',
        '⏳ <b>Прогноз:</b> ~{n} днів',
    ],
    'bal.history_more': [
        '<i>... та ще {n} запис</i>',
        '<i>... та ще {n} записи</i>',
        '<i>... та ще {n} записів</i>',
    ],
    # notif
    'notif.low_balance.forecast': [
        '⏳ <b>Прогноз:</b> ~{n} день до вичерпання',
        '⏳ <b>Прогноз:</b> ~{n} дні до вичерпання',
        '⏳ <b>Прогноз:</b> ~{n} днів до вичерпання',
    ],
    # plural
    'plural.checks_in_row': [
        '{n} перевірка поспіль',
        '{n} перевірки поспіль',
        '{n} перевірок поспіль',
    ],
    # alert
    'alert.no_servers_monitored.body': [
        'Не моніториться {n} сервер (немає живих воркерів) уже кілька перевірок поспіль. Перевірте бота і логи.',
        'Не моніторяться {n} сервери (немає живих воркерів) уже кілька перевірок поспіль. Перевірте бота і логи.',
        'Не моніториться {n} серверів (немає живих воркерів) уже кілька перевірок поспіль. Перевірте бота і логи.',
    ],
}
