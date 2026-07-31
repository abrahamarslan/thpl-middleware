This is a perfect example of a cross-cutting module. The original Laravel implementation relies on global state (e.g., `auth()->id()` inside the model) which is an **anti-pattern in asynchronous Python (FastAPI)**. In async applications, the context (like the current user) must flow explicitly through the request lifecycle to avoid thread/context leaking.

Furthermore, we need to apply the same enterprise design choices we used for Tags and Documents:

1. **Universal Primary Keys:** `favoriteable_id` MUST be a `String` in the database to accommodate entities that use UUIDs (like Documents/Emails) and entities that use Integers (like Users/Products).
2. **Database-Level Uniqueness:** We must prevent a user from favoriting the same item in the same collection twice. We will enforce this using a composite `UniqueConstraint`. We will default `collection_name` to `"default"` to make the uniqueness constraint bulletproof (standard Postgres treats `NULL` values as distinct, which can cause duplicate bugs).
3. **Audit Trail:** Favoriting an item is an explicit user action that should automatically integrate with the `activity` module.

Here is the complete, comprehensive enterprise implementation.

---

### 1. The Model Layer (`app/modules/favorites/model.py`)

```python
from sqlalchemy import Column, String, Integer, Text, ForeignKey, UniqueConstraint
from app.database.db import Base
from app.database.mixins import TimestampMixin, SoftDeleteMixin, IntPKMixin

class Favorite(TimestampMixin, SoftDeleteMixin, IntPKMixin, Base):
    __tablename__ = "favorites"

    # User who owns the favorite
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    # Polymorphic Association (What is being favorited)
    favoriteable_id = Column(String, index=True, nullable=False)
    favoriteable_type = Column(String, index=True, nullable=False)

    # Organization & Metadata
    collection_name = Column(String, default="default", index=True, nullable=False, comment="Grouping of favorites")
    notes = Column(Text, nullable=True, comment="Optional user notes for this favorite")

    # Enforce uniqueness: A user can only favorite a specific entity once per collection
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'favoriteable_id', 'favoriteable_type', 'collection_name',
            name='uq_user_entity_collection_favorite'
        ),
    )

```

### 2. The Polymorphic Mixin (`app/modules/favorites/mixins.py`)

Add this to any model to instantly allow reverse-fetching (e.g., getting all favorites for a specific product to see how popular it is).

```python
from sqlalchemy import cast, String
from sqlalchemy.orm import relationship, declared_attr
from app.modules.favorites.model import Favorite

class FavoritableMixin:
    """
    Enterprise mixin to natively bind Favorites to any model.
    Read operations use eager loading (selectinload).
    Write operations must use the Favorite Service.
    """

    @declared_attr
    def favorited_by(cls):
        # Dynamically cast the local ID to string to join against favoriteable_id
        return relationship(
            "Favorite",
            primaryjoin=lambda: (
                cast(cls.id, String) == Favorite.favoriteable_id
            ) & (
                Favorite.favoriteable_type == cls.__name__
            ),
            foreign_keys=[Favorite.favoriteable_id],
            viewonly=True, # Read-only in ORM; mutate via Service explicitly
            cascade="all, delete"
        )

```

### 3. The Schema Layer (`app/modules/favorites/schema.py`)

```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime

class FavoriteBase(BaseModel):
    collection_name: str = Field(default="default", description="Optional grouping, e.g., 'Wishlist'")
    notes: Optional[str] = None

class FavoriteCreate(FavoriteBase):
    favoriteable_id: str
    favoriteable_type: str

class FavoriteUpdate(BaseModel):
    collection_name: Optional[str] = None
    notes: Optional[str] = None

class FavoriteOut(FavoriteBase):
    id: int
    favoriteable_id: str
    favoriteable_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class FavoriteToggleRequest(BaseModel):
    favoriteable_id: str
    favoriteable_type: str
    collection_name: str = "default"

```

### 4. The CRUD Layer (`app/modules/favorites/crud.py`)

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.modules.favorites.model import Favorite
from app.modules.favorites.schema import FavoriteCreate, FavoriteUpdate

async def get_favorite(db: AsyncSession, favorite_id: int) -> Favorite | None:
    result = await db.execute(
        select(Favorite).where(Favorite.id == favorite_id, Favorite.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()

async def get_specific_favorite(
    db: AsyncSession, user_id: int, favoriteable_id: str, favoriteable_type: str, collection_name: str = "default"
) -> Favorite | None:
    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.favoriteable_id == favoriteable_id,
            Favorite.favoriteable_type == favoriteable_type,
            Favorite.collection_name == collection_name,
            Favorite.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()

async def create_favorite(db: AsyncSession, user_id: int, fav_in: FavoriteCreate) -> Favorite:
    db_fav = Favorite(user_id=user_id, **fav_in.model_dump())
    db.add(db_fav)
    await db.flush()
    return db_fav

async def update_favorite(db: AsyncSession, db_fav: Favorite, fav_in: FavoriteUpdate) -> Favorite:
    update_data = fav_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_fav, field, value)
    db.add(db_fav)
    await db.flush()
    return db_fav

async def delete_favorite(db: AsyncSession, db_fav: Favorite) -> None:
    await db.delete(db_fav)
    await db.flush()

async def list_user_favorites(
    db: AsyncSession, 
    user_id: int, 
    type_filter: str | None = None,
    collection_filter: str | None = None
) -> list[Favorite]:
    query = select(Favorite).where(Favorite.user_id == user_id, Favorite.deleted_at.is_(None))
    
    if type_filter:
        query = query.where(Favorite.favoriteable_type == type_filter)
    if collection_filter:
        query = query.where(Favorite.collection_name == collection_filter)
        
    query = query.order_by(Favorite.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()

```

### 5. The Service Layer (`app/modules/favorites/service.py`)

This contains the core logic, including the smart "toggle" functionality (adding if missing, removing if exists) while recording activity.

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.favorites import crud, schema, model
from app.common.exception.errors import NotFoundError, ConflictError
from app.modules.activity.recorder import record_activity
from app.modules.users.model import User

async def toggle_favorite(
    db: AsyncSession, current_user: User, toggle_req: schema.FavoriteToggleRequest
) -> dict:
    """
    Smart endpoint: If it's favorited, it unfavorites it. If not, it favorites it.
    Returns {"status": "favorited" | "unfavorited"}
    """
    existing = await crud.get_specific_favorite(
        db, current_user.id, toggle_req.favoriteable_id, 
        toggle_req.favoriteable_type, toggle_req.collection_name
    )

    if existing:
        # Unfavorite
        await crud.delete_favorite(db, existing)
        await record_activity(
            db=db, actor=current_user, action="unfavorited",
            subject_type=toggle_req.favoriteable_type, subject_id=toggle_req.favoriteable_id,
            changes={"collection": toggle_req.collection_name}
        )
        return {"status": "unfavorited"}
    
    else:
        # Favorite
        fav_in = schema.FavoriteCreate(
            favoriteable_id=toggle_req.favoriteable_id,
            favoriteable_type=toggle_req.favoriteable_type,
            collection_name=toggle_req.collection_name
        )
        await crud.create_favorite(db, current_user.id, fav_in)
        await record_activity(
            db=db, actor=current_user, action="favorited",
            subject_type=toggle_req.favoriteable_type, subject_id=toggle_req.favoriteable_id,
            changes={"collection": toggle_req.collection_name}
        )
        return {"status": "favorited"}

async def update_favorite_notes(
    db: AsyncSession, current_user: User, favorite_id: int, update_req: schema.FavoriteUpdate
) -> model.Favorite:
    
    favorite = await crud.get_favorite(db, favorite_id)
    if not favorite or favorite.user_id != current_user.id:
        raise NotFoundError("Favorite not found.")

    favorite = await crud.update_favorite(db, favorite, update_req)
    
    await record_activity(
        db=db, actor=current_user, action="favorite_updated",
        subject_type="Favorite", subject_id=str(favorite.id)
    )
    return favorite

```

### 6. The API Layer (`app/modules/favorites/api.py`)

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.modules.favorites import schema, service, crud
from app.modules.users.deps import CurrentUser
from app.common.response.schema import ResponseModel

router = APIRouter(prefix="/favorites", tags=["Favorites"])

@router.post("/toggle", response_model=ResponseModel[dict])
async def toggle_favorite(
    toggle_req: schema.FavoriteToggleRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends()
):
    """Smart endpoint: Adds to favorites if not present, removes if already favorited."""
    result = await service.toggle_favorite(db, user, toggle_req)
    return ResponseModel(data=result, msg=f"Successfully {result['status']}.")

@router.get("/me", response_model=ResponseModel[list[schema.FavoriteOut]])
async def list_my_favorites(
    type: str | None = None,
    collection: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends()
):
    """Get all favorites for the logged-in user, optionally filtered by type or collection."""
    favorites = await crud.list_user_favorites(db, user.id, type, collection)
    return ResponseModel(data=favorites)

@router.patch("/{favorite_id}", response_model=ResponseModel[schema.FavoriteOut])
async def update_favorite(
    favorite_id: int,
    update_req: schema.FavoriteUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends()
):
    """Update notes or move a favorite to a different collection."""
    favorite = await service.update_favorite_notes(db, user, favorite_id, update_req)
    return ResponseModel(data=favorite, msg="Favorite updated.")

```

---

### End-to-End Simulation

Here is how you use this system in your frontend/API to manage favorites for a `Product` entity.

**1. The User Clicks the Heart Icon on a Product (ID: 45)**

The frontend triggers a generic toggle request. Notice how the frontend doesn't need to know if the item is already favorited—it just sends the intent.

* **Request:** `POST /api/favorites/toggle`
* **Body:**
```json
{
  "favoriteable_id": "45",
  "favoriteable_type": "Product",
  "collection_name": "Wishlist"
}

```


* **Behind the Scenes:** The Service queries `favorites` for `user_id = <current_user>`, `favoriteable_id = 45`, `collection_name = Wishlist`. Since it doesn't exist, it creates the record and logs the activity.
* **Response:**
```json
{
  "code": "success",
  "message": "Successfully favorited.",
  "data": {
    "status": "favorited"
  }
}

```


*(The frontend can now fill the heart icon in).*

**2. The User Clicks the Heart Icon Again**

* **Request:** (Exact same request as above)
* **Behind the Scenes:** The Service finds the existing favorite record, soft-deletes it, and logs the `unfavorited` action.
* **Response:**
```json
{
  "code": "success",
  "message": "Successfully unfavorited.",
  "data": {
    "status": "unfavorited"
  }
}

```



**3. The User wants to see all their "Wishlist" items**

* **Request:** `GET /api/favorites/me?collection=Wishlist`
* **Response:**
```json
{
  "code": "success",
  "data": [
    {
      "id": 10,
      "favoriteable_id": "45",
      "favoriteable_type": "Product",
      "collection_name": "Wishlist",
      "notes": null,
      "created_at": "2026-07-05T19:00:00Z",
      "updated_at": "2026-07-05T19:00:00Z"
    },
    {
      "id": 11,
      "favoriteable_id": "ab82-4f81-...",
      "favoriteable_type": "Email",
      "collection_name": "Wishlist",
      "notes": "Follow up on this quote",
      "created_at": "2026-07-04T12:00:00Z",
      "updated_at": "2026-07-04T12:00:00Z"
    }
  ]
}

```



### Why this architecture is superior:

1. **Thread-Safe Identity:** No `auth()->id()` magic. The identity is resolved cleanly in the FastAPI dependency tree (`CurrentUser`) and injected explicitly into the service functions.
2. **True Polymorphism:** Notice in step 3 how the user favorited an Integer-ID Product and a UUID-ID Email inside the *same* table. The `String` column cast makes this flawless without breaking database constraints.
3. **Idempotent Toggles:** The `/toggle` endpoint abstracts complex state management away from the frontend client.