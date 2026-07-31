"""Master API router — every module registers exactly once here."""

from fastapi import APIRouter

from app.modules.activity.api import router as activity_router
from app.modules.documents.api import router as documents_router
from app.modules.emails.api import router as emails_router
from app.modules.favorites.api import router as favorites_router
from app.modules.files.api import router as files_router
from app.modules.media.api import router as media_router
from app.modules.search.api import router as search_router
from app.modules.tags.api import router as tags_router
from app.modules.users.api import auth_router, users_router
from app.modules.zoho.api import router as zoho_router
from app.modules.zoho.organizations.api import router as zoho_organizations_router
from app.modules.zoho.sync.api import router as zoho_sync_engine_router

from app.modules.zoho.auth.api import zoho_auth_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
# Zoho: specific sub-routers BEFORE the generic /zoho router (route priority)
api_router.include_router(zoho_auth_router, prefix="/zoho/auth", tags=["zoho:auth"])
api_router.include_router(zoho_organizations_router, prefix="/zoho/organizations", tags=["zoho:organizations"])
api_router.include_router(zoho_sync_engine_router, prefix="/zoho/sync-engine", tags=["zoho:sync-engine"])
api_router.include_router(zoho_router, prefix="/zoho", tags=["zoho"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(files_router, prefix="/files", tags=["files"])
api_router.include_router(favorites_router, prefix="/favorites", tags=["favorites"])
api_router.include_router(tags_router, prefix="/tags", tags=["tags"])
api_router.include_router(emails_router, prefix="/emails", tags=["emails"])
api_router.include_router(media_router, prefix="/media", tags=["media"])
api_router.include_router(activity_router, prefix="/activity", tags=["activity"])
api_router.include_router(search_router, prefix="/search", tags=["search"])
