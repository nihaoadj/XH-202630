"""Public component registry and pure-data adapters."""

from app.core.courseware.components.catalog import (
    CATALOG_V1,
    ComponentDefinition,
    component_asset_matrix,
    component_definition,
    is_registered_component,
    migrate_component_payload,
    validate_component_payload,
)

__all__ = [
    "CATALOG_V1", "ComponentDefinition", "component_asset_matrix",
    "component_definition", "is_registered_component", "migrate_component_payload", "validate_component_payload",
]
