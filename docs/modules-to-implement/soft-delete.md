Soft Delete Implementation

1. **The Unique Constraint Problem:** If a user with `test@email.com` is soft-deleted, a new user cannot register with `test@email.com` because a standard unique constraint will throw an `IntegrityError`.
2. **The Relationship Cascade Bug:** If you call `session.delete(user)`, SQLAlchemy will either hard-delete related records (like Posts/Orders) or nullify their foreign keys, which destroys the integrity of your soft-deleted data.
3. **Asynchronous I/O:** Enterprise FastAPI apps use `AsyncSession` to handle thousands of concurrent requests, meaning the repository must be fully async.

Here is the production-ready, fully asynchronous architecture that solves all three.

## 1. The Core Database & Mixin

We define our mixin using SQLAlchemy 2.0 type hinting. Notice that we rely exclusively on modifying the `deleted_at` timestamp. **We never call the ORM's actual `.delete()` method.**

```python
# core/database.py
from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), 
        default=None, 
        nullable=True
    )

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        
    def restore(self) -> None:
        self.deleted_at = None

```

## 2. Solving the Unique Constraint (Partial Indexes)

Instead of a standard `unique=True` column flag, enterprise applications use a **Partial Index**. This tells the database (like Postgres or SQLite) to only enforce uniqueness on rows where `deleted_at IS NULL`.

This allows you to have ten soft-deleted users with `test@email.com`, but only one *active* user with that email.

```python
# modules/user/models.py
from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base, SoftDeleteMixin

class User(SoftDeleteMixin, Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    
    # Relationships will not be nullified because we never call session.delete()
    # products: Mapped[list["Product"]] = relationship(back_populates="user")

    __table_args__ = (
        # Enterprise Fix: Unique constraint only applies to active records
        Index(
            "ix_users_email_unique", 
            "email", 
            unique=True, 
            # Use postgresql_where for Postgres, or sqlite_where for SQLite
            postgresql_where=text("deleted_at IS NULL") 
        ),
    )

```

## 3. The Async Event Listener (Targeting SELECTs Only)

Even when using `AsyncSession`, SQLAlchemy event listeners bind to the synchronous `Session` object under the hood.

We must explicitly check `execute_state.is_select` to ensure we don't accidentally intercept `UPDATE` or `INSERT` statements, which can cause subtle bugs.

```python
# core/events.py
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from core.database import SoftDeleteMixin

@event.listens_for(Session, "do_orm_execute")
def _add_soft_delete_filter(execute_state):
    # 1. Only intercept SELECT queries (ignore inserts/updates)
    if not execute_state.is_select:
        return
        
    # 2. Check if the query explicitly requested trashed items
    if execute_state.execution_options.get("include_deleted", False):
        return

    # 3. Apply the global filter to all models inheriting SoftDeleteMixin
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            SoftDeleteMixin,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        )
    )

```

## 4. The Async Generic Repository

This is the engine of the application. It uses Python's `TypeVar` to provide fully typed, asynchronous CRUD operations for every model in your system.

```python
# core/repository.py
from typing import Generic, TypeVar, Type, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import Base

ModelType = TypeVar("ModelType", bound=Base)

class CRUDBase(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: int) -> ModelType | None:
        # Automatically respects the event listener (hides deleted)
        return await db.get(self.model, id)

    async def get_trashed(self, db: AsyncSession) -> Sequence[ModelType]:
        """Fetches ONLY soft-deleted records."""
        stmt = (
            select(self.model)
            .where(self.model.deleted_at.is_not(None))
            .execution_options(include_deleted=True)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def soft_delete(self, db: AsyncSession, *, id: int) -> ModelType | None:
        obj = await self.get(db, id)
        if obj and hasattr(obj, "soft_delete"):
            obj.soft_delete()
            # We strictly commit the UPDATE. We avoid db.delete(obj) to protect relationships.
            await db.commit()
            await db.refresh(obj)
        return obj

    async def restore(self, db: AsyncSession, *, id: int) -> ModelType | None:
        # We must pass include_deleted=True to find the record in order to restore it
        stmt = select(self.model).where(self.model.id == id).execution_options(include_deleted=True)
        result = await db.execute(stmt)
        obj = result.scalar_one_or_none()
        
        if obj and hasattr(obj, "restore"):
            obj.restore()
            await db.commit()
            await db.refresh(obj)
        return obj

```

## 5. Clean, Modular FastAPI Routers

With the complexity handled in the core, your individual modules just instantiate the repository and call the async methods.

```python
# modules/user/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.dependencies import get_async_db
from core.repository import CRUDBase
from modules.user.models import User

router = APIRouter(prefix="/users", tags=["users"])
user_repo = CRUDBase[User](User)

@router.delete("/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    user = await user_repo.soft_delete(db=db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User soft deleted successfully"}

@router.post("/{user_id}/restore")
async def restore_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    user = await user_repo.restore(db=db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found in trash")
    return {"message": "User restored successfully"}

```