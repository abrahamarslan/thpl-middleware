"""Documents API: async PDF generation + the document domain.

PDF: POST returns immediately with a Celery task id (202 semantics); the client
polls GET /documents/render/{task_id} or listens on Soketi for completion.

Documents (docs/documents/README.md): catalog, registration, files, links,
versions and the verification lifecycle. Reviewer actions (verify / reject /
request-resubmission) need ``TenantAdmin`` — interim authorisation until RBAC.
"""

from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.documents import crud, service, verification
from app.modules.documents.enums import DocumentLinkableType, DocumentLinkRole
from app.modules.documents.schema import (
    AddFileRequest,
    AttachDocumentsRequest,
    DocumentCreate,
    DocumentOut,
    DocumentTypeOut,
    LinkIn,
    ReasonRequest,
    RemarksRequest,
    RenderRequest,
    ResubmitRequest,
    TaskStatus,
    TaskSubmitted,
    VerificationLogOut,
    VerifyRequest,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser
from app.tasks.celery_app import celery_app

router = APIRouter()


# ── PDF rendering ───────────────────────────────────────────────────────────

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


# ── the catalog ─────────────────────────────────────────────────────────────

@router.get("/types", response_model=ResponseModel[list[DocumentTypeOut]])
async def list_document_types(
    _: CurrentUser, db: DBSession,
    category: str | None = Query(None, description="DocumentPurpose value"),
    include_deactivated: bool = False,
):
    types = await service.list_document_types(db, category=category, include_deactivated=include_deactivated)
    return ResponseModel(data=[DocumentTypeOut.model_validate(t) for t in types])


@router.get("/types/{code}", response_model=ResponseModel[DocumentTypeOut])
async def get_document_type(_: CurrentUser, db: DBSession, code: str):
    return ResponseModel(data=DocumentTypeOut.model_validate(await service.get_document_type(db, code)))


# ── documents ───────────────────────────────────────────────────────────────

@router.post("", response_model=ResponseModel[DocumentOut], status_code=201)
async def register_document(user: CurrentUser, db: DBSession, doc_in: DocumentCreate):
    """Register a document (with its files and owners) after the bytes reached object storage."""
    document = await service.register_document(db, doc_in, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document registered")


@router.post("/attach", response_model=ResponseModel[list[DocumentOut]])
async def attach_documents(user: CurrentUser, db: DBSession, req: AttachDocumentsRequest):
    """Link existing documents to any entity (an email's attachments, …)."""
    docs = await service.attach_documents(db, req, actor_id=user.id)
    return ResponseModel(data=[DocumentOut.model_validate(d) for d in docs], msg="Documents attached")


@router.get("/for-entity", response_model=ResponseModel[list[DocumentOut]])
async def list_entity_documents(
    _: CurrentUser, db: DBSession,
    linkable_type: DocumentLinkableType = Query(...), linkable_id: int = Query(..., gt=0),
    roles: list[DocumentLinkRole] | None = Query(None),
    all_versions: bool = Query(False, description="Include superseded versions"),
):
    docs = await service.list_documents_for_entity(
        db, linkable_type.value, linkable_id, roles=[r.value for r in roles] if roles else None,
        latest_only=not all_versions,
    )
    return ResponseModel(data=[DocumentOut.model_validate(d) for d in docs])


@router.get("/{document_id}", response_model=ResponseModel[DocumentOut])
async def get_document(_: CurrentUser, db: DBSession, document_id: UUID):
    return ResponseModel(data=DocumentOut.model_validate(await service.get_document(db, document_id)))


@router.delete("/{document_id}", response_model=ResponseModel[None])
async def delete_document(user: CurrentUser, db: DBSession, document_id: UUID, reason: str | None = Query(None)):
    await service.soft_delete_document(db, document_id, reason=reason, actor_id=user.id)
    return ResponseModel(data=None, msg="Document soft-deleted")


# ── files, links, versions ──────────────────────────────────────────────────

@router.post("/{document_id}/files", response_model=ResponseModel[DocumentOut], status_code=201)
async def add_file(user: CurrentUser, db: DBSession, document_id: UUID, file_in: AddFileRequest):
    document = await service.add_file(db, document_id, file_in, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="File added")


@router.post("/{document_id}/links", response_model=ResponseModel[DocumentOut], status_code=201)
async def link_document(user: CurrentUser, db: DBSession, document_id: UUID, link_in: LinkIn):
    document = await service.link_document(db, document_id, link_in, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document linked")


@router.delete("/{document_id}/links/{link_id}", response_model=ResponseModel[DocumentOut])
async def unlink_document(
    user: CurrentUser, db: DBSession, document_id: UUID, link_id: UUID, reason: str | None = Query(None),
):
    document = await service.unlink_document(db, document_id, link_id, reason=reason, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document unlinked")


@router.post("/{document_id}/resubmit", response_model=ResponseModel[DocumentOut], status_code=201)
async def resubmit_document(user: CurrentUser, db: DBSession, document_id: UUID, req: ResubmitRequest):
    """Upload the next version of a rejected / expired / resubmission-required document."""
    document = await service.resubmit_document(db, document_id, req, actor_id=user.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="New version created")


# ── verification lifecycle ──────────────────────────────────────────────────

@router.post("/{document_id}/submit", response_model=ResponseModel[DocumentOut])
async def submit_for_review(user: CurrentUser, db: DBSession, document_id: UUID, body: RemarksRequest | None = None):
    document = await service.get_document(db, document_id)
    await verification.submit_for_review(db, document, actor_id=user.id, remarks=body.remarks if body else None)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Submitted for review")


@router.post("/{document_id}/verify", response_model=ResponseModel[DocumentOut])
async def verify_document(admin: TenantAdmin, db: DBSession, document_id: UUID, body: VerifyRequest):
    document = await service.get_document(db, document_id)
    await verification.verify(db, document, body, actor_id=admin.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document verified")


@router.post("/{document_id}/reject", response_model=ResponseModel[DocumentOut])
async def reject_document(admin: TenantAdmin, db: DBSession, document_id: UUID, body: ReasonRequest):
    document = await service.get_document(db, document_id)
    await verification.reject(db, document, body.reason, actor_id=admin.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Document rejected")


@router.post("/{document_id}/request-resubmission", response_model=ResponseModel[DocumentOut])
async def request_resubmission(admin: TenantAdmin, db: DBSession, document_id: UUID, body: ReasonRequest):
    document = await service.get_document(db, document_id)
    await verification.request_resubmission(db, document, body.reason, actor_id=admin.id)
    return ResponseModel(data=DocumentOut.model_validate(document), msg="Resubmission requested")


@router.get("/{document_id}/logs", response_model=ResponseModel[list[VerificationLogOut]])
async def document_logs(_: CurrentUser, db: DBSession, document_id: UUID):
    document = await service.get_document(db, document_id)
    logs = await crud.list_logs(db, document.id)
    return ResponseModel(data=[VerificationLogOut.model_validate(entry) for entry in logs])
