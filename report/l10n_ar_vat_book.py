from odoo import api, models
from odoo.tools import SQL


class ArgentinianReportCustomHandler(models.AbstractModel):
    _inherit = "l10n_ar.tax.report.handler"

    def _custom_options_initializer(self, report, options, previous_options):
        """Store original date range for later use."""
        result = super()._custom_options_initializer(
            report, options, previous_options=previous_options
        )

        # Store original dates before they get modified
        if "date" in options:
            options["_original_date_from"] = options["date"].get("date_from")
            options["_original_date_to"] = options["date"].get("date_to")

        return result

    def _build_query(self, report, options, column_group_key) -> SQL:
        """Override to use vat_computation_date for AR purchases.

        We modify the WHERE clause before building the query to use
        l10n_ar_vat_computation_date for AR purchase invoices.
        """
        selected_types = self._vat_book_get_selected_tax_types(options)

        # If purchases are NOT selected, use standard behavior
        if "purchase" not in selected_types:
            return super()._build_query(report, options, column_group_key)

        # Get original date range
        date_from = options.get("_original_date_from") or options.get("date", {}).get(
            "date_from"
        )
        date_to = options.get("_original_date_to") or options.get("date", {}).get(
            "date_to"
        )

        # Temporarily modify options to get a query without restrictive date filters
        # We'll add our own date filters that consider vat_computation_date
        modified_options = options.copy()
        modified_options["date"] = {
            "date_from": "2000-01-01",  # Very wide range
            "date_to": "2099-12-31",
            "mode": options.get("date", {}).get("mode", "range"),
            "filter": options.get("date", {}).get("filter", "custom"),
        }

        # Get the base query object without restrictive date filters
        query = report._get_report_query(modified_options, "strict_range")

        # Build our own date filtering conditions that use vat_computation_date
        date_conditions = []

        if date_from:
            date_conditions.append(
                SQL(
                    """COALESCE(
                        account_move.l10n_ar_vat_computation_date,
                        account_move.date
                    ) >= %s""",
                    date_from,
                )
            )

        if date_to:
            date_conditions.append(
                SQL(
                    """COALESCE(
                        account_move.l10n_ar_vat_computation_date,
                        account_move.date
                    ) <= %s""",
                    date_to,
                )
            )

        # Combine original WHERE clause with our date conditions
        if date_conditions:
            enhanced_where = SQL(
                "%s AND %s", query.where_clause, SQL(" AND ").join(date_conditions)
            )
        else:
            enhanced_where = query.where_clause

        tax_types = tuple(selected_types)

        # Build the final query using our enhanced WHERE clause
        return self.env["account.ar.vat.line"]._ar_vat_line_build_query(
            query.from_clause, enhanced_where, column_group_key, tax_types
        )

    @api.model
    def _vat_book_get_lines_domain(self, options):
        """Override to filter purchase invoices by l10n_ar_vat_computation_date.

        For Argentine purchase invoices, we use l10n_ar_vat_computation_date to
        determine in which period the VAT credit should be computed. This allows
        invoices with accounting dates in locked periods to be reported in the
        correct VAT period.

        IMPORTANT: This domain is used on account.move, so fields are direct
        (no move_id. prefix needed).
        """
        # Get basic domain without date filters (we'll add custom date logic)
        company_ids = self.env.company.ids
        selected_types = self._vat_book_get_selected_tax_types(options)

        # Build base domain (same as parent but without date filters)
        domain = [
            ("journal_id.type", "in", selected_types),
            ("journal_id.l10n_latam_use_documents", "=", True),
            ("company_id", "in", company_ids),
        ]

        # Add state filter
        state = options.get("all_entries") and "all" or "posted"
        if state and state.lower() != "all":
            domain += [("state", "=", state)]

        # Get date range
        date_from = options.get("date", {}).get("date_from")
        date_to = options.get("date", {}).get("date_to")

        # Add custom date filters based on invoice type
        if "purchase" in selected_types and "sale" in selected_types:
            # Both purchases and sales: complex domain
            date_domain = self._build_mixed_date_domain(date_from, date_to)
        elif "purchase" in selected_types:
            # Only purchases: use vat_computation_date for AR, date for others
            date_domain = self._build_purchase_date_domain(date_from, date_to)
        else:
            # Only sales or other: standard date filters
            date_domain = self._build_standard_date_domain(date_from, date_to)

        domain.extend(date_domain)
        return domain

    @api.model
    def _vat_simple_get_lines_domain(self, options):
        """Override to filter purchase invoices by l10n_ar_vat_computation_date.

        This method is used by the VAT Simple export (CSV files for AFIP).
        For Argentine purchase invoices, we use l10n_ar_vat_computation_date to
        determine in which period the VAT credit should be computed.

        IMPORTANT: This domain is used on account.move, so fields are direct
        (no move_id. prefix needed).
        """
        import logging

        _logger = logging.getLogger(__name__)

        company_ids = self.env.company.ids
        domain = [
            ("state", "=", "posted"),
            ("journal_id.l10n_latam_use_documents", "=", True),
            ("company_id", "in", company_ids),
        ]

        # Get date range
        date_from = options.get("date", {}).get("date_from")
        date_to = options.get("date", {}).get("date_to")

        _logger.warning("=== VAT SIMPLE DOMAIN DEBUG ===")
        _logger.warning(f"Date range: {date_from} to {date_to}")

        # Add date filters using vat_computation_date for AR purchases
        if date_from:
            domain.extend(
                [
                    "|",
                    # AR purchase with vat_computation_date
                    "&",
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("country_code", "=", "AR"),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", ">=", date_from),
                    # All other invoices (NOT(AR purchase with vat_computation_date))
                    "&",
                    "|",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("country_code", "!=", "AR"),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", ">=", date_from),
                ]
            )

        if date_to:
            domain.extend(
                [
                    "|",
                    # AR purchase with vat_computation_date
                    "&",
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("country_code", "=", "AR"),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", "<=", date_to),
                    # All other invoices (NOT(AR purchase with vat_computation_date))
                    "&",
                    "|",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("country_code", "!=", "AR"),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", "<=", date_to),
                ]
            )

        _logger.warning(f"Final domain: {domain}")

        # Test the domain to see what moves it finds
        test_moves = self.env["account.move"].search(domain)
        _logger.warning(f"Moves found: {len(test_moves)} - IDs: {test_moves.ids[:10]}")
        for move in test_moves[:5]:
            _logger.warning(
                f"  Move: {move.name} | date={move.date} | "
                f"vat_comp={move.l10n_ar_vat_computation_date} | "
                f"type={move.move_type}"
            )

        return domain

    def _vat_simple_get_csv_move_ids(self, options, file_type):
        """Override to add logging and proper ordering for AR purchases.

        For AR purchase invoices, we should consider vat_computation_date
        for ordering, not just invoice_date.
        """
        import logging

        _logger = logging.getLogger(__name__)

        # Call parent to get the domain and search
        result = super()._vat_simple_get_csv_move_ids(options, file_type)

        _logger.warning("=== VAT SIMPLE CSV MOVE IDS DEBUG ===")
        _logger.warning(f"File type: {file_type}")
        _logger.warning(f"Move IDs found: {result}")

        # Show details of the moves found
        if result:
            moves = self.env["account.move"].browse(result)
            for move in moves[:10]:
                _logger.warning(
                    f"  Move: {move.name} | date={move.date} | "
                    f"invoice_date={move.invoice_date} | "
                    f"vat_comp={move.l10n_ar_vat_computation_date} | "
                    f"doc_type={move.l10n_latam_document_type_id.code}"
                )

        return result

    def _vat_simple_build_purchase_query(self, file_type, move_ids):
        """Override to add logging for purchase query debugging."""
        import logging

        _logger = logging.getLogger(__name__)

        _logger.warning("=== VAT SIMPLE BUILD PURCHASE QUERY DEBUG ===")
        _logger.warning(f"File type: {file_type}")
        _logger.warning(f"Move IDs received: {move_ids}")

        # Call parent
        result = super()._vat_simple_build_purchase_query(file_type, move_ids)

        _logger.warning(f"Query returned {len(result)} rows")
        for i, row in enumerate(result[:5]):
            _logger.warning(
                f"  Row {i+1}: concept={row.get('concept')}, "
                f"rate_code={row.get('rate_code')}, "
                f"balance={row.get('balance')}"
            )

        return result

    def _build_standard_date_domain(self, date_from, date_to):
        """Build standard date domain using 'date' field."""
        domain = []
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        return domain

    def _build_purchase_date_domain(self, date_from, date_to):
        """Build date domain for purchases only, using vat_computation_date.

        Note: Uses company's country instead of country_code which doesn't
        exist in Odoo 18.
        """
        domain = []

        if date_from:
            domain.extend(
                [
                    "|",
                    # AR purchase with vat_computation_date
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", ">=", date_from),
                    # Other invoices or without vat_computation_date
                    "&",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", ">=", date_from),
                ]
            )

        if date_to:
            domain.extend(
                [
                    "|",
                    # AR purchase with vat_computation_date
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", "<=", date_to),
                    # Other invoices or without vat_computation_date
                    "&",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", "<=", date_to),
                ]
            )

        return domain

    def _build_mixed_date_domain(self, date_from, date_to):
        """Build date domain for both purchases and sales.

        Logic:
        - AR purchase invoices with vat_computation_date: filter by
          vat_computation_date
        - All others: filter by date

        Note: We check for l10n_ar_vat_computation_date presence to identify
        AR purchases since country_code doesn't exist in Odoo 18.
        """
        domain = []

        if date_from:
            domain.extend(
                [
                    "|",
                    # AR purchase invoices with vat_computation_date
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", ">=", date_from),
                    # All other invoices
                    "&",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", ">=", date_from),
                ]
            )

        if date_to:
            domain.extend(
                [
                    "|",
                    # AR purchase invoices with vat_computation_date
                    "&",
                    "&",
                    ("move_type", "in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "!=", False),
                    ("l10n_ar_vat_computation_date", "<=", date_to),
                    # All other invoices
                    "&",
                    "|",
                    ("move_type", "not in", ["in_invoice", "in_refund"]),
                    ("l10n_ar_vat_computation_date", "=", False),
                    ("date", "<=", date_to),
                ]
            )

        return domain
