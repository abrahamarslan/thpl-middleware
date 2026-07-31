This is a fantastic candidate for modernization. The original Laravel implementation is comprehensive, but it contains a few classic anti-patterns for database design (like storing computed `*_formatted` values directly in the database) and synchronous S3 logic.

Here is the **Enterprise Async FastAPI implementation** of the Document module.

### Key Architectural Improvements Made:

1. **Database Normalization (No `*_formatted` columns):** We removed `file_size_formatted`, `created_time_formatted`, etc., from the database. Instead, these are calculated dynamically at runtime using Pydantic’s `@computed_field`. This guarantees the string always matches the raw data and saves database space.
2. **Polymorphic 1-to-Many via Mixins:** Like the Tags system, we create a `HasDocumentsMixin`. By inheriting this, **any** model (Email, Product, User) instantly gets an eager-loaded `documents` list with zero N+1 queries.
3. **Primary Key Standardization:** Instead of having an auto-incrementing `id` *and* a `document_id` UUID, we upgrade the primary key to be a native Postgres `UUID`. This prevents ID enumeration attacks.
4. **S3 Presigned URLs:** Shifted to an async Service method that generates presigned URLs for secure, temporary frontend access.

---

### 1. The Polymorphic Mixin (`app/modules/documents/mixins.py`)

Add this to any model (like `Email` or `Invoice`) to instantly give it a `documents` relationship.

```python
from sqlalchemy import cast, String
from sqlalchemy.orm import relationship, declared_attr
from app.modules.documents.model import Document

class HasDocumentsMixin:
    """
    Enterprise mixin to natively bind Documents to any model.
    Read operations use eager loading (selectinload).
    Write operations must use the Document Service to ensure async safety.
    """

    @declared_attr
    def documents(cls):
        # Cast local ID to string to join against the polymorphic documentable_id
        return relationship(
            "Document",
            primaryjoin=lambda: (
                cast(cls.id, String) == Document.documentable_id
            ) & (
                Document.documentable_type == cls.__name__
            ),
            foreign_keys=[Document.documentable_id],
            viewonly=True, # Read-only in ORM; mutate via Service explicitly
            order_by="Document.display_order.asc(), Document.created_at.desc()"
        )

```

### 2. The Model Layer (`app/modules/documents/model.py`)

```python
import uuid
from sqlalchemy import Column, String, Integer, Boolean, Numeric, DateTime, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database.db import Base
from app.database.mixins import TimestampMixin, SoftDeleteMixin
from app.modules.tags.mixins import HasTagsMixin  # Documents can be tagged!

class Document(TimestampMixin, SoftDeleteMixin, HasTagsMixin, Base):
    __tablename__ = "documents"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Polymorphic Association (What this document belongs to)
    documentable_id = Column(String, index=True, nullable=True)
    documentable_type = Column(String, index=True, nullable=True)

    # Core Information
    file_name = Column(String, nullable=False, index=True)
    file_type = Column(String, nullable=False, index=True)
    file_size = Column(Integer, nullable=False, comment="Size in bytes")
    
    # Zoho / External Systems
    zoho_id = Column(String, unique=True, index=True, nullable=True)
    folder_id = Column(String, nullable=True)
    folder_name = Column(String, nullable=True)
    
    # File Status Flags
    document_status = Column(String, default="uploaded", index=True)
    is_active = Column(Boolean, default=True, index=True)
    is_verified = Column(Boolean, default=False, index=True)
    is_blocked = Column(Boolean, default=False)
    is_visible = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)

    # S3 Storage Data
    s3_bucket = Column(String, nullable=True, index=True)
    s3_key = Column(String, nullable=True, index=True)
    s3_version_id = Column(String, nullable=True)
    s3_region = Column(String, nullable=True)
    s3_storage_class = Column(String, default="STANDARD")
    s3_etag = Column(String, nullable=True)
    s3_metadata = Column(JSONB, nullable=True)

    # Processing & OCR Data
    processing_status = Column(String, default="pending", index=True)
    processing_results = Column(JSONB, nullable=True)
    scanned_amount = Column(Numeric(15, 2), default=0.00)
    vendor_name = Column(String, nullable=True, index=True)
    scanned_receipt_date = Column(DateTime(timezone=True), nullable=True)
    extracted_text = Column(JSONB, nullable=True)

    # Security & Integrity
    checksum_md5 = Column(String, nullable=True)
    checksum_sha256 = Column(String, nullable=True)
    virus_scanned = Column(Boolean, default=False)
    contains_pii = Column(Boolean, default=False)
    access_permissions = Column(JSONB, nullable=True)

    # Metadata & Versioning
    version = Column(String, default="1.0")
    revision = Column(Integer, default=1)
    version_history = Column(JSONB, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True) # avoiding SQLAlchemy reserved keyword

```

### 3. The Schema Layer (`app/modules/documents/schema.py`)

This is where the magic happens for replacing `_formatted` columns.

```python
import math
from pydantic import BaseModel, Field, computed_field, ConfigDict
from typing import Optional, Any, Dict
from datetime import datetime
from uuid import UUID
from app.modules.tags.schema import TagOut

class DocumentBase(BaseModel):
    file_name: str
    file_type: str
    file_size: int
    document_status: str = "uploaded"
    processing_status: str = "pending"
    is_active: bool = True
    is_visible: bool = True

class DocumentCreate(DocumentBase):
    documentable_id: Optional[str] = None
    documentable_type: Optional[str] = None
    s3_bucket: str
    s3_key: str
    s3_region: str
    s3_etag: Optional[str] = None
    checksum_md5: Optional[str] = None

class DocumentOut(DocumentBase):
    id: UUID
    zoho_id: Optional[str]
    s3_key: Optional[str]
    scanned_amount: float
    vendor_name: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Optional nested tags
    tags: list[TagOut] = []

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def file_size_formatted(self) -> str:
        """Dynamically calculates readable file size (KB, MB)"""
        if self.file_size == 0:
            return "0 B"
        unit_names = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(self.file_size, 1024)))
        p = math.pow(1024, i)
        s = round(self.file_size / p, 2)
        return f"{s} {unit_names[i]}"

    @computed_field
    def is_processable(self) -> bool:
        """Determines if the document can be sent to OCR/Processing"""
        return self.file_type.lower() in ["pdf", "doc", "docx", "png", "jpg", "jpeg"]

```

### 4. The CRUD Layer (`app/modules/documents/crud.py`)

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.modules.documents.model import Document
from app.modules.documents.schema import DocumentCreate

async def create_document(db: AsyncSession, doc_in: DocumentCreate) -> Document:
    document = Document(**doc_in.model_dump())
    db.add(document)
    await db.flush()
    return document

async def get_document(db: AsyncSession, document_id: UUID) -> Document | None:
    query = select(Document).where(
        Document.id == document_id, 
        Document.deleted_at.is_(None)
    ).options(selectinload(Document.tags))
    
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def list_documents_for_entity(
    db: AsyncSession, entity_type: str, entity_id: str
) -> list[Document]:
    query = select(Document).where(
        Document.documentable_type == entity_type,
        Document.documentable_id == entity_id,
        Document.deleted_at.is_(None)
    ).order_by(Document.display_order.asc())
    
    result = await db.execute(query)
    return result.scalars().all()

```

### 5. The Service Layer (`app/modules/documents/service.py`)

```python
import boto3 # Assuming standard boto3 usage for presigned URLs
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.conf import settings
from app.modules.documents import crud, schema
from app.common.exception.errors import NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.users.model import User

async def register_uploaded_document(
    db: AsyncSession, doc_in: schema.DocumentCreate, current_user: User
) -> schema.DocumentOut:
    """Creates the DB record after a file is successfully uploaded to S3."""
    document = await crud.create_document(db, doc_in)

    await record_activity(
        db=db, actor=current_user, action="document_uploaded",
        subject_type="Document", subject_id=str(document.id),
        changes={"file_name": doc_in.file_name}
    )
    return document

async def generate_presigned_url(db: AsyncSession, document_id: UUID) -> str:
    """Generates a secure, temporary 15-minute download link for a document."""
    document = await crud.get_document(db, document_id)
    if not document:
        raise NotFoundError("Document not found or deleted.")

    # In production, use aioboto3 or run this in a threadpool executor
    s3_client = boto3.client(
        's3',
        region_name=document.s3_region,
        aws_access_key_id=settings.AWS_ACCESS_KEY,
        aws_secret_access_key=settings.AWS_SECRET_KEY
    )
    
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': document.s3_bucket, 'Key': document.s3_key},
        ExpiresIn=900 # 15 minutes
    )
    
    # Optionally log access
    document.download_count += 1
    db.add(document)
    await db.commit()
    
    return url

async def update_processing_status(
    db: AsyncSession, document_id: UUID, status: str, results: dict = None
):
    """Called by Celery workers after OCR/Scanning is complete."""
    document = await crud.get_document(db, document_id)
    if not document:
        return
        
    document.processing_status = status
    if results:
        document.processing_results = results
        # Automatically extract mapped data if present
        if "amount" in results:
            document.scanned_amount = results["amount"]
        if "vendor" in results:
            document.vendor_name = results["vendor"]
            
    db.add(document)
    await db.commit()

```

### 6. The API Layer (`app/modules/documents/api.py`)

```python
from fastapi import APIRouter, Depends
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.modules.documents import schema, service
from app.modules.users.deps import CurrentUser
from app.common.response.schema import ResponseModel

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("", response_model=ResponseModel[schema.DocumentOut])
async def register_document(
    doc_in: schema.DocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends()
):
    """
    Registers a document in the database after the frontend uploads it to S3.
    """
    document = await service.register_uploaded_document(db, doc_in, user)
    return ResponseModel(data=document, msg="Document registered successfully.")

@router.get("/{document_id}/download-link", response_model=ResponseModel[str])
async def get_download_link(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends()
):
    """Returns a temporary 15-minute secure S3 URL."""
    url = await service.generate_presigned_url(db, document_id)
    return ResponseModel(data=url, msg="Link generated.")

```

---

### End-to-End Simulation: An Email with Multiple Documents

Here is how you use this powerful setup in practice.

**1. Create the Email Model**
Notice we inherit `HasDocumentsMixin`.

```python
# app/modules/emails/model.py
from app.database.db import Base
from app.database.mixins import TimestampMixin, IntPKMixin
from app.modules.documents.mixins import HasDocumentsMixin
from sqlalchemy import Column, String, Text

class Email(TimestampMixin, IntPKMixin, HasDocumentsMixin, Base):
    __tablename__ = "emails"

    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    sender = Column(String, nullable=False)

```

**2. Configure the Email Pydantic Schema**
Notice we simply declare `documents: list[DocumentOut] = []`. Pydantic handles the rest!

```python
# app/modules/emails/schema.py
from pydantic import BaseModel, ConfigDict
from typing import List
from app.modules.documents.schema import DocumentOut

class EmailOut(BaseModel):
    id: int
    subject: str
    body: str
    sender: str
    documents: List[DocumentOut] = []  # Natively loads attachments!

    model_config = ConfigDict(from_attributes=True)

```

**3. Fetch the Email in your API (Zero N+1)**

```python
# app/modules/emails/crud.py
from sqlalchemy.orm import selectinload

async def get_email(db: AsyncSession, email_id: int):
    # This executes exactly 2 queries:
    # 1. Fetch Email
    # 2. Fetch all Documents where documentable_id = email_id & type = 'Email'
    query = select(Email).where(Email.id == email_id).options(selectinload(Email.documents))
    result = await db.execute(query)
    return result.scalar_one_or_none()

```

**JSON Output Result for the Email API:**

```json
{
  "code": "success",
  "data": {
    "id": 142,
    "subject": "Q3 Invoices attached",
    "body": "Please find the invoices attached.",
    "sender": "vendor@acme.com",
    "documents": [
      {
        "id": "e2c3b2f9-7d8a-4a6f-b1e9-9c2b4d8a5e3c",
        "file_name": "invoice_jul.pdf",
        "file_type": "pdf",
        "file_size": 1548200,
        "file_size_formatted": "1.48 MB",  // <- Beautifully computed on the fly!
        "is_processable": true,          // <- Computed dynamically
        "document_status": "uploaded",
        "scanned_amount": 0.0,
        "s3_key": "emails/142/invoice_jul.pdf",
        "tags": []
      },
      {
        "id": "a4d3f2b1-9x8z-2b4h-m7k3-1p9l4x7c2v5n",
        "file_name": "invoice_aug.pdf",
        "file_type": "pdf",
        "file_size": 24000,
        "file_size_formatted": "23.44 KB", 
        "is_processable": true,
        "document_status": "uploaded",
        "scanned_amount": 0.0,
        "s3_key": "emails/142/invoice_aug.pdf",
        "tags": []
      }
    ]
  }
}

```

### Why this is an Enterprise Grade Architecture:

* **Polymorphic isolation:** The `Email` model has no idea how S3 works. The `Document` model has no idea what an Email is. They are completely decoupled.
* **Dynamic Resolution:** You don't have to map data manually in your routers. SQLAlchemy `selectinload` populates the ORM object, and Pydantic reads it automatically.
* **Storage Independence:** DB isn't storing computed text (like "1.48 MB"). If you decide to change formatting to use commas or metric boundaries later, you update one Pydantic schema and it changes system-wide immediately.