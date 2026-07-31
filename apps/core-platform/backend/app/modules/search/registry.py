"""Searchable-entity registry — the single place a table becomes searchable.

Each entry declares, for one Meilisearch index (named after the mirror
table), everything the search stack needs:

  - which SQLAlchemy model hydrates hits (ScoutBuilder, soft-delete aware);
  - which Pydantic schema serializes hydrated rows in API responses;
  - the Meilisearch index settings (searchable / filterable / sortable
    attributes). Meilisearch REJECTS filters on undeclared attributes, so
    ``ensure_index_settings()`` must run before the first filtered query —
    the indexer applies it on startup, idempotently.

Adding a searchable entity is three steps:
  1. add the table's topic to SEARCH_CDC_TOPICS (deployment .env) and to
     Debezium's ``table.include.list``;
  2. register a SearchableEntity below;
  3. that's it — the indexer bootstraps the index settings, the generic
     /api/search/{index} endpoint serves it.
"""

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger("app.search.registry")


@dataclass(frozen=True)
class SearchableEntity:
    """Declarative search config for one mirror table / Meili index."""

    index_name: str                      # == __tablename__ == Kafka topic suffix
    model_path: tuple[str, str]          # (module, attr) — lazy import, keeps this file model-free
    schema_path: tuple[str, str]         # (module, attr) — response DTO for hydrated rows
    searchable: list[str] = field(default_factory=list)   # ranked, in priority order
    filterable: list[str] = field(default_factory=list)
    sortable: list[str] = field(default_factory=list)

    def resolve_model(self) -> type:
        import importlib

        module = importlib.import_module(self.model_path[0])
        return getattr(module, self.model_path[1])

    def resolve_schema(self) -> type:
        import importlib

        module = importlib.import_module(self.schema_path[0])
        return getattr(module, self.schema_path[1])


#: index name -> config. Extend when a new mirror table becomes searchable.
SEARCHABLE_ENTITIES: dict[str, SearchableEntity] = {
    "zoho_organizations": SearchableEntity(
        index_name="zoho_organizations",
        model_path=("app.modules.zoho.organizations.model", "ZohoOrganization"),
        schema_path=("app.modules.zoho.organizations.schema", "OrganizationOut"),
        searchable=[
            "name",
            "contact_name",
            "email",
            "phone",
            "website",
            "address_city",
            "address_state",
            "address_country",
        ],
        filterable=[
            "address_country",
            "address_state",
            "address_city",
            "industry_type",
            "is_org_active",
            "currency_code",
            "sync_status",
        ],
        sortable=["name", "account_created_date"],
    ),
}


async def ensure_index_settings(meili) -> None:
    """Idempotently push declared settings to Meilisearch for every entity.

    Runs on indexer startup. Updating settings on a missing index creates it,
    so first boot works on an empty Meilisearch too. Settings tasks are
    async server-side; we don't wait — queries issued before completion fall
    back to previous settings rather than failing.
    """
    for entity in SEARCHABLE_ENTITIES.values():
        index = meili.index(entity.index_name)
        if entity.searchable:
            await index.update_searchable_attributes(entity.searchable)
        if entity.filterable:
            await index.update_filterable_attributes(entity.filterable)
        if entity.sortable:
            await index.update_sortable_attributes(entity.sortable)
        logger.info(
            "search_index_settings_applied",
            index=entity.index_name,
            searchable=len(entity.searchable),
            filterable=len(entity.filterable),
            sortable=len(entity.sortable),
        )
