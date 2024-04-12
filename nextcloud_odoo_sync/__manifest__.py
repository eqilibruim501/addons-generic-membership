# Copyright (c) 2023 iScale Solutions Inc.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
{
    "name": "Nextcloud-Odoo Sync",
    "version": "16.0.1.0.0",
    "category": "Others",
    "description": """Sync Nextcloud apps into Odoo""",
    "author": "iScale Solutions Inc.",
    "website": "http://iscale-solutions.com",
    "external_dependencies": {"python": ["caldav"]},
    "depends": ["base", "calendar", "resource", "contacts"],
    "maintainers": ["iscale-solutions"],
    "license": "AGPL-3",
    "data": [
        "data/res_groups_data.xml",
        "data/nc_sync_error_data.xml",
        "data/nc_event_status_data.xml",
        "data/nextcloud_odoo_sync_cron_data.xml",
        "data/nc_sync_log_capacity_cron_data.xml",
        "data/calendar_alarm_data.xml",
        "data/calendar_event_type_data.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "views/calendar_event_views.xml",
        "views/nc_sync_user_views.xml",
        "views/nc_sync_log_views.xml",
        "views/nc_sync_error_views.xml",
        "views/nc_calendar_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "wizards/run_sync_wizard_views.xml",
    ],
    "installable": True,
    "active": False,
    "auto_install": False,
    "application": True,
    "uninstall_hook": "uninstall_hook",
}
