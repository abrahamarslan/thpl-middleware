"""Seed this deployment's tenant and its root organization.

``run_seed_company`` is idempotent and safe to re-run: it creates or updates

  * the tenant ``COMPANY_TENANT_CODE`` (name, timezone, locale, contact email);
  * its root organization ``COMPANY_ORGANIZATION_CODE`` — a ``legal_entity``
    whose profile / address / tax fields come from the ``COMPANY_*`` settings,
    with the fields the model has no column for (bank account, secondary phone)
    kept in ``custom_attributes``;
  * the organization's system roles (owner / admin / member);
  * an admin user (``COMPANY_ADMIN_*``) bound to ``COMPANY_ADMIN_ROLE``.

Everything is configured in ``app/core/conf.py`` / ``.env``. Point
``DEFAULT_TENANT_CODE`` / ``DEFAULT_ORGANIZATION_CODE`` at the two codes above
so rows written without a tenant/organization context are scoped to them
(app/database/tenancy.py).

Called by ``scripts/seed.py``; also runnable on its own::

    python scripts/seed.py --only company
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.conf import settings
from app.database.tenancy import clear_default_cache, system_actor, tenant_scope
from app.modules.organizations.model import Organization
from app.modules.roles.model import Role
from app.modules.roles.service import seed_system_roles
from app.modules.tenants.enums import OrganizationType
from app.modules.tenants.model import Tenant
from app.modules.users.model import User
from app.modules.users.password_policy import validate_password
from app.modules.users.security import hash_password, verify_password

logger = structlog.get_logger("app.tenants.seed")


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """The tenant + organization to seed, sourced from the COMPANY_* settings."""

    tenant_code: str
    tenant_name: str
    timezone: str
    locale: str
    org_code: str
    legal_name: str
    trading_name: str
    display_name: str
    address_line_one: str
    address_line_two: str
    country: str
    gstin: str
    phone_one: str
    phone_two: str
    bank_name: str
    account_number: str
    ifsc_code: str
    phone: str
    email: str
    website: str
    admin_name: str
    admin_email: str
    admin_username: str
    admin_password: str
    admin_role: str

    @classmethod
    def from_settings(cls) -> CompanyProfile:
        return cls(
            tenant_code=settings.COMPANY_TENANT_CODE,
            tenant_name=settings.COMPANY_TENANT_NAME or settings.COMPANY_NAME,
            timezone=settings.COMPANY_TIMEZONE,
            locale=settings.COMPANY_LOCALE,
            org_code=settings.COMPANY_ORGANIZATION_CODE,
            legal_name=settings.COMPANY_LEGAL_NAME or settings.COMPANY_NAME,
            trading_name=settings.COMPANY_TRADING_NAME,
            display_name=settings.COMPANY_NAME or settings.COMPANY_LEGAL_NAME,
            address_line_one=settings.COMPANY_ADDRESS_LINE_ONE,
            address_line_two=settings.COMPANY_ADDRESS_LINE_TWO,
            country=settings.COMPANY_COUNTRY,
            gstin=settings.COMPANY_GSTIN,
            phone_one=settings.COMPANY_PHONE_ONE,
            phone_two=settings.COMPANY_PHONE_TWO,
            bank_name=settings.COMPANY_BANK_NAME,
            account_number=settings.COMPANY_ACCOUNT_NUMBER,
            ifsc_code=settings.COMPANY_IFSC_CODE,
            phone=settings.COMPANY_PHONE,
            email=settings.COMPANY_EMAIL,
            website=settings.COMPANY_WEBSITE,
            admin_name=settings.COMPANY_ADMIN_NAME,
            admin_email=settings.COMPANY_ADMIN_EMAIL or settings.COMPANY_EMAIL,
            admin_username=settings.COMPANY_ADMIN_USERNAME,
            admin_password=settings.COMPANY_ADMIN_PASSWORD,
            admin_role=settings.COMPANY_ADMIN_ROLE or "owner",
        )


def _custom_attributes(p: CompanyProfile) -> dict:
    """Fields the organization model has no column for."""
    custom: dict = {}
    phones = {"primary": p.phone_one or p.phone, "secondary": p.phone_two}
    phones = {k: v for k, v in phones.items() if v}
    if phones:
        custom["phones"] = phones
    bank = {"name": p.bank_name, "account_number": p.account_number, "ifsc": p.ifsc_code}
    bank = {k: v for k, v in bank.items() if v}
    if bank:
        custom["bank"] = bank
    return custom


async def _upsert_tenant(db: AsyncSession, p: CompanyProfile) -> tuple[Tenant, bool]:
    tenant = await db.scalar(select(Tenant).where(Tenant.tenant_code == p.tenant_code))
    created = tenant is None
    if tenant is None:
        tenant = Tenant(
            tenant_code=p.tenant_code,
            name=p.tenant_name,
            timezone=p.timezone,
            locale=p.locale,
            primary_contact_email=p.email or "admin@localhost",
            status="active",
            is_verified=True,
        )
        db.add(tenant)
    else:
        tenant.name = p.tenant_name
        tenant.timezone = p.timezone
        tenant.locale = p.locale
        if p.email:
            tenant.primary_contact_email = p.email
    await db.flush()
    return tenant, created


#: The placeholder organization migration ``fdbf62102e86`` creates for a tenant
#: that has none, so ``users``/``roles`` had somewhere to land when they became
#: organization-scoped. It is a scaffold, not a company.
_MIGRATION_PLACEHOLDER = "DEFAULT-HQ"


async def _upsert_organization(db: AsyncSession, p: CompanyProfile, *, actor_id: int | None) -> tuple[Organization, bool]:
    org = await db.scalar(select(Organization).where(Organization.org_code == p.org_code))
    if org is None:
        # Adopt the migration's placeholder rather than adding a second row
        # beside it. A freshly migrated database has exactly one organization
        # and it is a scaffold; creating the real company next to it would
        # leave the tenant with two, which is the state that makes every
        # "which organization?" fallback ambiguous for good.
        # Runs inside tenant_scope, so the tenancy filter confines this to the
        # tenant being seeded.
        placeholder = await db.scalar(
            select(Organization).where(Organization.org_code == _MIGRATION_PLACEHOLDER)
        )
        if placeholder is not None:
            logger.info("tenants.seed_adopted_placeholder", from_code=_MIGRATION_PLACEHOLDER,
                        to_code=p.org_code, org_id=placeholder.id)
            placeholder.org_code = p.org_code
            placeholder.org_type = OrganizationType.LEGAL_ENTITY.value
            org = placeholder
    custom = _custom_attributes(p)
    if org is None:
        from app.modules.organizations import service as org_service
        from app.modules.organizations.schema import OrganizationCreate

        org = await org_service.create_organization(
            db,
            OrganizationCreate(
                org_code=p.org_code,
                legal_name=p.legal_name,
                org_type=OrganizationType.LEGAL_ENTITY,
                trading_name=p.trading_name or None,
                tax_id=p.gstin or None,
                timezone=p.timezone,
                custom_attributes=custom,
                name=p.display_name or None,
                email=p.email or None,
                phone=p.phone_one or p.phone or None,
                website=p.website or None,
                address_street1=p.address_line_one or None,
                address_street2=p.address_line_two or None,
                address_country=p.country or None,
            ),
            actor_id=actor_id,
        )
        _claim_zoho_identity(org)
        await db.flush()
        return org, True

    org.legal_name = p.legal_name
    org.trading_name = p.trading_name or None
    org.tax_id = p.gstin or None
    org.timezone = p.timezone
    org.name = p.display_name or None
    if p.email:
        org.email = p.email
    org.phone = p.phone_one or p.phone or None
    org.website = p.website or None
    org.address_street1 = p.address_line_one or None
    org.address_street2 = p.address_line_two or None
    org.address_country = p.country or None
    org.custom_attributes = {**(org.custom_attributes or {}), **custom}
    _claim_zoho_identity(org)
    await db.flush()
    return org, False


def _claim_zoho_identity(org: Organization) -> None:
    """The company's organization IS the Zoho organization.

    Stamping ``ZOHO_ORGANIZATION_ID`` here means the organizations sync finds
    this row through the crosswalk's identity and *updates* it, instead of
    creating a parallel ``ZOHO-<id>`` node beside it. Without this the
    deployment ends up with two organizations for one company — the seeded one
    that every app write uses, and the synced one that every Zoho write uses —
    which is redesign open decision #1 answered the wrong way round.

    Only ever set, never changed: if the row already names a different Zoho
    organization, that is a real conflict for a human, not something to
    overwrite during a seed.
    """
    zoho_organization_id = (settings.ZOHO_ORGANIZATION_ID or "").strip()
    if not zoho_organization_id or org.zoho_id == zoho_organization_id:
        return
    if org.zoho_id:
        logger.warning(
            "tenants.seed_zoho_id_conflict", org_code=org.org_code,
            stored=org.zoho_id, configured=zoho_organization_id,
            action="left as is; change ZOHO_ORGANIZATION_ID or the organization by hand",
        )
        return
    org.zoho_id = zoho_organization_id
    logger.info("tenants.seed_zoho_id_claimed", org_code=org.org_code, zoho_id=zoho_organization_id)


async def _ensure_roles(db: AsyncSession, org: Organization) -> dict[str, Role]:
    """Ensure the system roles (owner/admin/member) exist for the organization."""
    await seed_system_roles(db, org.id)
    roles = (await db.scalars(select(Role).where(Role.organization_id == org.id))).all()
    return {role.code: role for role in roles}


async def _upsert_admin_user(
    db: AsyncSession, p: CompanyProfile, org: Organization, roles: dict[str, Role],
) -> tuple[User | None, bool]:
    """Create/update the admin user and bind it to the organization's role.

    Skipped (returns ``None``) when no password is configured, so the tenant and
    organization still seed. The configured password is authoritative: an
    existing user whose stored password no longer matches is reset to it.
    """
    email = (p.admin_email or p.email).strip().lower()
    if not email or not p.admin_password:
        logger.warning("tenants.seed_admin_skipped", reason="COMPANY_ADMIN_PASSWORD (or email) is empty")
        return None, False
    role = roles.get(p.admin_role)
    if role is None:
        raise ValueError(
            f"COMPANY_ADMIN_ROLE '{p.admin_role}' is not a role of organization '{org.org_code}' "
            f"(have: {', '.join(sorted(roles))})"
        )

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    created = user is None
    if created:
        validate_password(p.admin_password, email=email, name=p.admin_name)
        user = User(
            name=p.admin_name,
            email=email,
            username=p.admin_username or None,
            password=hash_password(p.admin_password),
            role_id=role.id,
            organization_id=org.id,
            user_type="admin",
            status="active",
            user_status="active",
            is_verified=True,
            email_verified_at=datetime.now(UTC),
            last_password_change_at=datetime.now(UTC),
            country_code="IN",
            timezone=p.timezone,
            currency="INR",
            language="en",
        )
        db.add(user)
    else:
        user.name = p.admin_name
        user.organization_id = org.id
        user.role_id = role.id
        user.user_type = user.user_type or "admin"
        user.status = "active"
        user.user_status = "active"
        user.is_deactivated = False
        if p.admin_username:
            user.username = p.admin_username
        if not verify_password(p.admin_password, user.password):
            validate_password(p.admin_password, email=email, name=p.admin_name)
            user.password = hash_password(p.admin_password)
            user.last_password_change_at = datetime.now(UTC)
    await db.flush()
    return user, created


async def seed_tenant_and_organization(
    db: AsyncSession, profile: CompanyProfile | None = None, *, actor_id: int | None = None,
) -> dict:
    """Create/update the tenant, its root organization, system roles and admin user."""
    p = profile or CompanyProfile.from_settings()
    tenant, tenant_created = await _upsert_tenant(db, p)
    with tenant_scope(tenant.id, actor=system_actor("seed")):
        org, org_created = await _upsert_organization(db, p, actor_id=actor_id)
        roles = await _ensure_roles(db, org)
        admin_user, admin_created = await _upsert_admin_user(db, p, org, roles)
    clear_default_cache()
    logger.info(
        "tenants.seeded", tenant_id=tenant.id, tenant_code=tenant.tenant_code, tenant_created=tenant_created,
        org_id=org.id, org_code=org.org_code, org_created=org_created,
        admin_user_id=admin_user.id if admin_user else None, admin_created=admin_created,
        roles=sorted(roles),
    )
    return {
        "tenant": tenant,
        "organization": org,
        "tenant_created": tenant_created,
        "organization_created": org_created,
        "roles": roles,
        "admin_user": admin_user,
        "admin_user_created": admin_created,
    }


def _async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def run_seed_company(database_url: str | None = None, profile: CompanyProfile | None = None) -> dict:
    """Standalone async entry point (own engine, own transaction)."""
    engine = create_async_engine(_async_url(database_url or settings.DATABASE_URL), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await seed_tenant_and_organization(db, profile)
            await db.commit()
    finally:
        await engine.dispose()
    return result
