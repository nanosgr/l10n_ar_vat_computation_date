from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ar_vat_credit_account_id = fields.Many2one(
        related="company_id.l10n_ar_vat_credit_account_id",
        readonly=False,
    )
    l10n_ar_vat_credit_to_compute_account_id = fields.Many2one(
        related="company_id.l10n_ar_vat_credit_to_compute_account_id",
        readonly=False,
    )
