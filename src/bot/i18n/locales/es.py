"""Spanish translation catalog (one module per locale).

Flat ``{key: value}`` mappings. Keys MUST stay in sync with the other
locales — src.bot.i18n.catalog assembles them and the i18n tests enforce
that every locale defines the same keys."""

from __future__ import annotations

MESSAGES: dict[str, str] = {
    # menu
    'menu.monitoring': '📊 Monitoreo',
    'menu.servers': '🖥️ Servidores',
    'menu.balance': '💰 Saldo',
    'menu.settings': '⚙️ Ajustes',
    'menu.placeholder': 'Elige una acción...',
    # start
    'start.welcome': (
        '<b>🎉 ¡Bienvenido al sistema de monitoreo de servidores!</b>\n'
        '\n'
        'Este bot te ayuda a controlar el estado de tus servidores y gestionarlos desde Telegram.\n'
        '\n'
        '<b>Funciones disponibles:</b>\n'
        '📊 <b>Monitoreo</b> — consulta el estado de todos los servidores\n'
        '🖥️ <b>Servidores</b> — gestiona servidores (añadir, eliminar)\n'
        '💰 <b>Saldo</b> — información del saldo de los proveedores\n'
        '⚙️ <b>Ajustes</b> — opciones de idioma y monitoreo\n'
        '\n'
        'Usa los botones del menú de abajo para navegar 👇'
    ),
    # common
    'common.back': '◀️ Atrás',
    'common.refresh': '🔄 Actualizar',
    'common.refreshed': '✅ Actualizado',
    'common.invalid_data_format': '❌ Formato de datos no válido',
    'common.server_not_found': '❌ Servidor no encontrado',
    'common.page_change_error': '❌ No se pudo cambiar de página',
    'common.unknown_operation': '❌ Operación desconocida',
    # kb
    'kb.statistics': '📊 Estadísticas',
    'kb.manage': '⚙️ Gestionar',
    'kb.back_to_providers': '◀️ A proveedores',
    'kb.restart': '🔄 Reiniciar',
    'kb.stop': '⏹️ Detener',
    'kb.start': '▶️ Iniciar',
    'kb.shutdown_acpi': '🌙 Apagar (ACPI)',
    'kb.confirm': '✅ Confirmar',
    'kb.cancel': '❌ Cancelar',
    'kb.history': '📊 Historial',
    'kb.period_7': '7 días',
    'kb.period_30': '30 días',
    # mon
    'mon.empty': (
        '📊 <b>Monitoreo de servidores</b>\n'
        '\n'
        'La lista de servidores está vacía.\n'
        'Añade servidores para comenzar el monitoreo.'
    ),
    'mon.dashboard_title': '📊 <b>Monitoreo general de servidores</b>',
    'mon.list_title': '📊 <b>Monitoreo de servidores</b>',
    'mon.section_servers': '━━━ <b>Servidores</b> ━━━',
    'mon.total_servers': '<b>Servidores totales:</b> {count}',
    'mon.status_inline': '🟢 En línea: {online} | 🔴 Fuera de línea: {offline} | ❓ Desconocido: {unknown}',
    'mon.section_finance': '━━━ <b>Finanzas</b> ({count} prov.) ━━━',
    'mon.finance_balance': '💰 Saldo: ${amount:,.2f}',
    'mon.finance_expenses': '📉 Gastos/mes: ${amount:,.2f}',
    'mon.section_stats_24h': '━━━ <b>Estadísticas (24 horas)</b> ━━━',
    'mon.no_ping_data': 'Sin datos de ping',
    'mon.section_by_provider': '━━━ <b>Por proveedor</b> ━━━',
    'mon.choose_server': 'Elige un servidor para ver los detalles 👇',
    # status
    'status.online': 'EN LÍNEA',
    'status.offline': 'FUERA DE LÍNEA',
    'status.unknown': 'DESCONOCIDO',
    # power
    'power.on': 'ENCENDIDO',
    'power.off': 'APAGADO',
    # details
    'details.status_label': '<b>Estado:</b>',
    'details.provider_label': '<b>Proveedor:</b>',
    'details.ip_label': '<b>IP:</b>',
    'details.region_label': '<b>Región:</b>',
    'details.plan_label': '<b>Plan:</b>',
    'details.os_label': '<b>SO:</b>',
    'details.resources_label': '<b>Recursos:</b>',
    'details.disk_suffix': 'GB de disco',
    'details.last_ping_label': '<b>Último ping:</b>',
    'details.response_time_label': '<b>Tiempo de respuesta:</b>',
    'details.monitoring_label': '<b>Monitoreo:</b>',
    'details.monitoring_on': 'Activado',
    'details.monitoring_off': 'Desactivado',
    'details.stats_24h_header': '📊 <b>Estadísticas (24 horas)</b>',
    'details.recent_problems': '🔴 <b>Problemas recientes:</b>',
    # time
    'time.just_now': 'ahora mismo',
    'time.min_ago': 'hace {n} min',
    'time.hours_ago': 'hace {n} h',
    'time.na': 'n/d',
    # stats
    'stats.title': '📊 <b>Estadísticas: {name}</b>',
    # srv
    'srv.manage_title': '🖥️ <b>Gestión de servidores</b>',
    'srv.empty': (
        '🖥️ <b>Gestión de servidores</b>\n'
        '\n'
        'La lista de servidores está vacía.\n'
        'Añade servidores para gestionarlos.'
    ),
    'srv.choose_provider': 'Elige un proveedor para ver los servidores 👇',
    'srv.servers_provider_title': '🖥️ <b>Servidores • {provider}</b>',
    'srv.choose_server': 'Elige un servidor para gestionarlo 👇',
    'srv.confirm_stop_title': '⚠️ <b>Confirmar detención</b>',
    'srv.confirm_stop_q': '¿Seguro que quieres detener el servidor?',
    'srv.confirm_stop_warn': (
        '⚠️ <b>Advertencia:</b> El servidor no estará disponible hasta el próximo inicio.\n'
        'Se detendrán todos los procesos en ejecución.'
    ),
    'srv.confirm_shutdown_title': '🌙 <b>Confirmar apagado (ACPI)</b>',
    'srv.confirm_shutdown_q': '¿Seguro que quieres apagar de forma controlada el servidor?',
    'srv.confirm_shutdown_warn': (
        'ℹ️ <b>Apagado controlado:</b> El SO recibirá una señal para apagarse limpiamente.\n'
        'El servidor no estará disponible hasta el próximo inicio.'
    ),
    'srv.confirm_reboot_title': '⚠️ <b>Confirmar reinicio</b>',
    'srv.confirm_reboot_q': '¿Seguro que quieres reiniciar el servidor?',
    'srv.confirm_reboot_warn': (
        '⚠️ <b>Advertencia:</b> El servidor no estará disponible durante el reinicio (1-2 minutos).\n'
        'Se cerrarán todas las conexiones activas.'
    ),
    'srv.confirm_generic_title': '⚠️ <b>Confirmar operación</b>',
    'srv.confirm_generic_server': 'Servidor: <b>{name}</b>',
    'srv.confirm_generic_action': 'Operación: {action}',
    'srv.op_success_title': '✅ <b>Operación completada</b>',
    'srv.op_success_body': 'El servidor <b>{name}</b> se ha {action}.',
    'srv.op_success_hint': (
        'ℹ️ <i>Los cambios surten efecto en 30-60 segundos.\n'
        "Usa el botón 'Actualizar' para comprobar.</i>"
    ),
    'srv.op_error_title': '❌ <b>Falló: {action}</b>',
    'srv.op_error_body': 'No se pudo completar la operación para el servidor <b>{name}</b>.',
    'srv.op_error_details': '<b>Detalles:</b> {error}',
    'srv.op_error_retry': 'Inténtalo más tarde o contacta con el administrador.',
    # provider error details (localized exception text; full technical detail stays in logs)
    'error.invalid_token': 'Token de API de {provider} no válido — comprueba las credenciales en tu archivo .env.',
    'error.permission': 'Permisos insuficientes para la operación: {operation}.',
    'error.not_found': '{resource_type} con ID «{resource_id}» no encontrado.',
    'error.rate_limit': 'Límite de solicitudes de la API de {provider} superado — inténtalo de nuevo en breve.',
    'error.server_side': 'Error de la API de {provider} del lado del proveedor — un problema temporal, inténtalo más tarde.',
    'error.conflict': 'No se puede ejecutar «{operation}»: el servidor está en estado «{state}».',
    'error.locked': 'El servidor {resource_id} está ocupado — hay otra operación en curso.',
    'error.provider_api': 'Error de comunicación con la API de {provider} — un problema temporal, inténtalo más tarde.',
    # action
    'action.start.done': 'iniciado',
    'action.stop.done': 'detenido',
    'action.reboot.done': 'reiniciado',
    'action.shutdown.done': 'apagado',
    'action.generic.done': 'procesado',
    'action.start.err': 'Inicio',
    'action.stop.err': 'Detención',
    'action.reboot.err': 'Reinicio',
    'action.shutdown.err': 'Apagado',
    'action.generic.err': 'Operación',
    # srv
    'srv.provider_unavailable': '❌ El proveedor {provider} no está disponible',
    'srv.no_servers_for_provider': '❌ No se encontraron servidores para {provider}',
    'srv.loading_data': '⏳ Obteniendo datos...',
    'srv.starting': '⏳ Iniciando el servidor...',
    'srv.stopping': '⏳ Deteniendo el servidor...',
    'srv.rebooting': '⏳ Reiniciando el servidor...',
    'srv.shutting_down': '⏳ Apagando el servidor (ACPI)...',
    'srv.performing_operation': '⏳ Ejecutando la operación...',
    'srv.operation_cancelled': '❌ Operación cancelada',
    'srv.refreshing_data': '⏳ Actualizando datos...',
    # bal
    'bal.provider_not_found': '❌ <b>Proveedor no encontrado</b>',
    'bal.error_empty_data': 'Error: datos vacíos',
    'bal.error_data_format': 'Error: formato de datos',
    'bal.error_unknown_command': 'Error: comando desconocido',
    'bal.main_title': '💰 <b>Saldos de los proveedores en la nube</b>',
    'bal.no_providers': '❌ <i>No hay proveedores disponibles</i>',
    'bal.add_api_keys': '💡 Añade claves de API al archivo .env',
    'bal.available_funds': '📊 <b>Fondos disponibles:</b>',
    'bal.postpaid_suffix': '(pospago)',
    'bal.monthly_expenses': '📉 <b>Gastos del mes actual:</b>',
    'bal.unavailable': '⚠️ <b>No disponible:</b>',
    'bal.no_api_suffix': '(sin API)',
    'bal.choose_provider': '💡 Elige un proveedor para ver los detalles',
    'bal.history_title_provider': '📊 <b>Historial de saldo {emoji} {provider} ({period} días)</b>',
    'bal.history_title_all': '📊 <b>Historial de saldo ({period} días)</b>',
    'bal.history_insufficient': '❌ <i>No hay datos suficientes para este período</i>',
    'bal.history_wait': '💡 Espera unos días para acumular estadísticas.',
    'bal.history_only_provider': '💡 El historial muestra datos solo de {provider}',
    'bal.history_all_providers': '💡 El historial muestra datos de todos los proveedores',
    'bal.detail_unavailable': '⚠️ <b>Saldo no disponible vía API</b>',
    'bal.detail_no_api_body': '{provider} no ofrece una API para obtener información del saldo.',
    'bal.detail_check_manually': '💡 Comprueba el saldo manualmente en el panel del proveedor.',
    'bal.detail_postpaid_costs': '💵 <b>Costos del mes actual:</b> ${value:.2f}',
    'bal.detail_postpaid_hint': '💡 <i>AWS usa facturación pospago — la factura se emite a fin de mes</i>',
    'bal.detail_available_balance': '💰 <b>Saldo disponible:</b> ${value:.2f}',
    'bal.detail_account_balance': '   ├─ Saldo de la cuenta: ${value:.2f}',
    'bal.detail_pending': '   └─ Cargos pendientes: ${value:.2f}',
    'bal.detail_burn': '📉 <b>Gasto medio:</b> ${value:.2f}/día',
    'bal.detail_burn_monthly': '   └─ ~${value:.2f}/mes',
    'bal.detail_burn_insufficient': '📉 <b>Gasto medio:</b> datos insuficientes',
    'bal.detail_burn_insufficient_hint': '   └─ <i>(mín. 2 comprobaciones en 12 horas)</i>',
    'bal.detail_forecast_period': '   └─ ~{period}',
    'bal.detail_forecast_depleted': '⏳ <b>Previsión:</b> saldo agotado',
    'bal.detail_forecast_none': '⏳ <b>Previsión:</b> —',
    'bal.detail_trend_label': '<b>Tendencia:</b>',
    'bal.detail_last_deposit': '📅 <b>Último depósito:</b>',
    'bal.detail_deposit_date': '   • Fecha: {date} UTC',
    'bal.detail_deposit_amount': '   • Importe: ${value:.2f}',
    'bal.detail_last_check': '⏰ <b>Última comprobación:</b> {timestamp}',
    # trend
    'trend.increasing': 'al alza',
    'trend.decreasing': 'a la baja',
    'trend.stable': 'estable',
    'trend.unknown': 'desconocida',
    # period
    'period.years_months': '{years}a {months}m',
    'period.years': '{years}a',
    'period.months': '{months}m',
    # settings
    'settings.title': '⚙️ <b>Ajustes</b>',
    'settings.language_current': '🌐 <b>Idioma:</b> {current}',
    'settings.choose_section': 'Elige una sección:',
    'settings.section_language': '🌐 Idioma',
    'settings.section_language_desc': 'idioma de la interfaz y las notificaciones',
    'settings.language_changed': '✅ Idioma cambiado a Español',
    'settings.language_not_saved': '⚠️ Idioma cambiado para esta sesión, pero no se pudo guardar (podría restablecerse tras un reinicio).',
    'settings.menu_updated': '🌐 El menú se ha actualizado.',
    'settings.section_balance': '💵 Alertas de saldo',
    'settings.section_balance_desc': 'umbral de aviso de saldo bajo',
    'settings.balance_status_on': '🔔 <b>Alertas de saldo:</b> Activadas',
    'settings.balance_status_off': '🔕 <b>Alertas de saldo:</b> Desactivadas',
    'settings.balance_threshold_current': '💵 <b>Umbral:</b> ${value:.2f}',
    'settings.balance_threshold_hint': '<i>Se envía un aviso cuando el saldo de un proveedor cae por debajo de este valor.</i>',
    'settings.balance_choose': 'Elige un preajuste o define tu propio valor:',
    'settings.balance_btn_on': '🔔 Activar',
    'settings.balance_btn_off': '🔕 Desactivar',
    'settings.balance_btn_custom': '✏️ Valor personalizado',
    'settings.balance_prompt_title': '✏️ <b>Umbral personalizado</b>',
    'settings.balance_prompt_body': 'Envía el nuevo umbral en USD como número (por ejemplo, <code>500</code>).',
    'settings.balance_invalid': '❌ No es un importe válido. Envía un número positivo como <code>500</code>, o pulsa Cancelar.',
    'settings.balance_enabled_toast': '🔔 Alertas de saldo activadas',
    'settings.balance_disabled_toast': '🔕 Alertas de saldo desactivadas',
    'settings.balance_threshold_set_toast': '✅ Umbral fijado en ${value:.2f}',
    'settings.balance_not_saved_toast': '⚠️ Aplicado por ahora, pero no se pudo guardar (podría restablecerse tras un reinicio).',
    'settings.balance_not_saved_notice': '⚠️ Aplicado por ahora, pero no se pudo guardar (podría restablecerse tras un reinicio).',
    'settings.balance_cancelled': '✖️ Entrada cancelada.',
    # admin
    'admin.denied_message': (
        '⛔️ <b>Acceso denegado</b>\n'
        '\n'
        'Este bot está disponible solo para administradores.'
    ),
    'admin.denied_short': '⛔️ Acceso denegado',
    # cmd
    'cmd.start_desc': 'Iniciar el bot',
    'cmd.language_desc': 'Cambiar idioma',
    # notif
    'notif.server_down.title': '🔴 <b>Servidor no disponible</b>',
    'notif.server_down.body': 'El servidor <b>{name}</b> ({ip}) dejó de responder al ping.',
    'notif.error_label': '<b>Error:</b> {error}',
    'notif.server_up.title': '🟢 <b>Servidor recuperado</b>',
    'notif.server_up.body': 'El servidor <b>{name}</b> ({ip}) vuelve a estar accesible.',
    'notif.response_time_label': '<b>Tiempo de respuesta:</b> {ms} ms',
    'notif.low_balance.title': '🔴 <b>Saldo bajo {provider}</b>',
    'notif.low_balance.body': 'El saldo actual <b>${balance:.2f}</b> está por debajo del umbral <b>${threshold:.2f}</b>.',
    'notif.low_balance.depleted': '⚠️ <b>¡Saldo agotado!</b>',
    'notif.low_balance.top_up': '💡 Recarga tu saldo en el panel de {provider}.',
    'notif.low_balance.settings_hint': 'ℹ️ <i>Cambia el umbral o desactiva los avisos en Ajustes → Alertas de saldo.</i>',
    'notif.critical.title': '🔴 <b>Error crítico: {error_type}</b>',
    'notif.critical.check_logs': '⚠️ Revisa los registros de la aplicación para más información.',
    'notif.provider_outage.title': '⚠️ <b>Proveedor no disponible: {provider}</b>',
    'notif.provider_outage.body': 'Sin respuesta durante {duration} ({checks}).',
    'notif.provider_outage.last_error': '<b>Último error:</b> {error}',
    'notif.provider_outage.footer': 'Parece un problema temporal del lado del proveedor. Te avisaré cuando se recupere.',
    # outage
    'outage.duration_hours': '~{hours:.1f} h',
    'outage.duration_minutes': '~{minutes} min',
    # notif
    'notif.provider_recovered.title': '✅ <b>Proveedor recuperado: {provider}</b>',
    'notif.provider_recovered.body': 'Disponible de nuevo. Estuvo caído durante {duration}.',
    'notif.server_added.title': '🟢 <b>Nuevo servidor detectado</b>',
    'notif.server_added.body': 'Se encontró un nuevo servidor <b>{name}</b> ({ip}) en el proveedor <b>{provider}</b>.',
    'notif.server_added.region': '<b>Región:</b> {region}',
    'notif.server_added.monitoring_started': '✅ El monitoreo se inició automáticamente.',
    'notif.server_removed.title': '🔴 <b>Servidor eliminado</b>',
    'notif.server_removed.body': (
        'El servidor <b>{name}</b> ({ip}) ya no existe en el proveedor <b>{provider}</b>.\n'
        '\n'
        '⛔ Monitoreo detenido.\n'
        '🗑️ Estadísticas eliminadas.'
    ),
    # alert
    'alert.provider_api.title': 'API de {provider}',
    'alert.providers_unavailable.title': 'Proveedores no disponibles',
    'alert.providers_unavailable.body': (
        '¡Todos los proveedores en la nube no están disponibles!\n'
        '\n'
        'Proveedores: {providers}\n'
        '\n'
        'Comprueba:\n'
        '- Las claves de API en el archivo .env\n'
        '- La conexión a Internet\n'
        '- El estado de la API del proveedor'
    ),
    'alert.servers_fetch_failed.body': 'No se pudo obtener la lista de servidores: {error}',
    'alert.worker_abandoned.title': 'Monitoreo del servidor detenido',
    'alert.worker_abandoned.body': 'El proceso de monitoreo del servidor {label} falló repetidamente y se detuvo. El servidor no se monitorea temporalmente — se reintentará automáticamente más tarde. Revisa el servidor y la red.',
    'alert.core_unavailable.title': 'Núcleo de monitoreo no disponible',
    'alert.core_unavailable.body': 'El proceso Manager (que almacena los estados de los servidores) no responde. Las actualizaciones de estado y parte del monitoreo no funcionan. Probablemente sea necesario reiniciar el bot.',
    'alert.monitoring_stopped.title': 'Monitoreo completamente detenido',
    'alert.queue_overflow.title': 'La cola de resultados se está desbordando',
    'alert.queue_overflow.body': 'La cola de resultados de ping ha estado ~{ratio:.0f}% llena durante varias comprobaciones seguidas — el procesador de resultados parece colgado o caído. Pueden perderse estadísticas y notificaciones.',
    'alert.db_failure.title': 'Error de escritura de estadísticas',
    'alert.db_failure.body': 'La escritura de estadísticas de ping en la base de datos sigue fallando (errores repetidos). Se descartaron ~{dropped} registros para evitar agotar la memoria. El monitoreo y las notificaciones funcionan, pero se están perdiendo estadísticas. Revisa el espacio en disco y la base de datos.',
    'alert.task_gaveup.body': 'La tarea en segundo plano «{name}» finalizó inesperadamente varias veces ({restarts} reinicios seguidos) y ya NO se reinicia. Se requiere intervención — reinicia el bot.',
    'alert.task_exited.body': 'La tarea en segundo plano «{name}» finalizó inesperadamente sin error (debe ejecutarse de forma continua) y se reinició.',
    'alert.task_crashed.body': 'La tarea en segundo plano «{name}» falló y se reinició.',
    'alert.task_error_label': 'Error: {error}',
    'alert.task_event.type': 'Tarea en segundo plano: {name}',
    'alert.task_stalled.title': 'Tarea en segundo plano estancada: {name}',
    'alert.task_stalled.body': 'La tarea en segundo plano «{name}» no muestra progreso desde hace ~{minutes} min (se ejecuta pero parece atascada). Reiniciar automáticamente una tarea estancada no es fiable — probablemente sea necesario reiniciar el bot. Revisa los registros.',
}


PLURALS: dict[str, list[str]] = {
    # srv
    'srv.cooldown_wait': [
        '⚠️ Espera {n} segundo más antes de la próxima operación',
        '⚠️ Espera {n} segundos más antes de la próxima operación',
    ],
    # bal
    'bal.forecast_days': [
        '⏳ <b>Previsión:</b> ~{n} día',
        '⏳ <b>Previsión:</b> ~{n} días',
    ],
    'bal.history_more': [
        '<i>... y {n} registro más</i>',
        '<i>... y {n} registros más</i>',
    ],
    # notif
    'notif.low_balance.forecast': [
        '⏳ <b>Previsión:</b> ~{n} día hasta agotarse',
        '⏳ <b>Previsión:</b> ~{n} días hasta agotarse',
    ],
    # plural
    'plural.checks_in_row': [
        '{n} comprobación seguida',
        '{n} comprobaciones seguidas',
    ],
    # alert
    'alert.no_servers_monitored.body': [
        '{n} servidor no se está monitoreando (sin procesos activos) durante varias comprobaciones seguidas. Revisa el bot y los registros.',
        '{n} servidores no se están monitoreando (sin procesos activos) durante varias comprobaciones seguidas. Revisa el bot y los registros.',
    ],
}
