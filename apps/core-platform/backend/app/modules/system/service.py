import json
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system.model import (
    SystemModule, SettingGroup, SettingDefinition, SettingValue, 
    SettingAuditLog, SettingType, SettingContext
)

class SystemSettingsService:
    async def get_setting(self, db: AsyncSession, key: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None) -> Any:
        """Resolve a setting taking hierarchy into account: User -> Tenant -> Global -> Default."""
        
        # 1. Fetch the definition
        stmt = select(SettingDefinition).where(SettingDefinition.key == key)
        definition = await db.scalar(stmt)
        if not definition:
            return None
            
        # 2. Try to fetch the specific context value
        val_stmt = select(SettingValue).where(SettingValue.definition_id == definition.id)
        
        # We need to load all relevant overrides to resolve the hierarchy
        values = (await db.scalars(val_stmt)).all()
        
        resolved_value_str = definition.default_value
        
        # Build a hierarchy map
        val_map = { (v.context_type, v.context_id): v.value for v in values }
        
        # Hierarchy resolution
        if context == SettingContext.USER and context_id:
            if (SettingContext.USER, context_id) in val_map:
                resolved_value_str = val_map[(SettingContext.USER, context_id)]
            elif (SettingContext.TENANT, None) in val_map: # Or pass tenant_id if available in a more complex setup
                resolved_value_str = val_map[(SettingContext.TENANT, None)]
            elif (SettingContext.GLOBAL, None) in val_map:
                resolved_value_str = val_map[(SettingContext.GLOBAL, None)]
        elif context == SettingContext.TENANT and context_id:
            if (SettingContext.TENANT, context_id) in val_map:
                resolved_value_str = val_map[(SettingContext.TENANT, context_id)]
            elif (SettingContext.GLOBAL, None) in val_map:
                resolved_value_str = val_map[(SettingContext.GLOBAL, None)]
        else: # GLOBAL
            if (SettingContext.GLOBAL, None) in val_map:
                resolved_value_str = val_map[(SettingContext.GLOBAL, None)]
                
        # Parse the value according to its type
        if resolved_value_str is None:
            return None
            
        return self._cast_value(resolved_value_str, definition.value_type)

    async def set_setting(self, db: AsyncSession, key: str, value: Any, updated_by: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None, ip_address: str | None = None) -> SettingValue:
        """Sets a setting value, auto-provisioning the hierarchy if necessary, and logs it."""
        
        # Auto-provision hierarchy
        parts = key.split('.')
        module_name = parts[0] if len(parts) > 0 else 'core'
        group_name = parts[1] if len(parts) > 1 else 'general'
        def_name = '.'.join(parts[2:]) if len(parts) > 2 else key
        
        # Module
        mod = await db.scalar(select(SystemModule).where(SystemModule.name == module_name))
        if not mod:
            mod = SystemModule(name=module_name, description=f"Auto-provisioned module: {module_name}")
            db.add(mod)
            await db.flush()
            
        # Group
        grp = await db.scalar(select(SettingGroup).where(SettingGroup.module_id == mod.id, SettingGroup.name == group_name))
        if not grp:
            grp = SettingGroup(module_id=mod.id, name=group_name, description=f"Auto-provisioned group: {group_name}")
            db.add(grp)
            await db.flush()
            
        # Definition
        definition = await db.scalar(select(SettingDefinition).where(SettingDefinition.key == key))
        
        # Infer type
        inferred_type = self._infer_type(value)
        str_value = self._stringify_value(value)
        
        if not definition:
            definition = SettingDefinition(
                group_id=grp.id,
                key=key,
                name=def_name,
                value_type=inferred_type,
                default_value=str_value
            )
            db.add(definition)
            await db.flush()
            
        # Upsert the value
        val_stmt = select(SettingValue).where(
            SettingValue.definition_id == definition.id,
            SettingValue.context_type == context,
            SettingValue.context_id == context_id
        )
        setting_val = await db.scalar(val_stmt)
        
        old_val_str = None
        if setting_val:
            old_val_str = setting_val.value
            setting_val.value = str_value
            setting_val.updated_by = updated_by
        else:
            setting_val = SettingValue(
                definition_id=definition.id,
                context_type=context,
                context_id=context_id,
                value=str_value,
                updated_by=updated_by
            )
            db.add(setting_val)
            
        await db.flush()
        
        # Audit Log
        if old_val_str != str_value:
            audit = SettingAuditLog(
                setting_value_id=setting_val.id,
                module_name=mod.name,
                definition_key=key,
                context_type=context,
                context_id=context_id,
                old_value=old_val_str,
                new_value=str_value,
                changed_by=updated_by,
                ip_address=ip_address
            )
            db.add(audit)
            
        return setting_val

    def _infer_type(self, value: Any) -> SettingType:
        if isinstance(value, bool):
            return SettingType.BOOLEAN
        elif isinstance(value, int):
            return SettingType.INTEGER
        elif isinstance(value, float):
            return SettingType.FLOAT
        elif isinstance(value, (dict, list)):
            return SettingType.JSON
        return SettingType.STRING
        
    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        elif isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
        
    def _cast_value(self, str_val: str, val_type: SettingType) -> Any:
        if val_type == SettingType.BOOLEAN:
            return str_val.lower() == "true"
        elif val_type == SettingType.INTEGER:
            return int(str_val)
        elif val_type == SettingType.FLOAT:
            return float(str_val)
        elif val_type == SettingType.JSON:
            return json.loads(str_val)
        return str_val

    async def delete_setting(self, db: AsyncSession, key: str, context: SettingContext = SettingContext.GLOBAL, context_id: str | None = None) -> bool:
        """Deletes a contextual setting value (does not delete the definition)."""
        definition = await db.scalar(select(SettingDefinition).where(SettingDefinition.key == key))
        if not definition:
            return False
            
        stmt = select(SettingValue).where(
            SettingValue.definition_id == definition.id,
            SettingValue.context_type == context,
            SettingValue.context_id == context_id
        )
        val = await db.scalar(stmt)
        if val:
            await db.delete(val)
            await db.flush()
            return True
        return False

system_settings_service = SystemSettingsService()
