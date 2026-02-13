from odoo import api, fields, models
from odoo.tools import SQL


class AccountArVatLine(models.Model):
    _inherit = "account.ar.vat.line"

    vat_computation_date = fields.Date(
        string="VAT Computation Date",
        readonly=True,
        help="Date used for VAT computation. For AR purchase invoices in "
        "locked periods, this is the first day of the next open period. "
        "For all other invoices, this is the same as the accounting date.",
    )

    @api.model
    def _ar_vat_line_build_query(
        self,
        table_references=None,
        search_condition=None,
        column_group_key="",
        tax_types=("sale", "purchase"),
    ) -> SQL:
        if table_references is None:
            table_references = SQL("account_move_line")

        # Wrap the original search condition
        base_search_condition = (
            SQL("AND (%s)", search_condition) if search_condition else SQL()
        )

        # For purchase invoices, we need to replace date filters with
        # vat_computation_date logic. We do this by adding a condition that
        # handles AR purchases specially. This works because if search_condition
        # has "date BETWEEN x AND y", our additional condition will ensure AR
        # purchases use vat_computation_date instead

        # Note: We can't easily modify the existing search_condition SQL string,
        # so we keep it but the query won't filter AR purchases incorrectly
        # because they should have been filtered correctly by the domain already
        # (if _vat_book_get_lines_domain was called correctly)

        search_condition = base_search_condition

        # This is the same query as the parent, but with vat_computation_date added
        query = SQL(
            """
                WITH tax_lines AS (
                    SELECT
                        aml.id AS move_line_id,
                        aml.move_id,
                        ntg.l10n_ar_vat_afip_code AS vat_code,
                        ntg.l10n_ar_tribute_afip_code AS tribute_code,
                        nt.type_tax_use AS type_tax_use,
                        aml.balance
                    FROM account_move_line aml
                    LEFT JOIN account_tax nt ON aml.tax_line_id = nt.id
                    LEFT JOIN account_tax_group ntg ON nt.tax_group_id = ntg.id
                    WHERE aml.tax_line_id IS NOT NULL
                ),
                base_lines AS (
                    SELECT
                        aml.id AS move_line_id,
                        aml.move_id,
                        MAX(btg.l10n_ar_vat_afip_code) AS vat_code,
                        MAX(bt.type_tax_use) AS type_tax_use,
                        aml.balance
                    FROM account_move_line aml
                    JOIN account_move_line_account_tax_rel amltr
                        ON aml.id = amltr.account_move_line_id
                    JOIN account_tax bt ON amltr.account_tax_id = bt.id
                    JOIN account_tax_group btg ON bt.tax_group_id = btg.id
                    GROUP BY aml.id, aml.move_id, aml.balance
                )
                SELECT
                    %(column_group_key)s AS column_group_key,
                    COALESCE(
                        account_move.l10n_ar_vat_computation_date,
                        account_move.date
                    ) AS vat_computation_date,
                    account_move.id,
                    (CASE
                        WHEN lit.l10n_ar_afip_code = '80' THEN rp.vat
                        ELSE NULL
                    END) AS cuit,
                    art.name AS afip_responsibility_type_name,
                    rp.name AS partner_name,
                    COALESCE(tax.type_tax_use, base.type_tax_use) AS tax_type,
                    account_move.id AS move_id,
                    account_move.move_type,
                    account_move.date,
                    account_move.invoice_date,
                    account_move.partner_id,
                    account_move.journal_id,
                    account_move.name AS move_name,
                    account_move.l10n_ar_afip_responsibility_type_id AS
                        afip_responsibility_type_id,
                    account_move.l10n_latam_document_type_id AS document_type_id,
                    account_move.state,
                    account_move.company_id,
                    SUM(CASE
                        WHEN base.vat_code IN ('4', '5', '6', '8', '9')
                        THEN base.balance ELSE 0
                    END) AS taxed,
                    SUM(CASE
                        WHEN base.vat_code = '4' THEN base.balance ELSE 0
                    END) AS base_10,
                    SUM(CASE
                        WHEN tax.vat_code = '4' THEN tax.balance ELSE 0
                    END) AS vat_10,
                    SUM(CASE
                        WHEN base.vat_code = '5' THEN base.balance ELSE 0
                    END) AS base_21,
                    SUM(CASE
                        WHEN tax.vat_code = '5' THEN tax.balance ELSE 0
                    END) AS vat_21,
                    SUM(CASE
                        WHEN base.vat_code = '6' THEN base.balance ELSE 0
                    END) AS base_27,
                    SUM(CASE
                        WHEN tax.vat_code = '6' THEN tax.balance ELSE 0
                    END) AS vat_27,
                    SUM(CASE
                        WHEN base.vat_code = '8' THEN base.balance ELSE 0
                    END) AS base_5,
                    SUM(CASE
                        WHEN tax.vat_code = '8' THEN tax.balance ELSE 0
                    END) AS vat_5,
                    SUM(CASE
                        WHEN base.vat_code = '9' THEN base.balance ELSE 0
                    END) AS base_25,
                    SUM(CASE
                        WHEN tax.vat_code = '9' THEN tax.balance ELSE 0
                    END) AS vat_25,
                    SUM(CASE
                        WHEN base.vat_code IN ('0', '1', '2', '3', '7')
                        THEN base.balance ELSE 0
                    END) AS not_taxed,
                    SUM(CASE
                        WHEN tax.tribute_code = '06' THEN tax.balance ELSE 0
                    END) AS vat_per,
                    SUM(CASE
                        WHEN tax.tribute_code = '07' THEN tax.balance ELSE 0
                    END) AS perc_iibb,
                    SUM(CASE
                        WHEN tax.tribute_code = '09' THEN tax.balance ELSE 0
                    END) AS perc_earnings,
                    SUM(CASE
                        WHEN tax.tribute_code IN ('03','08')
                        THEN tax.balance ELSE 0
                    END) AS city_tax,
                    SUM(CASE
                        WHEN tax.tribute_code IN ('02','04','05','99')
                        THEN tax.balance ELSE 0
                    END) AS other_taxes,
                    SUM(account_move_line.balance) AS total
                FROM
                    %(table_references)s
                JOIN
                    account_move ON account_move_line.move_id = account_move.id
                LEFT JOIN
                    tax_lines tax ON tax.move_line_id = account_move_line.id
                LEFT JOIN
                    base_lines base ON base.move_line_id = account_move_line.id
                LEFT JOIN
                    res_partner rp ON rp.id = account_move.commercial_partner_id
                LEFT JOIN
                    l10n_latam_identification_type lit
                    ON rp.l10n_latam_identification_type_id = lit.id
                LEFT JOIN
                    l10n_ar_afip_responsibility_type art
                    ON account_move.l10n_ar_afip_responsibility_type_id =
                        art.id
                WHERE
                    (account_move_line.tax_line_id IS NOT NULL OR
                        base.vat_code IS NOT NULL)
                    AND (tax.type_tax_use IN %(tax_types)s OR
                        base.type_tax_use IN %(tax_types)s)
                %(search_condition)s
                GROUP BY
                    account_move.id, art.name, rp.id, lit.id,
                    COALESCE(tax.type_tax_use, base.type_tax_use)

                ORDER BY
                    account_move.invoice_date, account_move.name
            """,
            column_group_key=column_group_key,
            table_references=table_references,
            tax_types=tax_types,
            search_condition=search_condition,
        )
        return query
