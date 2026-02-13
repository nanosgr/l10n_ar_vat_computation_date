from odoo import models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _check_tax_lock_date(self):
        """Override to use l10n_ar_vat_computation_date for Argentine purchase invoices.

        For Argentine purchase invoices, we check the tax lock date against the
        l10n_ar_vat_computation_date instead of the regular date field. This allows
        the invoice to be posted with an accounting date in a locked period, while
        the VAT credit is computed in the current open period.
        """
        ar_purchase_lines = self.env["account.move.line"]
        other_lines = self.env["account.move.line"]

        for line in self:
            move = line.move_id
            if (
                move.move_type in ("in_invoice", "in_refund")
                and move.country_code == "AR"
                and move.l10n_ar_vat_computation_date
            ):
                ar_purchase_lines |= line
            else:
                other_lines |= line

        # Check Argentine purchase lines using l10n_ar_vat_computation_date
        for line in ar_purchase_lines:
            move = line.move_id
            if move.state != "posted":
                continue
            violated_lock_dates = move.company_id._get_lock_date_violations(
                move.l10n_ar_vat_computation_date,
                fiscalyear=False,
                sale=False,
                purchase=False,
                tax=True,
                hard=True,
            )
            if violated_lock_dates and line._affect_tax_report():
                raise UserError(
                    _(
                        "The operation is refused as it would impact an "
                        "already issued tax statement. Please change the VAT "
                        "computation date or the following lock dates to "
                        "proceed: %(lock_date_info)s.",
                        lock_date_info=self.env["res.company"]._format_lock_dates(
                            violated_lock_dates
                        ),
                    )
                )

        # Check other lines using the standard method
        if other_lines:
            return super(AccountMoveLine, other_lines)._check_tax_lock_date()

        return True
