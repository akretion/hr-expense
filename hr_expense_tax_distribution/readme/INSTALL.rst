This module depends on the standard ``hr_expense`` module. No
third-party dependency is required.

Install the module in the usual way (Apps menu or
``-i hr_expense_tax_distribution`` on the command line). The *Tax
Distribution* table appears automatically on the expense form as soon as
the module is installed — no migration of existing data is needed.

Incompatibility with ``hr_expense_tax_adjust``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hr_expense_tax_distribution`` is **not compatible** with the
``hr_expense_tax_adjust`` module.

Both modules override ``_compute_amount`` on ``hr.expense`` to update
``total_amount`` and ``untaxed_amount``, but with conflicting logic:

- ``hr_expense_tax_adjust`` computes ``total_amount`` as
  ``untaxed_amount + tax_amount``, where ``tax_amount`` is stored in the
  ``amount_by_group_txt`` field and can be manually edited by the user
  via a dedicated JavaScript widget.
- ``hr_expense_tax_distribution`` computes ``total_amount`` as the sum
  of the ``total_amount_currency`` fields on the tax distribution lines.

When both modules are installed simultaneously, the last
``_compute_amount`` in the MRO chain overwrites the result of the other,
producing incorrect ``total_amount`` values.

Do not install both modules in the same Odoo instance. Choose one
approach:

- Use ``hr_expense_tax_adjust`` if you need to manually adjust the tax
  amount on a single-rate expense.
- Use ``hr_expense_tax_distribution`` if you need to split a receipt
  across multiple tax rates with a correct per-rate accounting entry.
