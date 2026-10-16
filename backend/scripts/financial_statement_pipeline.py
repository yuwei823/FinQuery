from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

try:
    from scripts.csv_parquet_pipeline import (
        ColumnSpec,
        DatasetSpec,
        compact_dataset,
        convert_dataset,
        validate_dataset,
        write_inventory,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/financial_statement_pipeline.py
    from csv_parquet_pipeline import (
        ColumnSpec,
        DatasetSpec,
        compact_dataset,
        convert_dataset,
        validate_dataset,
        write_inventory,
    )


SPEC = DatasetSpec(
    dataset="stock-fin-data-xbx-daily",
    database="trade_data",
    table="financial_statement",
    encoding="gb18030",
    skip_rows=1,
    columns=(
        ColumnSpec("stock_code", "symbol", "text"),
        ColumnSpec("statement_format", "statement_format", "text"),
        ColumnSpec("report_date", "report_date", "compact_date"),
        ColumnSpec("publish_date", "publish_date", "date"),
        ColumnSpec("B_total_assets@xbx", "total_assets", "number"),
        ColumnSpec("B_total_liab@xbx", "total_liabilities", "number"),
        ColumnSpec("B_total_equity_atoopc@xbx", "parent_equity", "number"),
        ColumnSpec("B_total_owner_equity@xbx", "total_owner_equity", "number"),
        ColumnSpec("B_currency_fund@xbx", "monetary_funds", "number", required=False),
        ColumnSpec("B_bill_receivable@xbx", "notes_receivable", "number", required=False),
        ColumnSpec("B_account_receivable@xbx", "accounts_receivable", "number", required=False),
        ColumnSpec("B_bill_and_account_receivable@xbx", "notes_and_accounts_receivable", "number", required=False),
        ColumnSpec("B_receivable_financing@xbx", "receivables_financing", "number", required=False),
        ColumnSpec("B_other_receivables_sum@xbx", "other_receivables_total", "number", required=False),
        ColumnSpec("B_prepays@xbx", "prepayments", "number", required=False),
        ColumnSpec("B_inventory@xbx", "inventory", "number", required=False),
        ColumnSpec("B_total_current_assets@xbx", "total_current_assets", "number", required=False),
        ColumnSpec("B_fixed_asset@xbx", "fixed_assets", "number", required=False),
        ColumnSpec("B_intangible_assets@xbx", "intangible_assets", "number", required=False),
        ColumnSpec("B_goodwill@xbx", "goodwill", "number", required=False),
        ColumnSpec("B_st_borrow@xbx", "short_term_borrowings", "number", required=False),
        ColumnSpec("B_bill_payable@xbx", "notes_payable", "number", required=False),
        ColumnSpec("B_accounts_payable@xbx", "accounts_payable", "number", required=False),
        ColumnSpec("B_bill_and_account_payable@xbx", "notes_and_accounts_payable", "number", required=False),
        ColumnSpec("B_contract_liab@xbx", "contract_liabilities", "number", required=False),
        ColumnSpec("B_payroll_payable@xbx", "employee_benefits_payable", "number", required=False),
        ColumnSpec("B_tax_payable@xbx", "taxes_payable", "number", required=False),
        ColumnSpec("B_other_payables_sum@xbx", "other_payables_total", "number", required=False),
        ColumnSpec("B_noncurrent_liab_due_in1y@xbx", "current_portion_noncurrent_liabilities", "number", required=False),
        ColumnSpec("B_st_bond_payable@xbx", "short_term_bonds_payable", "number", required=False),
        ColumnSpec("B_total_current_liab@xbx", "total_current_liabilities", "number", required=False),
        ColumnSpec("B_lt_loan@xbx", "long_term_borrowings", "number", required=False),
        ColumnSpec("B_bond_payable@xbx", "bonds_payable", "number", required=False),
        ColumnSpec("B_lease_libilities@xbx", "lease_liabilities", "number", required=False),
        ColumnSpec("B_total_noncurrent_liab@xbx", "total_noncurrent_liabilities", "number", required=False),
        ColumnSpec("B_preferred_shares@xbx", "preferred_shares_equity", "number", required=False),
        ColumnSpec("B_minority_equity@xbx", "minority_interest", "number", required=False),
        ColumnSpec("R_revenue@xbx", "operating_revenue", "number"),
        ColumnSpec("R_operating_total_revenue@xbx", "total_operating_revenue", "number", required=False),
        ColumnSpec("R_operating_total_cost@xbx", "total_operating_cost", "number", required=False),
        ColumnSpec("R_operating_cost@xbx", "operating_cost", "number", required=False),
        ColumnSpec("R_operating_taxes_and_surcharge@xbx", "taxes_and_surcharges", "number", required=False),
        ColumnSpec("R_sales_fee@xbx", "selling_expenses", "number", required=False),
        ColumnSpec("R_manage_fee@xbx", "administrative_expenses", "number", required=False),
        ColumnSpec("R_rad_cost_sum@xbx", "research_and_development_expenses", "number", required=False),
        ColumnSpec("R_financing_expenses@xbx", "finance_expenses", "number", required=False),
        ColumnSpec("R_interest_fee@xbx", "interest_expense", "number", required=False),
        ColumnSpec("R_fc_interest_income@xbx", "interest_income_finance_expense_note", "number", required=False),
        ColumnSpec("R_income_tax_cost@xbx", "income_tax_expense", "number", required=False),
        ColumnSpec("R_minority_gal@xbx", "minority_profit_loss", "number", required=False),
        ColumnSpec("R_op@xbx", "operating_profit", "number"),
        ColumnSpec("R_total_profit@xbx", "total_profit", "number"),
        ColumnSpec("R_np@xbx", "net_profit", "number"),
        ColumnSpec("R_np_atoopc@xbx", "parent_net_profit", "number"),
        ColumnSpec("R_basic_eps@xbx", "basic_eps", "number"),
        ColumnSpec("R_dlt_earnings_per_share@xbx", "diluted_eps", "number"),
        ColumnSpec("C_ncf_from_oa@xbx", "operating_cash_flow", "number"),
        ColumnSpec("C_ncf_from_ia@xbx", "investing_cash_flow", "number"),
        ColumnSpec("C_ncf_from_fa@xbx", "financing_cash_flow", "number"),
        ColumnSpec("C_net_increase_in_cce@xbx", "net_cash_increase", "number"),
        ColumnSpec("C_final_balance_of_cce@xbx", "ending_cash_balance", "number"),
        ColumnSpec("C_initial_cce_balance@xbx", "beginning_cash_equivalents", "number", required=False),
        ColumnSpec("C_depreciation_etc@xbx", "depreciation_fixed_assets", "number", required=False),
        ColumnSpec("C_intangible_assets_amortized@xbx", "amortization_intangible_assets", "number", required=False),
        ColumnSpec("C_lt_deferred_expenses_amrtzt@xbx", "amortization_long_term_deferred_expenses", "number", required=False),
        ColumnSpec("C_cash_paid_for_assets@xbx", "capital_expenditure_cash", "number", required=False),
        ColumnSpec("C_cash_received_of_borrowing@xbx", "cash_proceeds_from_borrowings", "number", required=False),
        ColumnSpec("C_cash_received_from_bond_issue@xbx", "cash_proceeds_from_bond_issuance", "number", required=False),
        ColumnSpec("C_cash_pay_for_debt@xbx", "cash_repayment_of_debt", "number", required=False),
        ColumnSpec("C_cash_paid_of_distribution@xbx", "cash_paid_for_dividends_interest", "number", required=False),
        ColumnSpec("C_dap_paid_to_minority_holder@xbx", "dividends_paid_to_minority", "number", required=False),
        ColumnSpec("C_inventory_decrease@xbx", "inventory_decrease_cashflow_adjustment", "number", required=False),
        ColumnSpec("C_operating_items_decrease@xbx", "operating_receivables_decrease_adjustment", "number", required=False),
        ColumnSpec("C_increase_of_operating_item@xbx", "operating_payables_increase_adjustment", "number", required=False),
    ),
    key_fields=("symbol", "statement_format", "report_date", "publish_date"),
    identity_field="symbol",
    recursive=True,
    identity_from_parent=True,
    allow_extra_columns=True,
)


def _default_source() -> Path:
    return Path(os.getenv("TRADE_DATA_ROOT", "D:/trade_data")) / "stock-fin-data-xbx"


def _default_output() -> Path:
    return Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated")) / SPEC.database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the XBX financial statement table")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--source", type=Path, default=_default_source())
    inventory_parser.add_argument(
        "--output",
        type=Path,
        default=_default_output() / "_inventory.financial_statement.json",
    )
    convert_parser = subparsers.add_parser("convert")
    convert_parser.add_argument("--source", type=Path, default=_default_source())
    convert_parser.add_argument("--output", type=Path, default=_default_output())
    convert_parser.add_argument("--force", action="store_true")
    convert_parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    for command in ("validate", "compact"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--output", type=Path, default=_default_output())
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        result = write_inventory(SPEC, args.source, args.output)
    elif args.command == "convert":
        result = convert_dataset(
            SPEC,
            args.source,
            args.output,
            force=args.force,
            workers=args.workers,
            progress=True,
        )
    elif args.command == "validate":
        result = validate_dataset(SPEC, args.output)
    else:
        result = compact_dataset(SPEC, args.output)
    displayed = {key: value for key, value in result.items() if key != "files"}
    print(json.dumps(displayed, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
