"""
View layer, split by what each group of screens is for. Everything is re-exported here
so `urls.py` keeps addressing them as `views.<name>`.
"""
from .home import (  # noqa: F401
    CaptchaLoginView, ForcedPasswordChangeView, dashboard, profile, settings,
)
from .master import (  # noqa: F401
    admin_required, district_delete, district_form, district_list, period_form,
    period_list, project_delete, project_form, project_list, project_parameter_delete,
    user_delete, user_form, user_list,
)
from .monthly import (  # noqa: F401
    mpr_entry_delete, mpr_entry_form, mpr_list, mpr_lock, mpr_month, mpr_parameters,
    mpr_report, mpr_unlock_request,
)
from .reporting import (  # noqa: F401
    monitor_required, report_export, report_status, report_table, report_unlock, reports,
)
from .security import security_export, security_log, security_unlock  # noqa: F401
