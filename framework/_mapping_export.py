"""Export assembled mapping metadata to YAML files."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

if __package__:
    from framework._mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, SOURCE_KIND,
    )
    from framework._mapping_utils import (
        safe_filename, unique_filename, unique_nested_filename,
    )
    from framework._mapping_validation import validate_metadata_directory
    from framework._mapping_workbook import _build_metadata

else:
    from _mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, SOURCE_KIND,
    )
    from _mapping_utils import safe_filename, unique_filename, unique_nested_filename
    from _mapping_validation import validate_metadata_directory
    from _mapping_workbook import _build_metadata


def _write_yaml(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

def export_workbook(
    input_path: Path,
    output_dir: Path,
    *,
    verbose: bool = False,
) -> list[Path]:
    """Generate entity mappings, source-table mappings, and a YAML manifest."""
    if not input_path.is_file():
        raise FileNotFoundError(f"S2T workbook does not exist: {input_path}")

    print("[1/4] Reading S2T workbook")
    entities, sources, warnings, enrichment = _build_metadata(input_path)
    print(f"      Worksheets processed: {len(entities)}")
    print("[2/4] Extracting mappings")
    print(f"      Entity mappings: {len(entities)}")
    print(f"      Source tables discovered: {len(sources)}")

    used_entity_names: set[str] = set()
    used_source_names: set[str] = set()
    generated_paths = []
    entity_entries = []
    source_entries = []

    print("[3/4] Generating YAML metadata")
    for entity in entities:
        entity_name = entity["metadata"]["name"]
        filename = unique_filename(entity_name, used_entity_names) + ".yaml"
        relative_path = PurePosixPath("entities", filename).as_posix()
        path = output_dir / relative_path
        _write_yaml(path, entity)
        generated_paths.append(path)
        entity_entries.append({
            "name": entity_name,
            "worksheet": entity_name,
            "file": relative_path,
            "recordCount": entity["spec"]["recordCount"],
        })
        print(f"      Created: {path}")

    for source in sources:
        metadata = source["metadata"]
        source_system = safe_filename(metadata["sourceSystem"])
        source_schema = safe_filename(metadata["sourceSchema"])
        filename = unique_nested_filename(
            metadata["sourceTable"],
            ("sources", source_system, source_schema),
            used_source_names,
        ) + ".yaml"
        relative_path = PurePosixPath(
            "sources",
            source_system,
            source_schema,
            filename,
        ).as_posix()
        path = output_dir / relative_path
        _write_yaml(path, source)
        generated_paths.append(path)
        source_entries.append({
            "sourceSystem": metadata["sourceSystem"],
            "sourceSchema": metadata["sourceSchema"],
            "sourceTable": metadata["sourceTable"],
            "file": relative_path,
            "mappingCount": source["spec"]["mappingCount"],
        })
        print(f"      Created: {path}")

    entity_file_by_name = {
        entry["name"]: entry["file"]
        for entry in entity_entries
    }
    dependencies = set()
    for source, source_entry in zip(sources, source_entries):
        for mapping in source["spec"]["mappings"]:
            entity_file = entity_file_by_name.get(mapping["entity"])
            if entity_file is not None:
                dependencies.add((entity_file, source_entry["file"]))

    manifest = {
        "apiVersion": API_VERSION,
        "kind": MANIFEST_KIND,
        "sourceWorkbook": input_path.name,
        "entities": entity_entries,
        "sources": source_entries,
        "dependencies": [
            {"entity": entity_file, "source": source_file}
            for entity_file, source_file in sorted(dependencies)
        ],
        "enrichment": enrichment,
        "warnings": warnings,
    }
    manifest_path = output_dir / "_manifest.yaml"
    _write_yaml(manifest_path, manifest)
    generated_paths.append(manifest_path)
    print(f"      Created: {manifest_path}")

    print("[4/4] Validating generated metadata")
    errors = validate_metadata_directory(output_dir)
    if errors:
        raise ValueError("Generated metadata validation failed:\n" + "\n".join(errors))
    print(f"      Passed: {len(generated_paths)} YAML files")
    print(f"      Warnings: {len(warnings)}")
    if warnings:
        warning_counts: dict[str, int] = {}
        for warning in warnings:
            sheet_name = warning["worksheet"]
            warning_counts[sheet_name] = warning_counts.get(sheet_name, 0) + 1
        summary = ", ".join(
            f"{sheet_name}: {count}"
            for sheet_name, count in sorted(warning_counts.items())
        )
        print(f"      Warnings by worksheet: {summary}")
        print("      Row details: _manifest.yaml")
    if verbose:
        for warning in warnings:
            print(
                f"      WARNING: {warning['worksheet']} row {warning['excelRow']}: "
                f"{warning['message']}"
            )
    print(f"Complete: {len(generated_paths)} files created in {output_dir}")
    return generated_paths
