"""Async PDF generation endpoints.

POST returns immediately with a Celery task id (202 semantics); the client
polls GET /documents/render/{task_id} or listens on Soketi for completion.
"""

from celery.result import AsyncResult
from fastapi import APIRouter

from app.common.response.schema import ResponseModel
from app.modules.users.deps import CurrentUser
from app.modules.documents.schema import RenderRequest, TaskStatus, TaskSubmitted
from app.tasks.celery_app import celery_app

router = APIRouter()


@router.post("/render", response_model=ResponseModel[TaskSubmitted], status_code=202)
async def render_pdf(_: CurrentUser, body: RenderRequest):
    result = celery_app.send_task(
        "app.tasks.documents.generate_pdf",
        kwargs={
            "source": body.source,
            "filename": body.filename,
            "sys_inputs": body.sys_inputs,
        },
        queue="documents",
    )
    return ResponseModel(data=TaskSubmitted(task_id=result.id))


@router.get("/render/{task_id}", response_model=ResponseModel[TaskStatus])
async def render_status(_: CurrentUser, task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    payload = None
    if result.successful():
        payload = {"path": result.result}
    elif result.failed():
        payload = {"error": str(result.result)}
    return ResponseModel(data=TaskStatus(task_id=task_id, status=result.status.lower(), result=payload))


# ── Polymorphic document attachments ─────────────────────────────────────────

from uuid import UUID  # noqa: E402

from fastapi import Query  # noqa: E402

from app.database.db import DBSession  # noqa: E402
from app.modules.documents import crud, service  # noqa: E402
from app.modules.documents.schema import (  # noqa: E402
    AttachDocumentsRequest,
    DocumentCreate,
    DocumentOut,
)


@router.post("", response_model=ResponseModel[DocumentOut], status_code=201)
async def register_document(user: CurrentUser, db: DBSession, doc_in: DocumentCreate):
    """Register a document record after the frontend uploaded the bytes to S3."""
    document = await service.register_uploaded_document(db, doc_in, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document registered")


@router.post("/attach", response_model=ResponseModel[list[DocumentOut]])
async def attach_documents(user: CurrentUser, db: DBSession, req: AttachDocumentsRequest):
    """Attach existing documents to any entity (Email, ZohoOrganization, ...)."""
    docs = await service.attach_documents(db, req, actor_id=user.id)
    return ResponseModel(data=[DocumentOut.model_validate(d) for d in docs], msg="Documents attached")


@router.get("/for-entity", response_model=ResponseModel[list[DocumentOut]])
async def list_entity_documents(
    _: CurrentUser, db: DBSession,
    entity_type: str = Query(...), entity_id: str = Query(...),
):
    docs = await crud.list_documents_for_entity(db, entity_type, entity_id)
    return ResponseModel(data=[DocumentOut.model_validate(d) for d in docs])


@router.get("/{document_id}", response_model=ResponseModel[DocumentOut])
async def get_document(_: CurrentUser, db: DBSession, document_id: UUID):
    document = await service.get_document(db, document_id)
    return ResponseModel(data=DocumentOut.model_validate(document))


@router.delete("/{document_id}", response_model=ResponseModel[None])
async def delete_document(user: CurrentUser, db: DBSession, document_id: UUID):
    await service.soft_delete_document(db, document_id, actor_id=user.id)
    return ResponseModel(data=None, msg="Document soft-deleted")
