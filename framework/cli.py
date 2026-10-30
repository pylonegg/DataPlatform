"""Command-line interface for S2T metadata generation and validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from framework.contract_mapping import (
    export_workbook,
    validate_metadata_directory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataplatform",
        description="Generate and validate metadata from an S2T workbook.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser(
        "generate-metadata",
        help="Generate entity, source-table, and manifest YAML files.",
    )
    generate.add_argument("--workbook", type=Path, default=Path("s2t.xlsx"))
    generate.add_argument("--output-dir", type=Path, default=Path("metadata"))
    generate.add_argument("--verbose", action="store_true")

    validate = commands.add_parser(
        "validate-metadata",
        help="Validate a generated metadata directory.",
    )
    validate.add_argument("--metadata-dir", type=Path, default=Path("metadata"))

    generate_contracts = commands.add_parser(
        "generate-contracts",
        help="Generate source/entity contract drafts and SQL from mapping metadata.",
    )
    generate_contracts.add_argument("--metadata-dir", type=Path, default=Path("metadata"))
    generate_contracts.add_argument("--contracts-dir", type=Path, default=Path("contracts"))
    generate_contracts.add_argument("--sql-dir", type=Path, default=Path("warehouse/sql"))
    generate_contracts.add_argument("--discover-source-schema", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "generate-metadata":
            export_workbook(args.workbook, args.output_dir, verbose=args.verbose)
            return 0

        if args.command == "generate-contracts":
            from framework.generate_contracts import generate_contracts_and_sql

            generate_contracts_and_sql(
                metadata_dir=args.metadata_dir,
                contracts_dir=args.contracts_dir,
                sql_dir=args.sql_dir,
                discover_source_schema=args.discover_source_schema,
            )
            return 0

        errors = validate_metadata_directory(args.metadata_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Metadata processing failed: {error}\n")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Metadata validation failed with {len(errors)} error(s).")
        return 1

    print(f"Validated metadata in {args.metadata_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())