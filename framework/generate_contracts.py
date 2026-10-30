"""Public orchestration API for generating contract drafts and SQL."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

if __package__:
    from framework.contract_mapping import validate_metadata_directory
    from framework._contract_common import (
        API_VERSION, CONTRACT_MANIFEST_KIND, ENTITY_CONTRACT_KIND,
        SOURCE_CONTRACT_KIND, _enrichment_rows, _find_ingestion_configuration,
        _find_source_configuration, _metadata_entries, _path_component,
        _write_sql, _write_yaml,
    )
    from framework._contract_validation import validate_generated_artifacts
    from framework._entity_contracts import _entity_contract
    from framework._source_contracts import _source_contract
    from framework._source_discovery import (
        _discover_source_table, discover_source_columns,
    )

else:
    from contract_mapping import validate_metadata_directory
    from _contract_common import (
        API_VERSION, CONTRACT_MANIFEST_KIND, ENTITY_CONTRACT_KIND,
        SOURCE_CONTRACT_KIND, _enrichment_rows, _find_ingestion_configuration,
        _find_source_configuration, _metadata_entries, _path_component,
        _write_sql, _write_yaml,
    )
    from _contract_validation import validate_generated_artifacts
    from _entity_contracts import _entity_contract
    from _source_contracts import _source_contract
    from _source_discovery import (
        _discover_source_table, discover_source_columns,
    )

__all__ = [
    "API_VERSION",
    "CONTRACT_MANIFEST_KIND",
    "ENTITY_CONTRACT_KIND",
    "SOURCE_CONTRACT_KIND",
    "discover_source_columns",
    "generate_contracts_and_sql",
    "validate_generated_artifacts",
]


def generate_contracts_and_sql(
    metadata_dir: Path = Path("metadata"),
    contracts_dir: Path = Path("contracts"),
    sql_dir: Path = Path("warehouse/sql"),
    *,
    discover_source_schema: bool = False,
) -> list[Path]:
    """Generate draft contracts and SQL, preserving unresolved work explicitly."""
    metadata_errors = validate_metadata_directory(metadata_dir)
    if metadata_errors:
        raise ValueError(
            "Metadata validation failed:\n" + "\n".join(metadata_errors)
        )
    manifest, entities, sources = _metadata_entries(metadata_dir)

    print("[1/4] Reading validated mapping metadata")
    print(f"      Entities: {len(entities)}")
    print(f"      Source tables: {len(sources)}")

    generated_paths: list[Path] = []
    contract_entries = []
    sql_entries = []
    entity_sql_status: dict[str, tuple[bool, list[str]]] = {}

    print("[2/4] Generating source contracts and extraction SQL")
    for source_entry, source in sources:
        metadata = source["metadata"]
        source_system = _path_component(metadata["sourceSystem"])
        source_schema = _path_component(metadata["sourceSchema"])
        source_table = _path_component(metadata["sourceTable"])
        source_metadata_file = source_entry["file"]
        contract_relative = PurePosixPath(
            "source", source_system, source_schema, f"{source_table}.yaml"
        ).as_posix()
        sql_relative = PurePosixPath(
            "source", source_system, source_schema, f"{source_table}.sql"
        ).as_posix()
        source_configuration = _find_source_configuration(
            manifest,
            metadata["sourceSystem"],
        )
        ingestion_configuration = _find_ingestion_configuration(
            manifest,
            metadata["sourceSystem"],
            metadata["sourceSchema"],
            metadata["sourceTable"],
        )
        discovered_columns = (
            _discover_source_table(
                source_configuration,
                metadata,
                ingestion_configuration,
            )
            if discover_source_schema
            else None
        )
        contract, query, warnings = _source_contract(
            source,
            source_metadata_file,
            sql_relative,
            source_configuration,
            ingestion_configuration,
            discovered_columns,
        )
        contract_path = contracts_dir / contract_relative
        sql_path = sql_dir / sql_relative
        _write_yaml(contract_path, contract)
        _write_sql(sql_path, query)
        generated_paths.extend((contract_path, sql_path))
        contract_entries.append({
            "kind": SOURCE_CONTRACT_KIND,
            "name": contract["metadata"]["name"],
            "file": contract_relative,
        })
        sql_entries.append({
            "kind": "sourceExtraction",
            "name": contract["metadata"]["name"],
            "file": sql_relative,
            "ready": contract["spec"]["ingestion"]["queryReady"],
        })
        print(f"      Contract: {contract_path}")
        print(f"      Query: {sql_path}")
        for warning in warnings:
            print(f"      WARNING: {metadata['sourceTable']}: {warning}")

    print("[3/4] Generating entity contracts and transformation SQL")
    for entity_entry, entity in entities:
        entity_name = entity["metadata"]["name"]
        entity_type = entity["metadata"].get("entityType")
        definition = next((
            row for row in _enrichment_rows(manifest, "entity_definitions")
            if str(row.get("Target Entity Name", "")).casefold() == entity_name.casefold()
        ), {})
        entity_filename = f"{_path_component(entity_name)}.yaml"
        entity_sql_name = f"{_path_component(entity_name)}.sql"
        contract_relative = PurePosixPath("entity", entity_filename).as_posix()
        sql_layer = _path_component(str(
            definition.get("Target Schema")
            or ("gold" if entity_type in {"dimension", "fact"} else "draft")
        ))
        sql_relative = PurePosixPath(sql_layer, entity_sql_name).as_posix()
        contract, statement, unresolved = _entity_contract(
            entity,
            entity_entry["file"],
            sql_relative,
            manifest,
        )
        contract_path = contracts_dir / contract_relative
        sql_path = sql_dir / sql_relative
        _write_yaml(contract_path, contract)
        _write_sql(sql_path, statement)
        generated_paths.extend((contract_path, sql_path))
        entity_sql_status[entity_name] = (contract["spec"]["execution"]["sqlReady"], unresolved)
        contract_entries.append({
            "kind": ENTITY_CONTRACT_KIND,
            "name": entity_name,
            "file": contract_relative,
        })
        sql_entries.append({
            "kind": "entityTransformation",
            "name": entity_name,
            "file": sql_relative,
            "ready": contract["spec"]["execution"]["sqlReady"],
        })
        print(f"      Contract: {contract_path}")
        print(f"      SQL: {sql_path} ({'ready' if not unresolved else 'draft'})")

    contract_manifest = {
        "apiVersion": API_VERSION,
        "kind": CONTRACT_MANIFEST_KIND,
        "sourceMetadataManifest": Path(os.path.relpath(
            metadata_dir / "_manifest.yaml",
            contracts_dir,
        )).as_posix(),
        "contracts": contract_entries,
        "sqlFiles": sql_entries,
        "draftEntities": [
            {"name": name, "unresolved": unresolved}
            for name, (ready, unresolved) in sorted(entity_sql_status.items())
            if not ready
        ],
        "sourceWorkbook": manifest.get("sourceWorkbook"),
    }
    contract_manifest_path = contracts_dir / "_manifest.yaml"
    _write_yaml(contract_manifest_path, contract_manifest)
    generated_paths.append(contract_manifest_path)

    print("[4/4] Validating generated files")
    errors = validate_generated_artifacts(contracts_dir, sql_dir)
    if errors:
        raise ValueError("Generated contract validation failed:\n" + "\n".join(errors))
    ready_entities = sum(ready for ready, _ in entity_sql_status.values())
    print(f"      Passed: {len(generated_paths)} generated files")
    print(f"      Entity SQL ready: {ready_entities}/{len(entity_sql_status)}")
    print(f"      Entity SQL drafts: {len(entity_sql_status) - ready_entities}")
    return generated_paths
