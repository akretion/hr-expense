# Copyright 2026 Akretion
# @author Guillaume MASSON <guillaume.masson@akretion.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import formatLang


class HrExpense(models.Model):
    _inherit = "hr.expense"

    tax_line_ids = fields.One2many(
        comodel_name="hr.expense.tax.line",
        inverse_name="expense_id",
        string="Tax Distribution Lines",
        copy=True,
    )
    has_tax_distribution = fields.Boolean(
        compute="_compute_has_tax_distribution",
        store=True,
    )

    # -------------------------------------------------------------------------
    # Compute
    # -------------------------------------------------------------------------

    @api.depends("tax_line_ids", "tax_line_ids.base_amount_currency")
    def _compute_has_tax_distribution(self):
        for expense in self:
            expense.has_tax_distribution = bool(expense.tax_line_ids)

    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------

    @api.onchange("tax_ids")
    def _onchange_tax_ids_generate_distribution_lines(self):
        """Maintain tax distribution lines in sync with tax_ids.

        Rules:
        - If tax_ids has 0 or 1 tax: clear all distribution lines (single-tax
          expenses use the standard Odoo flow; no distribution needed).
        - If tax_ids has 2+ taxes: one line per tax is maintained.
          Existing lines whose tax is still present are preserved (base amounts
          are kept).  Lines for removed taxes are deleted.  Lines for newly
          added taxes are created with base_amount_currency = 0.
        """
        if len(self.tax_ids) <= 1:
            self.tax_line_ids = [Command.clear()]
            return
        self.tax_line_ids = self._sync_tax_distribution_lines(self.tax_ids)

    def _sync_tax_distribution_lines(self, taxes):
        """Return a list of ORM Commands to sync tax distribution lines with
        the given ``taxes`` recordset.

        Lines covering a single tax still present in ``taxes`` are preserved
        via Command.link() so their base_amount_currency is kept.  Lines for
        taxes that have been removed are dropped.  A new Command.create() is
        added for each tax not yet covered by a single-tax line.

        The caller is responsible for assigning the result to ``tax_line_ids``
        (onchange) or passing it to write() / create() (tests, other callers).
        This design allows downstream modules to override this method and add
        extra fields (e.g. an account_id) to the created lines.

        Uses self._origin.tax_line_ids so that ids are always real DB integers,
        even when called from inside an onchange where self is a virtual record.
        On a new (unsaved) expense, _origin.tax_line_ids is an empty recordset,
        which is the correct starting point.
        """
        self.ensure_one()
        existing_by_tax_id = {
            line.tax_ids.ids[0]: line
            for line in self.tax_line_ids
            if len(line.tax_ids) == 1
        }
        current_tax_ids = set(taxes.ids)

        commands = []
        covered = set()

        # Keep existing single-tax lines whose tax is still selected.
        for tax_id, line in existing_by_tax_id.items():
            if tax_id in current_tax_ids:
                commands.append(Command.link(line.id))
            else:
                commands.append(Command.delete(line.id))
            covered.add(tax_id)

        # Create new lines for taxes not yet covered.
        for tax in taxes._origin.filtered(lambda t: t.id not in covered):
            commands.append(
                Command.create(
                    {
                        "tax_ids": [Command.set(tax.ids)],
                        "base_amount_currency": 0.0,
                    }
                )
            )

        return commands

    @api.depends(
        "quantity",
        "unit_amount",
        "tax_ids",
        "currency_id",
        "tax_line_ids",
        "tax_line_ids.base_amount_currency",
        "tax_line_ids.tax_amount_currency",
    )
    def _compute_amount(self):
        super()._compute_amount()
        for expense in self.filtered(
            lambda he: he.has_tax_distribution
            and any(tl.base_amount_currency for tl in he.tax_line_ids)
        ):
            total = sum(expense.tax_line_ids.mapped("total_amount_currency"))
            tax_sum = sum(expense.tax_line_ids.mapped("tax_amount_currency"))
            expense.total_amount = total
            expense.untaxed_amount = total - tax_sum

    @api.onchange("tax_line_ids", "tax_line_ids.base_amount_currency")
    def _onchange_tax_line_ids_recompute_amount(self):
        self._compute_amount()

    def _check_tax_distribution_total(self):
        """Validate that distribution line totals match the expense total.

        Called explicitly from action_submit_expenses instead of via
        @api.constrains, to avoid false positives during onchange when lines
        are being built incrementally (some lines may still be at zero).
        """
        for expense in self:
            if not expense.tax_line_ids:
                continue
            if not expense.total_amount:
                continue
            if any(
                expense.currency_id.is_zero(tl.base_amount_currency)
                for tl in expense.tax_line_ids
            ):
                raise ValidationError(
                    _(
                        'Expense "%(name)s" has tax distribution lines with a '
                        "zero base amount. Please fill in all base amounts before "
                        "submitting.",
                        name=expense.name,
                    )
                )
            distributed_base = sum(expense.tax_line_ids.mapped("base_amount_currency"))
            reference = expense.unit_amount * expense.quantity
            diff = abs(distributed_base - reference)
            if not expense.currency_id.is_zero(diff):
                raise ValidationError(
                    _(
                        "The sum of tax distribution line bases (%(distributed)s) "
                        "does not match the expense untaxed amount (%(total)s) on "
                        'expense "%(name)s". '
                        "Please adjust the base amounts so that the totals match.",
                        distributed=formatLang(
                            self.env, distributed_base, currency_obj=expense.currency_id
                        ),
                        total=formatLang(
                            self.env,
                            expense.untaxed_amount,
                            currency_obj=expense.currency_id,
                        ),
                        name=expense.name,
                    )
                )

    def action_submit_expenses(self):
        """Validate tax distribution totals before submission."""
        self._check_tax_distribution_total()
        return super().action_submit_expenses()

    # -------------------------------------------------------------------------
    # Accounting entry generation
    # -------------------------------------------------------------------------

    def _get_account_move_line_values(self):
        result = super()._get_account_move_line_values()
        for expense in self.filtered("has_tax_distribution"):
            dist_lines = expense._get_tax_distribution_move_lines_vals()

            total_debit = sum(
                dl.get("debit", 0) - dl.get("credit", 0) for dl in dist_lines
            )
            account_date = (
                expense.date
                or expense.sheet_id.accounting_date
                or fields.Date.context_today(expense)
            )
            partner_id = (
                expense.employee_id.sudo().address_home_id.commercial_partner_id.id
            )
            move_line_name = (
                expense.employee_id.name + ": " + expense.name.split("\n")[0][:64]
            )
            move_line_dst = {
                "name": move_line_name,
                "debit": -total_debit if total_debit < 0 else 0,
                "credit": total_debit if total_debit > 0 else 0,
                "account_id": expense._get_expense_account_destination(),
                "date_maturity": account_date,
                "amount_currency": -sum(
                    dl.get("amount_currency", 0) for dl in dist_lines
                ),
                "currency_id": expense.currency_id.id,
                "expense_id": expense.id,
                "partner_id": partner_id,
            }
            result[expense.id] = dist_lines + [move_line_dst]
        return result

    def _get_tax_distribution_move_lines_vals(self):
        self.ensure_one()
        move_lines = []
        account_src = self._get_expense_account_source()
        account_date = (
            self.date
            or self.sheet_id.accounting_date
            or fields.Date.context_today(self)
        )
        company_currency = self.company_id.currency_id
        partner_id = self.employee_id.sudo().address_home_id.commercial_partner_id.id
        move_line_name = self.employee_id.name + ": " + self.name.split("\n")[0][:64]
        quantity = self.quantity or 1.0

        for dist_line in self.tax_line_ids:
            taxes = dist_line.tax_ids.with_context(round=True).compute_all(
                dist_line.base_amount_currency,
                self.currency_id,
                1,
                self.product_id,
            )
            # Base (HT) line
            balance = self.currency_id._convert(
                taxes["total_excluded"],
                company_currency,
                self.company_id,
                account_date,
            )
            move_lines.append(
                {
                    "name": move_line_name,
                    "quantity": quantity,
                    "debit": balance if balance > 0 else 0,
                    "credit": -balance if balance < 0 else 0,
                    "amount_currency": taxes["total_excluded"],
                    "account_id": account_src.id,
                    "product_id": self.product_id.id,
                    "product_uom_id": self.product_uom_id.id,
                    "analytic_account_id": self.analytic_account_id.id,
                    "analytic_tag_ids": [(6, 0, self.analytic_tag_ids.ids)],
                    "expense_id": self.id,
                    "partner_id": partner_id,
                    "tax_ids": [(6, 0, dist_line.tax_ids.ids)],
                    "tax_tag_ids": [(6, 0, taxes["base_tags"])],
                    "currency_id": self.currency_id.id,
                }
            )

            # Tax lines
            for tax in taxes["taxes"]:
                tax_balance = self.currency_id._convert(
                    tax["amount"],
                    company_currency,
                    self.company_id,
                    account_date,
                )
                if tax["tax_repartition_line_id"]:
                    rep_ln = self.env["account.tax.repartition.line"].browse(
                        tax["tax_repartition_line_id"]
                    )
                    base_amount = self.env["account.move"]._get_base_amount_to_display(
                        tax["base"], rep_ln
                    )
                    base_amount = self.currency_id._convert(
                        base_amount, company_currency, self.company_id, account_date
                    )
                else:
                    base_amount = None

                move_lines.append(
                    {
                        "name": tax["name"],
                        "quantity": 1,
                        "debit": tax_balance if tax_balance > 0 else 0,
                        "credit": -tax_balance if tax_balance < 0 else 0,
                        "amount_currency": tax["amount"],
                        "account_id": tax["account_id"] or account_src.id,
                        "tax_repartition_line_id": tax["tax_repartition_line_id"],
                        "tax_tag_ids": tax["tag_ids"],
                        "tax_base_amount": base_amount,
                        "expense_id": self.id,
                        "partner_id": partner_id,
                        "currency_id": self.currency_id.id,
                        "analytic_account_id": (
                            self.analytic_account_id.id if tax["analytic"] else False
                        ),
                        "analytic_tag_ids": (
                            [(6, 0, self.analytic_tag_ids.ids)]
                            if tax["analytic"]
                            else False
                        ),
                    }
                )

        return move_lines
