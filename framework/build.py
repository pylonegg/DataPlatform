"""Run the complete S2T-to-contract-and-SQL build."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
	from framework.contract_mapping import (
		export_workbook,
		validate_metadata_directory,
	)
	from framework.generate_contracts import generate_contracts_and_sql
else:
	from contract_mapping import export_workbook, validate_metadata_directory
	from generate_contracts import generate_contracts_and_sql


def run_build(
	workbook: Path = Path("s2t.xlsx"),
	metadata_dir: Path = Path("metadata"),
	contracts_dir: Path = Path("contracts"),
	sql_dir: Path = Path("warehouse/sql"),
	*,
	verbose: bool = False,
	discover_source_schema: bool = False,
) -> list[Path]:
	print("[1/3] Generating mapping metadata")
	metadata_paths = export_workbook(workbook, metadata_dir, verbose=verbose)

	print("[2/3] Validating mapping metadata")
	metadata_errors = validate_metadata_directory(metadata_dir)
	if metadata_errors:
		raise ValueError("Metadata validation failed:\n" + "\n".join(metadata_errors))

	print("[3/3] Generating contracts and SQL")
	generated_paths = generate_contracts_and_sql(
		metadata_dir=metadata_dir,
		contracts_dir=contracts_dir,
		sql_dir=sql_dir,
		discover_source_schema=discover_source_schema,
	)
	print(
		f"Build complete: {len(metadata_paths)} metadata files and "
		f"{len(generated_paths)} contract/SQL files."
	)
	return [*metadata_paths, *generated_paths]


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description="Generate mapping metadata, contract drafts, and SQL."
	)
	parser.add_argument("--workbook", type=Path, default=Path("s2t.xlsx"))
	parser.add_argument("--metadata-dir", type=Path, default=Path("metadata"))
	parser.add_argument("--contracts-dir", type=Path, default=Path("contracts"))
	parser.add_argument("--sql-dir", type=Path, default=Path("warehouse/sql"))
	parser.add_argument("--verbose", action="store_true")
	parser.add_argument(
		"--discover-source-schema",
		action="store_true",
		help="Connect to configured SQL Server sources and discover column metadata.",
	)
	args = parser.parse_args(argv)

	try:
		run_build(
			workbook=args.workbook,
			metadata_dir=args.metadata_dir,
			contracts_dir=args.contracts_dir,
			sql_dir=args.sql_dir,
			verbose=args.verbose,
			discover_source_schema=args.discover_source_schema,
		)
	except (OSError, ValueError) as error:
		parser.exit(1, f"Build failed: {error}\n")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
