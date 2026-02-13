{
    "name": "Argentina - VAT Computation Date",
    "version": "18.0.2.0.0",
    "category": "Accounting/Localizations",
    "summary": "Compute VAT credit in a different period than accounting date",
    "author": "Vikingo Software",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar",
        "l10n_ar_reports",
        "l10n_ar_account_reports",
    ],
    "data": [
        "views/account_move_views.xml",
        "views/account_ar_vat_line_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
