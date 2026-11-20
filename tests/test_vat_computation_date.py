from datetime import date, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ar.tests.common import TestArCommon


@tagged("post_install", "-at_install")
class TestVatComputationDate(TestArCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_ri
        cls.env.user.company_id = cls.company
        cls.purchase_journal = cls.company_data["default_journal_purchase"]
        cls.tax_21 = cls.env["account.tax"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type_tax_use", "=", "purchase"),
                ("amount", "=", 21),
                ("amount_type", "=", "percent"),
            ],
            limit=1,
        )
        vat_account = cls.tax_21.invoice_repartition_line_ids.filtered(
            lambda rl: rl.repartition_type == "tax"
        ).account_id
        to_compute = cls.env["account.account"].create(
            {
                "name": "IVA Credito Fiscal a Computar",
                "code": "1.1.4.99.999",
                "account_type": "asset_current",
                "company_ids": [Command.link(cls.company.id)],
            }
        )
        cls.company.write(
            {
                "l10n_ar_vat_credit_account_id": vat_account.id,
                "l10n_ar_vat_credit_to_compute_account_id": to_compute.id,
            }
        )
        cls.env["account.journal"].create(
            {
                "name": "Ajustes IVA",
                "code": "AJIVA",
                "type": "general",
                "company_id": cls.company.id,
            }
        )
        cls._seq = 0

    def _bill(self, bill_date, post=True):
        type(self)._seq += 1
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.res_partner_adhoc.id,
                "journal_id": self.purchase_journal.id,
                "invoice_date": bill_date,
                "date": bill_date,
                "l10n_latam_document_type_id": self.env.ref("l10n_ar.dc_a_f").id,
                "l10n_latam_document_number": "00001-%08d" % self._seq,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Servicio",
                            "quantity": 1,
                            "price_unit": 1000,
                            "tax_ids": [Command.set(self.tax_21.ids)],
                        }
                    )
                ],
            }
        )
        if post:
            bill.action_post()
        return bill

    def test_open_period_uses_accounting_date(self):
        bill = self._bill(date(2026, 10, 15))
        self.assertEqual(bill.l10n_ar_vat_computation_date, date(2026, 10, 15))
        self.assertFalse(bill.l10n_ar_vat_adjustment_move_id)

    def test_locked_period_defers_to_end_of_next_month(self):
        self.company.tax_lock_date = date(2026, 9, 30)
        bill = self._bill(date(2026, 9, 10))
        self.assertEqual(bill.date, date(2026, 9, 10))
        self.assertEqual(bill.l10n_ar_vat_computation_date, date(2026, 10, 31))
        adj = bill.l10n_ar_vat_adjustment_move_id
        self.assertTrue(adj)
        self.assertEqual(adj.date, date(2026, 10, 31))

    def test_lock_date_changes_do_not_rewrite_posted_bills(self):
        old_open = self._bill(date(2026, 8, 20))
        self.company.tax_lock_date = date(2026, 8, 31)
        deferred = self._bill(date(2026, 8, 25))
        expected = {
            old_open: date(2026, 8, 20),
            deferred: date(2026, 9, 30),
        }
        for move, value in expected.items():
            self.assertEqual(move.l10n_ar_vat_computation_date, value)

        bills = old_open | deferred
        for vals in (
            {"tax_lock_date": date(2026, 10, 31)},  # raise the lock
            {"fiscalyear_lock_date": date(2026, 6, 30)},
            {"tax_lock_date": False, "fiscalyear_lock_date": False},  # lower it
            {"tax_lock_date": date(2026, 9, 30)},
        ):
            self.company.write(vals)
            self.env.flush_all()
            bills.invalidate_recordset(["l10n_ar_vat_computation_date"])
            for move, value in expected.items():
                self.assertEqual(
                    move.l10n_ar_vat_computation_date,
                    value,
                    "Lock date change %s rewrote %s" % (vals, move.name),
                )

    # ------------------------------------------------------------------
    # Closed fiscal years (fiscal year / hard lock dates) - 18.0.3.1.0
    # ------------------------------------------------------------------

    def _adjustment_count(self):
        return self.env["account.move"].search_count(
            [("company_id", "=", self.company.id), ("l10n_ar_is_vat_adjustment", "=", True)]
        )

    def test_fiscalyear_lock_blocks_posting(self):
        self.company.fiscalyear_lock_date = date(2025, 12, 31)
        bill = self._bill(date(2025, 6, 15), post=False)
        before = self._adjustment_count()
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            bill.action_post()
        self.assertEqual(bill.state, "draft")
        self.assertEqual(self._adjustment_count(), before)

    def test_fiscalyear_lock_blocks_reset_to_draft(self):
        bill = self._bill(date(2025, 6, 15))
        self.company.fiscalyear_lock_date = date(2025, 12, 31)
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            bill.button_draft()
        self.assertEqual(bill.state, "posted")

    def test_fiscalyear_lock_blocks_line_edit_and_unlink(self):
        bill = self._bill(date(2025, 6, 15))
        self.company.fiscalyear_lock_date = date(2025, 12, 31)
        product_line = bill.invoice_line_ids[:1]
        other_account = self.company_data["default_account_expense"].copy()
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            product_line.write({"account_id": other_account.id})
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            product_line.unlink()

    def test_hard_lock_blocks(self):
        bill = self._bill(date(2025, 6, 15))
        draft = self._bill(date(2025, 6, 20), post=False)
        draft.unlink()  # hard lock refuses to be set with unposted entries
        self.company.hard_lock_date = date(2025, 12, 31)
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            bill.button_draft()
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            bill.invoice_line_ids[:1].unlink()
        late = self._bill(date(2025, 7, 1), post=False)
        with self.assertRaisesRegex(UserError, "closed fiscal year"):
            late.action_post()

    def test_lock_exception_allows_posting(self):
        self.company.fiscalyear_lock_date = date(2025, 12, 31)
        self.env["account.lock_exception"].create(
            {
                "company_id": self.company.id,
                "user_id": self.env.user.id,
                "fiscalyear_lock_date": date(2025, 1, 1),
                "end_datetime": fields.Datetime.now() + timedelta(hours=24),
                "reason": "test_lock_exception_allows_posting",
            }
        )
        bill = self._bill(date(2025, 6, 15))
        self.assertEqual(bill.state, "posted")
        self.assertEqual(bill.date, date(2025, 6, 15))

    def test_purchase_and_tax_lock_still_defer(self):
        self.company.write(
            {
                "fiscalyear_lock_date": date(2025, 12, 31),
                "purchase_lock_date": date(2026, 9, 30),
                "tax_lock_date": date(2026, 9, 30),
            }
        )
        bill = self._bill(date(2026, 9, 10))
        self.assertEqual(bill.state, "posted")
        self.assertEqual(bill.date, date(2026, 9, 10))
        self.assertEqual(bill.l10n_ar_vat_computation_date, date(2026, 10, 31))
        self.assertEqual(bill.l10n_ar_vat_adjustment_move_id.date, date(2026, 10, 31))
