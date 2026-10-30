"""Helpers for running the contract build from a Fabric Lakehouse notebook."""

from __future__ import annotations

from pathlib import Path

from framework.build import run_build


def _lakehouse_path(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Lakehouse Files path must be a safe relative path: {relative_path!r}.")

    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Lakehouse Files path escapes the configured root: {relative_path!r}.")
    return resolved


def run_fabric_build(
    lakehouse_files_dir: Path,
    *,
    workbook_path: str = "s2t.xlsx",
    output_dir: str = "contract-build",
    discover_source_schema: bool = False,
) -> list[Path]:
    """Build contracts using files under the mounted Lakehouse Files directory."""
    files_root = Path(lakehouse_files_dir).resolve()
    if not files_root.is_dir():
        raise NotADirectoryError(f"Lakehouse Files directory does not exist: {files_root}")

    workbook = _lakehouse_path(files_root, workbook_path)
    if not workbook.is_file():
        raise FileNotFoundError(f"S2T workbook does not exist in Lakehouse Files: {workbook}")

    output_root = _lakehouse_path(files_root, output_dir)
    return run_build(
        workbook=workbook,
        metadata_dir=output_root / "metadata",
        contracts_dir=output_root / "contracts",
        sql_dir=output_root / "warehouse" / "sql",
        discover_source_schema=discover_source_schema,
    )
