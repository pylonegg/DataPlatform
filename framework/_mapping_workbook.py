"""Read workbook worksheets and assemble mapping metadata documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

if __package__:
    from framework._mapping_schema import (
        API_VERSION, ENTITY_KIND, REQUIRED_HEADERS, SOURCE_KIND, SUPPORTING_SHEETS,
    )
    from framework._mapping_utils import mapping_value

else:
    from _mapping_schema import (
        API_VERSION, ENTITY_KIND, REQUIRED_HEADERS, SOURCE_KIND, SUPPORTING_SHEETS,
    )
    from _mapping_utils import mapping_value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())

def _read_headers(sheet_name: str, values: tuple[Any, ...]) -> list[str]:
    headers = []
    seen_headers: set[str] = set()
    for column_number, value in enumerate(values, start=1):
        header = str(value).strip() if not _is_empty(value) else f"column_{column_number}"
        if header in seen_headers:
            raise ValueError(
                f"Worksheet {sheet_name!r} has a duplicate header {header!r}."
            )
        seen_headers.add(header)
        headers.append(header)

    missing_headers = sorted(REQUIRED_HEADERS - seen_headers)
    if missing_headers:
        raise ValueError(
            f"Worksheet {sheet_name!r} is missing required headers: "
            f"{', '.join(missing_headers)}."
        )
    return headers

def _read_supporting_sheet(
    sheet_name: str,
    rows: list[tuple[Any, ...]],
    required_headers: frozenset[str],
) -> list[dict[str, Any]]:
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if required_headers <= {
                str(value).strip()
                for value in row
                if not _is_empty(value)
            }
        ),
        None,
    )
    if header_index is None:
        raise ValueError(
            f"Supporting worksheet {sheet_name!r} is missing required headers: "
            f"{', '.join(sorted(required_headers))}."
        )
    headers = _read_optional_headers(sheet_name, rows[header_index])
    records = []
    for row_number, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if all(_is_empty(value) for value in row):
            continue
        record: dict[str, Any] = {"_excel_row": row_number}
        for column_index, header in enumerate(headers):
            value = row[column_index] if column_index < len(row) else None
            record[header] = mapping_value(value)
        records.append(record)
    return records

def _read_optional_headers(sheet_name: str, values: tuple[Any, ...]) -> list[str]:
    headers = []
    seen_headers: set[str] = set()
    for column_number, value in enumerate(values, start=1):
        header = (
            str(value).strip()
            if not _is_empty(value)
            else f"column_{column_number}"
        )
        if header in seen_headers:
            raise ValueError(
                f"Worksheet {sheet_name!r} has a duplicate header {header!r}."
            )
        seen_headers.add(header)
        headers.append(header)
    return headers

def _mapping_warning(
    sheet_name: str,
    excel_row: int,
    message: str,
) -> dict[str, Any]:
    return {
        "worksheet": sheet_name,
        "excelRow": excel_row,
        "message": message,
    }

def _entity_type(sheet_name: str) -> str | None:
    normalized_name = sheet_name.casefold()
    if normalized_name.startswith(("dim_", "dimension_")):
        return "dimension"
    if normalized_name.startswith(("fct_", "fact_")):
        return "fact"
    return None

def _build_metadata(
    input_path: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    try:
        workbook = openpyxl.load_workbook(
            input_path,
            data_only=False,
            read_only=True,
        )
    except (OSError, BadZipFile, InvalidFileException) as error:
        raise ValueError(f"Unable to read S2T workbook {input_path}: {error}") from error
    entities: list[dict[str, Any]] = []
    source_mappings: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = []
    enrichment: dict[str, list[dict[str, Any]]] = {}

    try:
        for worksheet in workbook.worksheets:
            rows = list(worksheet.iter_rows(values_only=True))
            supporting_headers = SUPPORTING_SHEETS.get(worksheet.title.casefold())
            if supporting_headers is not None:
                enrichment[worksheet.title.casefold()] = _read_supporting_sheet(
                    worksheet.title,
                    rows,
                    supporting_headers,
                )
                continue
            header_index = next(
                (
                    index
                    for index, row in enumerate(rows)
                    if REQUIRED_HEADERS <= {
                        str(value).strip()
                        for value in row
                        if not _is_empty(value)
                    }
                ),
                None,
            )
            if header_index is None:
                first_nonempty_index = next(
                    (
                        index
                        for index, row in enumerate(rows)
                        if any(not _is_empty(value) for value in row)
                    ),
                    None,
                )
                if first_nonempty_index is None:
                    warnings.append(_mapping_warning(
                        worksheet.title,
                        1,
                        "Worksheet is empty and was skipped.",
                    ))
                    continue
                _read_headers(worksheet.title, rows[first_nonempty_index])

            headers = _read_headers(worksheet.title, rows[header_index])
            records = []
            for excel_row, row in enumerate(rows[header_index + 1:], start=header_index + 2):
                if all(_is_empty(value) for value in row):
                    continue

                record: dict[str, Any] = {"_excel_row": excel_row}
                for column_index, header in enumerate(headers):
                    value = row[column_index] if column_index < len(row) else None
                    record[header] = mapping_value(value)
                records.append(record)

                target_field = record.get("Field")
                if _is_empty(target_field):
                    continue
                for field_name in ("Attribute Type", "Field Type"):
                    if _is_empty(record.get(field_name)):
                        warnings.append(_mapping_warning(
                            worksheet.title,
                            excel_row,
                            f"Target field {target_field!r} is missing {field_name!r}.",
                        ))

                source_system = record.get("Source System")
                source_schema = record.get("Source Schema")
                source_table = record.get("Source Table")
                source_parts = (source_system, source_schema, source_table)
                if isinstance(source_system, str) and source_system.strip().casefold() == "internal":
                    continue
                if all(isinstance(part, str) and part.strip() for part in source_parts):
                    source_key = tuple(part.strip() for part in source_parts)
                    source_mappings.setdefault(source_key, []).append({
                        "entity": worksheet.title,
                        "worksheet": worksheet.title,
                        "excelRow": excel_row,
                        "targetField": target_field,
                        "sourceFields": record.get("Source Field(s)"),
                        "mapping": record,
                    })
                    if _is_empty(record.get("Source Field(s)")):
                        warnings.append(_mapping_warning(
                            worksheet.title,
                            excel_row,
                            f"Target field {target_field!r} has a source table but no source field.",
                        ))
                elif all(_is_empty(part) for part in source_parts):
                    warnings.append(_mapping_warning(
                        worksheet.title,
                        excel_row,
                        f"Target field {target_field!r} has no documented source table; "
                        "review whether it is derived or internal.",
                    ))
                elif any(not _is_empty(part) for part in source_parts):
                    warnings.append(_mapping_warning(
                        worksheet.title,
                        excel_row,
                        f"Target field {target_field!r} has an incomplete source system/schema/table mapping.",
                    ))

            entities.append({
                "apiVersion": API_VERSION,
                "kind": ENTITY_KIND,
                "metadata": {
                    "name": worksheet.title,
                    "sourceWorkbook": input_path.name,
                    "sourceWorksheet": worksheet.title,
                    "headerRow": header_index + 1,
                    "entityType": _entity_type(worksheet.title),
                },
                "spec": {
                    "recordCount": len(records),
                    "records": records,
                },
            })
    finally:
        workbook.close()

    if not entities:
        raise ValueError("The workbook contains no worksheets with valid mapping headers.")

    sources = []
    for (source_system, source_schema, source_table), mappings in sorted(source_mappings.items()):
        sources.append({
            "apiVersion": API_VERSION,
            "kind": SOURCE_KIND,
            "metadata": {
                "sourceSystem": source_system,
                "sourceSchema": source_schema,
                "sourceTable": source_table,
                "sourceWorkbook": input_path.name,
            },
            "spec": {
                "mappingCount": len(mappings),
                "mappings": mappings,
            },
        })

    return entities, sources, warnings, enrichment
