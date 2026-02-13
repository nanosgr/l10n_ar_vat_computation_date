from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ar_vat_computation_date = fields.Date(
        string="VAT Computation Period",
        help="Date used to determine in which period the VAT credit will be computed. "
        "If the invoice date is within a locked tax period, this will be automatically "
        "set to the last day of the month following the lock date.",
        copy=False,
        compute="_compute_l10n_ar_vat_computation_date",
        store=True,
        readonly=False,
    )

    l10n_ar_vat_adjustment_move_id = fields.Many2one(
        "account.move",
        string="VAT Adjustment Entry",
        help="Journal entry created to adjust VAT credit from temporary to "
        "definitive account",
        copy=False,
        readonly=True,
        index=True,
    )

    l10n_ar_vat_source_invoice_id = fields.Many2one(
        "account.move",
        string="Source Invoice",
        help="Original purchase invoice that generated this VAT adjustment entry",
        copy=False,
        readonly=True,
        index=True,
    )

    l10n_ar_is_vat_adjustment = fields.Boolean(
        string="Is VAT Adjustment",
        compute="_compute_l10n_ar_is_vat_adjustment",
        store=True,
        help="Indicates if this entry is a VAT credit adjustment",
    )

    @api.depends("l10n_ar_vat_source_invoice_id")
    def _compute_l10n_ar_is_vat_adjustment(self):
        """Mark entries as VAT adjustments if they have a source invoice."""
        for move in self:
            move.l10n_ar_is_vat_adjustment = bool(move.l10n_ar_vat_source_invoice_id)

    def _is_ar_purchase_move(self):
        """Check if this is an Argentine purchase invoice."""
        self.ensure_one()
        return (
            self.move_type in ("in_invoice", "in_refund") and self.country_code == "AR"
        )

    @api.depends(
        "date",
        "move_type",
        "country_code",
        "company_id.fiscalyear_lock_date",
        "company_id.tax_lock_date",
    )
    def _compute_l10n_ar_vat_computation_date(self):
        """Compute the VAT computation date based on lock dates.

        Uses the most restrictive lock date that affects this purchase invoice
        to determine when the VAT credit should be computed.
        """
        for move in self:
            if (
                move.move_type not in ("in_invoice", "in_refund")
                or move.country_code != "AR"
                or not move.date
            ):
                move.l10n_ar_vat_computation_date = False
                continue

            # Check all lock dates that could affect this purchase invoice
            lock_dates = move.company_id._get_violated_lock_dates(
                move.date,
                has_tax=True,  # Purchase invoices affect tax reports
                journal=move.journal_id,
            )

            if not lock_dates:
                # No lock dates violated, use the invoice date
                move.l10n_ar_vat_computation_date = move.date
            else:
                # Use the last day of the month following the most restrictive lock date
                most_restrictive_lock_date = lock_dates[-1][
                    0
                ]  # Last one is most recent
                move.l10n_ar_vat_computation_date = (
                    most_restrictive_lock_date + relativedelta(months=1)
                )

    def _check_fiscal_lock_dates(self):
        """Override to skip check for Argentine purchase invoices.

        For Argentine purchase invoices, we skip the fiscal lock date check on the
        accounting date (date field), as we use l10n_ar_vat_computation_date for
        tax reporting instead. The tax lock date will be checked against
        l10n_ar_vat_computation_date in _check_tax_lock_date on the move lines.
        """
        # Filter out Argentine purchase invoices from the check
        moves_to_check = self.filtered(lambda m: not m._is_ar_purchase_move())

        # Only check non-Argentine purchase invoices
        if moves_to_check:
            return super(AccountMove, moves_to_check)._check_fiscal_lock_dates()

        return True

    def _get_violated_lock_dates(self, invoice_date, has_tax):
        """Override to prevent lock date violations for Argentine purchase invoices.

        For Argentine purchase invoices, we don't consider lock dates when checking
        the accounting date (date field), because we want to keep the original
        invoice date. The lock dates are checked against l10n_ar_vat_computation_date
        instead.
        """
        self.ensure_one()
        # For Argentine purchase invoices, return empty to avoid date adjustment
        if self._is_ar_purchase_move():
            return []
        # For other moves, use standard behavior
        return super()._get_violated_lock_dates(invoice_date, has_tax)

    def _get_accounting_date(self, invoice_date, has_tax, lock_dates=None):
        """Override to keep original date for Argentine purchase invoices.

        For Argentine purchase invoices, we want to keep the invoice_date as the
        accounting date, even if it's in a locked period. The VAT computation
        will use l10n_ar_vat_computation_date instead.
        """
        self.ensure_one()
        # For Argentine purchase invoices, always return the invoice date unchanged
        if self._is_ar_purchase_move():
            return invoice_date
        # For other moves, use standard behavior
        return super()._get_accounting_date(
            invoice_date, has_tax, lock_dates=lock_dates
        )

    def _post(self, soft=True):
        """Override to replace VAT accounts in invoices posted in locked periods."""
        # Identify AR purchase invoices with deferred VAT computation
        ar_purchase_deferred = self.filtered(
            lambda m: m._is_ar_purchase_move()
            and m.l10n_ar_vat_computation_date
            and m.l10n_ar_vat_computation_date != m.date
        )

        # Replace VAT accounts before posting
        for move in ar_purchase_deferred:
            company = move.company_id

            # Validate configuration
            if (
                not company.l10n_ar_vat_credit_account_id
                or not company.l10n_ar_vat_credit_to_compute_account_id
            ):
                raise UserError(
                    _(
                        "Please configure VAT credit accounts for company "
                        "%(company)s in Accounting > Configuration > Settings > "
                        "Argentina",
                        company=company.name,
                    )
                )

            # Find and replace VAT credit account lines
            vat_credit_account = company.l10n_ar_vat_credit_account_id
            vat_lines = move.line_ids.filtered(
                lambda line, acc=vat_credit_account: line.account_id == acc
            )

            if vat_lines:
                vat_lines.write(
                    {"account_id": company.l10n_ar_vat_credit_to_compute_account_id.id}
                )

        # Continue with normal posting
        res = super()._post(soft=soft)

        # Create adjustment entries after posting
        ar_purchase_deferred._create_vat_adjustment_entries()

        return res

    def _create_vat_adjustment_entries(self):
        """Create adjustment journal entries for deferred VAT credit."""
        for move in self:
            company = move.company_id

            # Find the VAT adjustment journal
            adjustment_journal = self.env["account.journal"].search(
                [
                    ("company_id", "=", company.id),
                    ("type", "=", "general"),
                    ("code", "=", "AJIVA"),
                ],
                limit=1,
            )

            if not adjustment_journal:
                raise UserError(
                    _(
                        "VAT Adjustment Journal (AJIVA) not found for company "
                        "%(company)s. Please create it manually.",
                        company=company.name,
                    )
                )

            # Calculate total VAT amount deferred
            vat_to_compute_account = company.l10n_ar_vat_credit_to_compute_account_id
            vat_debit = sum(
                move.line_ids.filtered(
                    lambda line, acc=vat_to_compute_account: line.account_id == acc
                ).mapped("debit")
            )
            vat_credit = sum(
                move.line_ids.filtered(
                    lambda line, acc=vat_to_compute_account: line.account_id == acc
                ).mapped("credit")
            )
            vat_amount = vat_debit - vat_credit

            # Skip if no VAT amount
            if not vat_amount:
                continue

            # Create the adjustment entry
            adjustment_move = self.env["account.move"].create(
                {
                    "move_type": "entry",
                    "date": move.l10n_ar_vat_computation_date,
                    "journal_id": adjustment_journal.id,
                    "ref": _("VAT Adjustment - %(move)s", move=move.name),
                    "line_ids": [
                        # Debit: IVA Crédito Fiscal (definitive account)
                        (
                            0,
                            0,
                            {
                                "account_id": company.l10n_ar_vat_credit_account_id.id,
                                "debit": vat_amount,
                                "credit": 0.0,
                                "name": _(
                                    "VAT credit computation - %(move)s", move=move.name
                                ),
                            },
                        ),
                        # Credit: IVA Crédito Fiscal a Computar (temporary account)
                        (
                            0,
                            0,
                            {
                                "account_id": vat_to_compute_account.id,
                                "debit": 0.0,
                                "credit": vat_amount,
                                "name": _(
                                    "VAT credit computation - %(move)s", move=move.name
                                ),
                            },
                        ),
                    ],
                }
            )

            # Post the adjustment entry
            adjustment_move.action_post()

            # Create bidirectional relationship
            adjustment_move.l10n_ar_vat_source_invoice_id = move.id
            move.l10n_ar_vat_adjustment_move_id = adjustment_move.id

    def action_view_vat_adjustment(self):
        """Open the VAT adjustment entry related to this invoice."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.l10n_ar_vat_adjustment_move_id.id,
            "target": "current",
        }

    def action_view_source_invoice(self):
        """Open the source invoice that generated this VAT adjustment."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.l10n_ar_vat_source_invoice_id.id,
            "target": "current",
        }
