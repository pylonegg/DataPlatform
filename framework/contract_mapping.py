"""Public API for exporting and validating S2T mapping metadata."""

from __future__ import annotations

if __package__:
    from framework._mapping_export import _write_yaml, export_workbook
    from framework._mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, REQUIRED_HEADERS, SOURCE_KIND,
        SUPPORTING_SHEETS,
    )
    from framework._mapping_utils import (
        mapping_value, safe_filename, unique_filename, unique_nested_filename,
    )
    from framework._mapping_validation import (
        _safe_manifest_path, _validate_artifact, validate_metadata_directory,
    )
    from framework._mapping_workbook import (
        _build_metadata, _entity_type, _is_empty, _mapping_warning,
        _read_headers, _read_optional_headers, _read_supporting_sheet,
    )
else:
    from _mapping_export import _write_yaml, export_workbook
    from _mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, REQUIRED_HEADERS, SOURCE_KIND,
        SUPPORTING_SHEETS,
    )
    from _mapping_utils import (
        mapping_value, safe_filename, unique_filename, unique_nested_filename,
    )
    from _mapping_validation import (
        _safe_manifest_path, _validate_artifact, validate_metadata_directory,
    )
    from _mapping_workbook import (
        _build_metadata, _entity_type, _is_empty, _mapping_warning,
        _read_headers, _read_optional_headers, _read_supporting_sheet,
    )
