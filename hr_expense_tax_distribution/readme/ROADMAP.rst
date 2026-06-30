-  **Analytic distribution per line** — the current implementation
   copies the ``analytic_distribution`` from the parent expense to every
   distribution line. A future improvement could allow setting a
   distinct analytic distribution on each tax distribution line.
-  **Automatic total update** — when the user adjusts the distribution
   lines, the expense *Total* field is not automatically recalculated.
   The user must ensure consistency manually. A future improvement could
   offer a *Recompute Total* helper button.
-  **Import / OCR integration** — receipts parsed by the Odoo AI/OCR
   feature do not currently populate distribution lines. Integration
   with the attachment extraction pipeline is a possible future
   improvement.
-  **Compatibility with** ``hr_expense_tax_adjust`` — two approaches
   could make the modules compatible in a future version:

   1. **OCA CI test matrix** — configure ``.github/workflows/test.yml``
      to test the two modules in separate jobs so that CI catches
      regressions without requiring simultaneous installation.
   2. **Shared** ``amount_by_group`` **field** —
      ``hr_expense_tax_distribution`` could detect the presence of the
      ``amount_by_group`` and ``amount_by_group_txt`` fields (introduced
      by ``hr_expense_tax_adjust``) and populate them from the
      distribution lines. This would let
      ``hr_expense_tax_adjust._compute_amount`` read consistent data and
      produce the correct ``total_amount``, making both modules
      installable at the same time. This approach requires a glue module
      or an explicit dependency between the two.
