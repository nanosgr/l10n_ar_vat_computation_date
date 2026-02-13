from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_vat_credit_account_id = fields.Many2one(
        "account.account",
        string="VAT Credit Account",
        help="Account used for VAT credit in purchase invoices. "
        "This account will be replaced when invoices fall in locked periods.",
        domain="[('company_id', '=', id), ('account_type', '=', 'asset_current')]",
    )

    l10n_ar_vat_credit_to_compute_account_id = fields.Many2one(
        "account.account",
        string="VAT Credit To Compute Account",
        help="Temporary account for VAT credit to be computed in future periods. "
        "Used when purchase invoices are posted in locked tax periods.",
        domain="[('company_id', '=', id), ('account_type', '=', 'asset_current')]",
    )

    @api.constrains(
        "l10n_ar_vat_credit_account_id", "l10n_ar_vat_credit_to_compute_account_id"
    )
    def _check_l10n_ar_vat_accounts(self):
        """Validate VAT account configuration."""
        for company in self:
            # Skip if not configured
            if (
                not company.l10n_ar_vat_credit_account_id
                or not company.l10n_ar_vat_credit_to_compute_account_id
            ):
                continue

            # Cannot be the same account
            if (
                company.l10n_ar_vat_credit_account_id
                == company.l10n_ar_vat_credit_to_compute_account_id
            ):
                raise ValidationError(_("VAT credit accounts must be different"))

            # Both must be current assets
            for account in [
                company.l10n_ar_vat_credit_account_id,
                company.l10n_ar_vat_credit_to_compute_account_id,
            ]:
                if account.account_type != "asset_current":
                    raise ValidationError(
                        _("Account {} must be of type Current Assets").format(
                            account.code
                        )
                    )
