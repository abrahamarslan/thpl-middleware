import enum
from datetime import datetime
from sqlalchemy import String, Boolean, ForeignKey, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ENUM

from app.database.db import Base
from app.database.mixins import TimestampMixin, IntPKMixin

class SettingType(enum.Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"

class SettingContext(enum.Enum):
    GLOBAL = "global"
    TENANT = "tenant"
    USER = "user"


class SystemModule(IntPKMixin, Base):
    """Top-level domain representing an architectural module or microservice."""
    __tablename__ = 'system_modules'

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True) 
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True) 
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    groups: Mapped[list["SettingGroup"]] = relationship("SettingGroup", back_populates="module", cascade="all, delete-orphan")


class SettingGroup(IntPKMixin, Base):
    """Logical grouping of settings within a specific module."""
    __tablename__ = 'setting_groups'

    module_id: Mapped[int] = mapped_column(ForeignKey('system_modules.id', ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False) 
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Relationships
    module: Mapped["SystemModule"] = relationship("SystemModule", back_populates="groups")
    definitions: Mapped[list["SettingDefinition"]] = relationship("SettingDefinition", back_populates="group", cascade="all, delete-orphan")


class SettingDefinition(IntPKMixin, TimestampMixin, Base):
    """The master blueprint for a setting."""
    __tablename__ = 'setting_definitions'

    group_id: Mapped[int] = mapped_column(ForeignKey('setting_groups.id', ondelete="CASCADE"), nullable=False)
    
    # e.g. 'zoho.auth.refresh_token'
    key: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True) 
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    value_type: Mapped[SettingType] = mapped_column(ENUM(SettingType, name="setting_type_enum", create_type=False), nullable=False)
    default_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_overridable: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    group: Mapped["SettingGroup"] = relationship("SettingGroup", back_populates="definitions")
    values: Mapped[list["SettingValue"]] = relationship("SettingValue", back_populates="definition", cascade="all, delete-orphan")


class SettingValue(IntPKMixin, Base):
    """The contextual value (Global, Tenant, User)."""
    __tablename__ = 'setting_values'

    definition_id: Mapped[int] = mapped_column(ForeignKey('setting_definitions.id', ondelete="CASCADE"), nullable=False)
    
    context_type: Mapped[SettingContext] = mapped_column(ENUM(SettingContext, name="setting_context_enum", create_type=False), nullable=False, index=True)
    context_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True) 
    
    value: Mapped[str] = mapped_column(String(500), nullable=False) 
    
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    definition: Mapped["SettingDefinition"] = relationship("SettingDefinition", back_populates="values")


class SettingAuditLog(IntPKMixin, Base):
    """Immutable ledger of all setting changes."""
    __tablename__ = 'setting_audit_logs'

    setting_value_id: Mapped[int | None] = mapped_column(ForeignKey('setting_values.id', ondelete="SET NULL"), nullable=True)
    
    # Denormalized for fast querying without heavy JOINs
    module_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True) 
    definition_key: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    
    context_type: Mapped[SettingContext] = mapped_column(ENUM(SettingContext, name="setting_context_enum", create_type=False), nullable=False)
    context_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    old_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    new_value: Mapped[str] = mapped_column(String(500), nullable=False)
    
    changed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
