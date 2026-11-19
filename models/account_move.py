from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ar_vat_computation_date = fields.Date(
        string="VAT Computation Period",
        help="Date used to determine in which period the VAT credit will be computed. "
        "It is set once, when the invoice is posted: if the accounting date is within "
        "a locked tax period, it is the last day of the month following the lock date; "
        "otherwise it is the accounting date. Later changes to the company lock dates "
        "do NOT modify it.",
        copy=False,
        readonly=True,
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

    def _l10n_ar_get_vat_computation_date(self):
        """Return the VAT computation date for an Argentine purchase invoice.

        Uses the most restrictive lock date currently violated by the accounting
        date: the VAT credit is deferred to the last day of the month following
        that lock date. Without violated lock dates, the accounting date is used.

        IMPORTANT: this is evaluated only when the invoice is posted (see
        ``_post``). The field used to be a stored compute depending on the
        company lock dates, so every lock date change rewrote the value of ALL
        the purchase invoices of the company, including periods already declared.
        """
        self.ensure_one()
        if not self._is_ar_purchase_move() or not self.date:
            return False
        lock_dates = self.company_id._get_violated_lock_dates(
            self.date,
            has_tax=True,  # Purchase invoices affect tax reports
            journal=self.journal_id,
        )
        if not lock_dates:
            return self.date
        most_restrictive_lock_date = lock_dates[-1][0]  # sorted chronologically
        return most_restrictive_lock_date + relativedelta(months=1, day=31)

    @api.onchange("date", "move_type", "journal_id")
    def _onchange_l10n_ar_vat_computation_date(self):
        """Preview the VAT computation date on draft invoices (set for real on post)."""
        for move in self.filtered(lambda m: m.state == "draft"):
            move.l10n_ar_vat_computation_date = move._l10n_ar_get_vat_computation_date()

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
        """Override to fix the VAT computation date and replace VAT accounts in
        invoices posted in locked periods."""
        # Fix the VAT computation date at posting time (it is never recomputed
        # afterwards). Invoices reset to draft that already have a posted VAT
        # adjustment entry keep their value, to stay aligned with that entry.
        for move in self.filtered(lambda m: m._is_ar_purchase_move()):
            if (
                move.l10n_ar_vat_computation_date
                and move.l10n_ar_vat_adjustment_move_id.state == "posted"
            ):
                continue
            new_date = move._l10n_ar_get_vat_computation_date()
            if move.l10n_ar_vat_computation_date != new_date:
                move.l10n_ar_vat_computation_date = new_date

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
                                "partner_id": move.partner_id.id,
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
                                "partner_id": move.partner_id.id,
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
