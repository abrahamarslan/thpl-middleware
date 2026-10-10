"""Master API router — every module registers exactly once here."""

from fastapi import APIRouter

from app.modules.accounting.api import router as accounting_router
from app.modules.price_lists.api import router as price_lists_router
from app.modules.parties.api import router as parties_router
from app.modules.catalogue.api_masters import router as catalogue_masters_router
from app.modules.activity.api import router as activity_router
from app.modules.brands.api import router as brands_router
from app.modules.categories.api import (
    categories_router,
    categorizables_router,
    taxonomies_router,
)
from app.modules.comments.api import router as comments_router
from app.modules.currencies.api import router as currencies_router
from app.modules.custom_fields.api import router as custom_fields_router
from app.modules.documents.api import router as documents_router
from app.modules.emails.api import router as emails_router
from app.modules.entities.api import router as entities_router
from app.modules.favorites.api import router as favorites_router
from app.modules.compliance.api import router as compliance_me_router
from app.modules.fieldops.api import router as fieldops_router
from app.modules.fieldops.api_me import auth_alias_router as fieldops_auth_alias_router
from app.modules.fieldops.api_me import router as fieldops_me_router
from app.modules.files.api import router as files_router
from app.modules.fleet_partners.api import router as fleet_partners_router
from app.modules.geo.api import (
    addresses_router,
    boundaries_router,
    geofences_router,
    places_router,
)
from app.modules.geo.geocoding.api import router as geocoding_router
from app.modules.hr.api import router as hr_router
from app.modules.hubs.api import router as hubs_router
from app.modules.locations.api import router as zoho_locations_router
from app.modules.manufacturers.api import router as manufacturers_router
from app.modules.organizations.api import router as organizations_router
from app.modules.rbac.api import (
    me_router as rbac_me_router,
    permissions_router,
    user_roles_router,
)
from app.modules.roles.api import router as roles_router
from app.modules.search.api import router as search_router
from app.modules.tags.api import router as tags_router
from app.modules.teams.api import (
    departments_router,
    job_titles_router,
    me_teams_router,
    team_roles_router,
    team_types_router,
    teams_router,
)
from app.modules.tenants.api import router as tenants_router
from app.modules.resolution.api import router as resolution_router
from app.modules.taxes.api import router as taxes_router
from app.modules.users.api import auth_router, countries_router, me_router, users_router
from app.modules.vehicles.api import driving_licenses_router, vehicles_router
from app.modules.zoho.admin.api import router as zoho_admin_router
from app.modules.zoho.api import router as zoho_router
from app.modules.zoho.auth.api import zoho_auth_router
from app.modules.zoho.sync.api import router as zoho_sync_engine_router
from app.modules.zoho_users.api import router as zoho_users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(me_router, prefix="/me", tags=["me"])
api_router.include_router(countries_router, prefix="/countries", tags=["countries"])
api_router.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
api_router.include_router(organizations_router, prefix="/organizations", tags=["organizations"])
# Canonical currency master (schema `currency`). /api/zoho/currencies further down
# is the read-only Zoho mirror: different thing, different prefix.
api_router.include_router(currencies_router, prefix="/currencies", tags=["currencies"])
api_router.include_router(brands_router, prefix="/brands", tags=["brands"])
api_router.include_router(manufacturers_router, prefix="/manufacturers", tags=["manufacturers"])
api_router.include_router(taxonomies_router, prefix="/taxonomies", tags=["taxonomies"])
api_router.include_router(categories_router, prefix="/categories", tags=["categories"])
api_router.include_router(categorizables_router, prefix="/categorizables", tags=["categorizables"])
api_router.include_router(entities_router, prefix="/entities", tags=["entities"])
api_router.include_router(comments_router, prefix="/comments", tags=["comments"])
api_router.include_router(custom_fields_router, prefix="/custom-fields", tags=["custom-fields"])
api_router.include_router(roles_router, prefix="/roles", tags=["roles"])
# RBAC (docs/rbac-module.md): the catalogue, my effective permissions, and a user's role assignments.
api_router.include_router(permissions_router, prefix="/permissions", tags=["rbac"])
api_router.include_router(rbac_me_router, prefix="/me", tags=["rbac"])
api_router.include_router(user_roles_router, prefix="/users", tags=["rbac"])
# Teams: departments, job titles, team types/roles, teams and their members; hr: employment and the org chart.
api_router.include_router(departments_router, prefix="/departments", tags=["teams"])
api_router.include_router(job_titles_router, prefix="/job-titles", tags=["teams"])
api_router.include_router(team_types_router, prefix="/team-types", tags=["teams"])
api_router.include_router(team_roles_router, prefix="/team-roles", tags=["teams"])
api_router.include_router(teams_router, prefix="/teams", tags=["teams"])
api_router.include_router(me_teams_router, prefix="/me", tags=["teams"])
api_router.include_router(hr_router, prefix="/hr", tags=["hr"])
# Location hub — our own places and addresses. /api/zoho/locations further
# down is the read-only Zoho warehouse mirror: different thing, different prefix.
api_router.include_router(places_router, prefix="/locations", tags=["locations"])
api_router.include_router(addresses_router, prefix="/addresses", tags=["addresses"])
api_router.include_router(geofences_router, prefix="/geofences", tags=["geofences"])
api_router.include_router(boundaries_router, prefix="/admin-boundaries", tags=["admin-boundaries"])
api_router.include_router(geocoding_router, prefix="/geocoding", tags=["geocoding"])
# Zoho: specific sub-routers BEFORE the generic /zoho router (route priority)
api_router.include_router(zoho_auth_router, prefix="/zoho/auth", tags=["zoho:auth"])
api_router.include_router(taxes_router, prefix="/taxes", tags=["taxes"])
api_router.include_router(accounting_router, prefix="/accounting", tags=["accounting"])
api_router.include_router(price_lists_router, prefix="/price-lists", tags=["price-lists"])
api_router.include_router(parties_router, prefix="/parties", tags=["parties"])
api_router.include_router(catalogue_masters_router, prefix="/catalogue", tags=["catalogue"])
api_router.include_router(resolution_router, prefix="/resolution", tags=["resolution"])
api_router.include_router(zoho_locations_router, prefix="/zoho/locations", tags=["zoho:locations"])
api_router.include_router(zoho_users_router, prefix="/zoho/users", tags=["zoho:users"])
api_router.include_router(zoho_sync_engine_router, prefix="/zoho/sync-engine", tags=["zoho:sync-engine"])
api_router.include_router(zoho_admin_router, prefix="/zoho/admin", tags=["zoho:admin"])
api_router.include_router(zoho_router, prefix="/zoho", tags=["zoho"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(files_router, prefix="/files", tags=["files"])
api_router.include_router(favorites_router, prefix="/favorites", tags=["favorites"])
api_router.include_router(tags_router, prefix="/tags", tags=["tags"])
api_router.include_router(emails_router, prefix="/emails", tags=["emails"])
# Media has no generic upload surface: images enter through their owner's own
# endpoint (e.g. POST /api/me/avatar), which validates the owner. The
# unauthenticated public serving router is mounted at the app root — see
# core/registrar.py and modules/media/public_api.py.
api_router.include_router(activity_router, prefix="/activity", tags=["activity"])
api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(hubs_router, prefix="/hubs", tags=["hubs"])
api_router.include_router(fleet_partners_router, prefix="/fleet-partners", tags=["fleet-partners"])
api_router.include_router(vehicles_router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(driving_licenses_router, prefix="/driving-licenses", tags=["driving-licenses"])
# Field operations (docs/fieldops/): the field app's own shifts/visits/location under /me, the
# managers' side under /fieldops. /api/auth/me/location is the historical alias of /api/me/location.
api_router.include_router(compliance_me_router, prefix="/me/consents", tags=["compliance"])
api_router.include_router(fieldops_me_router, prefix="/me", tags=["fieldops"])
api_router.include_router(fieldops_auth_alias_router, prefix="/auth", tags=["fieldops"])
api_router.include_router(fieldops_router, prefix="/fieldops", tags=["fieldops"])
