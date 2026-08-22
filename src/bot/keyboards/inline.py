"""Compatibility facade for inline keyboard builders."""

from .inline_balance import (
    get_balance_history_keyboard as get_balance_history_keyboard,
    get_balance_main_keyboard as get_balance_main_keyboard,
    get_balance_provider_keyboard as get_balance_provider_keyboard,
    get_provider_selection_keyboard as get_provider_selection_keyboard,
)
from .inline_checks import (
    _check_button_label as _check_button_label,
    get_check_delete_confirm_keyboard as get_check_delete_confirm_keyboard,
    get_check_detail_keyboard as get_check_detail_keyboard,
    get_check_input_cancel_keyboard as get_check_input_cancel_keyboard,
    get_check_type_keyboard as get_check_type_keyboard,
    get_checks_list_keyboard as get_checks_list_keyboard,
)
from .inline_common import (
    _nav_row as _nav_row,
    _paginate as _paginate,
    _server_button_rows as _server_button_rows,
)
from .inline_servers import (
    get_confirmation_keyboard as get_confirmation_keyboard,
    get_monitoring_keyboard as get_monitoring_keyboard,
    get_server_control_keyboard as get_server_control_keyboard,
    get_server_details_keyboard as get_server_details_keyboard,
    get_server_stats_keyboard as get_server_stats_keyboard,
    get_servers_management_keyboard as get_servers_management_keyboard,
)
from .inline_settings import (
    BALANCE_THRESHOLD_PRESETS as BALANCE_THRESHOLD_PRESETS,
    SETTINGS_SECTIONS as SETTINGS_SECTIONS,
    get_balance_alerts_keyboard as get_balance_alerts_keyboard,
    get_balance_threshold_cancel_keyboard as get_balance_threshold_cancel_keyboard,
    get_language_keyboard as get_language_keyboard,
    get_settings_menu_keyboard as get_settings_menu_keyboard,
)
