from pydantic import BaseModel, Field
from typing import Any
from datetime import datetime
from app.modules.system.model import SettingType, SettingContext

class SettingValueCreate(BaseModel):
    value: str
    context_type: SettingContext = SettingContext.GLOBAL
    context_id: str | None = None
    
class SettingValueOut(BaseModel):
    id: int
    context_type: SettingContext
    context_id: str | None
    value: str
    updated_by: str
    updated_at: datetime
    
    class Config:
        from_attributes = True

class SettingDefinitionOut(BaseModel):
    id: int
    key: str
    name: str
    description: str | None
    value_type: SettingType
    default_value: str | None
    is_sensitive: bool
    is_overridable: bool
    
    class Config:
        from_attributes = True
