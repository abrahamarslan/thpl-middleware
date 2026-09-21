"""Document module: the catalog, the logical document + files + links, the
verification lifecycle and its trail, versions, and the email attachment path.

Unit tests are hermetic; integration tests (the ``db`` fixture) run against the
migrated scratch database, where the migration has already seeded the catalog.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.common.exception.errors import ConflictError, NotFoundError
from app.core.conf import settings
from app.modules.documents import crud, schema, service, verification
from app.modules.documents.enums import (
    ALLOWED_TRANSITIONS,
    DocumentLinkableType,
    DocumentLinkRole,
    DocumentPageSide,
    DocumentPurpose,
    DocumentVerificationStatus,
    PersonnelType,
    Requirement,
    VerificationActorType,
)
from app.modules.documents.errors import DocumentRuleError
from app.modules.documents.mixins import linkable_type_of
from app.modules.documents.model import Document, DocumentFile, DocumentType
from app.modules.documents.seed import GENERAL_TYPE_CODE, catalog, seed_document_types
from app.modules.emails.model import Email
from app.modules.tenants.model import Tenant

_S = DocumentVerificationStatus
FRONT, BACK = DocumentPageSide.FRONT, DocumentPageSide.BACK


# ── helpers ─────────────────────────────────────────────────────────────────

def _file(name="a.pdf", side=DocumentPageSide.NOT_APPLICABLE, **kw) -> schema.FileIn:
    return schema.FileIn(file_name=name, file_key=f"k/{name}", page_side=side, **kw)


def _owner(entity="user", entity_id=5, role=DocumentLinkRole.OWNER) -> schema.LinkIn:
    return schema.LinkIn(linkable_type=DocumentLinkableType(entity), linkable_id=entity_id, link_role=role)


def _create(code=GENERAL_TYPE_CODE, **kw) -> schema.DocumentCreate:
    return schema.DocumentCreate(document_type_code=code, **kw)


async def _register(db, code=GENERAL_TYPE_CODE, **kw) -> Document:
    return await service.register_document(db, _create(code, **kw))


@pytest.fixture
async def catalog_ready(db):
    """The migration seeds the catalog; re-seeding is idempotent and never overwrites."""
    await db.run_sync(lambda session: seed_document_types(session.connection()))


# ── unit: the vocabulary and the state machine ──────────────────────────────

def test_every_status_has_transition_rules_and_none_loops_back():
    assert set(ALLOWED_TRANSITIONS) == set(_S)
    for status, targets in ALLOWED_TRANSITIONS.items():
        assert status not in targets
    # A resubmission is a new row, so the states that need one are dead ends.
    assert ALLOWED_TRANSITIONS[_S.RESUBMISSION_REQUIRED] == frozenset()
    # Nothing can jump straight into 'verified' without passing through review or upload.
    assert {s for s, t in ALLOWED_TRANSITIONS.items() if _S.VERIFIED in t} == {_S.UPLOADED, _S.IN_REVIEW}


def test_the_seed_catalog_is_consistent():
    rows = catalog()
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes)) and codes[0] == GENERAL_TYPE_CODE
    assert [r["sort_order"] for r in rows] == sorted({r["sort_order"] for r in rows})
    personnel = {p.value for p in PersonnelType}
    for row in rows:
        assert DocumentPurpose(row["category"])
        assert set(row["agent_type_requirement"]) == personnel, row["code"]
        assert set(row["agent_type_requirement"].values()) <= {r.value for r in Requirement}, row["code"]
        assert row["default_validity_days"] is None or row["has_expiry"], f"{row['code']}: validity without expiry"
    by_code = {r["code"]: r for r in rows}
    assert by_code["AADHAAR"]["allows_full_number_storage"] is False and by_code["AADHAAR"]["requires_front_and_back"]
    # The generic type is never a checklist item.
    assert set(by_code[GENERAL_TYPE_CODE]["agent_type_requirement"].values()) == {"not_applicable"}


def test_mask_number_keeps_the_last_four():
    assert service.mask_number("1234 5678 9012") == "XXXXXXXX9012"
    assert service.mask_number("ABCDE1234F") == "XXXXXX234F"
    assert service.mask_number("123") == "XXX"


def test_linkable_type_is_the_snake_case_of_the_class():
    assert linkable_type_of(Email) == "email"
    assert linkable_type_of(type("BrandOwner", (), {})) == "brand_owner"


def test_completeness_needs_both_faces_of_a_two_sided_type():
    two_sided = DocumentType(requires_front_and_back=True)
    one_sided = DocumentType(requires_front_and_back=False)
    assert not verification.is_complete(two_sided, [FRONT])
    assert not verification.is_complete(two_sided, [])
    assert verification.is_complete(two_sided, ["front", "back"])
    assert verification.is_complete(one_sided, [DocumentPageSide.NOT_APPLICABLE])
    assert not verification.is_complete(one_sided, [])


def test_request_schemas_validate_and_never_echo_the_number():
    request = _create(document_number="1234 5678 9012")
    assert request.document_type_code == GENERAL_TYPE_CODE
    assert "1234" not in repr(request) and "1234" not in request.model_dump_json()
    with pytest.raises(ValidationError):
        _file(file_hash_sha256="not-a-hash")
    with pytest.raises(ValidationError):
        schema.LinkIn(linkable_type="bogus", linkable_id=1)
    with pytest.raises(ValidationError):
        schema.LinkIn(linkable_type="user", linkable_id=0)


# ── integration: the catalog ────────────────────────────────────────────────

async def test_the_migration_seeded_the_catalog(db, catalog_ready):
    types = {t.code: t for t in await service.list_document_types(db)}
    assert {r["code"] for r in catalog()} <= set(types)
    assert types["AADHAAR"].requires_front_and_back and not types["AADHAAR"].allows_full_number_storage
    only_vehicle = await service.list_document_types(db, category="vehicle_compliance")
    assert only_vehicle and {t.category for t in only_vehicle} == {"vehicle_compliance"}
    with pytest.raises(NotFoundError):
        await service.get_document_type(db, "NOPE")


async def test_reseeding_never_overwrites_an_operators_edit(db, catalog_ready):
    pan = await service.get_document_type(db, "PAN_CARD")
    pan.display_name = "PAN (renamed by ops)"
    await db.flush()
    await db.run_sync(lambda session: seed_document_types(session.connection()))
    await db.refresh(pan)
    assert pan.display_name == "PAN (renamed by ops)"


# ── integration: registration ───────────────────────────────────────────────

async def test_register_a_generic_document_with_a_file_and_an_owner(db, catalog_ready):
    doc = await _register(db, files=[_file("scan.pdf", file_size_bytes=2048, file_hash_sha256="A" * 64)],
                          links=[_owner("user", 5)])
    assert doc.document_type_code == GENERAL_TYPE_CODE and doc.document_purpose == "other"
    assert doc.verification_status == "uploaded" and doc.is_verified is False and not doc.is_mandatory
    assert [(f.file_name, f.is_primary, f.file_hash_sha256) for f in doc.files] == [("scan.pdf", True, "a" * 64)]
    assert [(entry.linkable_type, entry.linkable_id, entry.link_role) for entry in doc.links] == [("user", 5, "owner")]
    assert doc.tenant_id == doc.files[0].tenant_id == doc.links[0].tenant_id
    logs = await crud.list_logs(db, doc.id)
    assert [(entry.action, entry.previous_status, entry.new_status) for entry in logs] == [("uploaded", None, "uploaded")]
    assert (logs[0].primary_link_type, logs[0].primary_link_id) == ("user", 5)


async def test_a_two_sided_document_waits_for_both_sides(db, catalog_ready):
    doc = await _register(db, "DRIVING_LICENSE", files=[_file("front.jpg", FRONT)])
    assert doc.verification_status == "pending_upload"

    with pytest.raises(DocumentRuleError):                       # a second FRONT
        await service.add_file(db, doc.uuid, _file("front2.jpg", FRONT))
    doc = await service.add_file(db, doc.uuid, _file("back.jpg", BACK))

    assert doc.verification_status == "uploaded"
    assert [f.page_side for f in doc.files] == ["front", "back"] and doc.files[0].is_primary
    logs = await crud.list_logs(db, doc.id)
    assert [(entry.action, entry.previous_status, entry.new_status) for entry in logs] == [
        ("uploaded", None, "pending_upload"), ("uploaded", "pending_upload", "uploaded"),
    ]


async def test_duplicate_files_are_refused(db, catalog_ready):
    with pytest.raises(DocumentRuleError):                       # twice in one request
        await _register(db, files=[_file("a.pdf", file_hash_sha256="b" * 64), _file("b.pdf", file_hash_sha256="B" * 64)])
    doc = await _register(db, files=[_file("a.pdf", file_hash_sha256="c" * 64)])
    with pytest.raises(ConflictError):                           # already part of the document
        await service.add_file(db, doc.uuid, _file("copy.pdf", file_hash_sha256="C" * 64))


async def test_files_cannot_be_added_once_the_document_is_in_review(db, catalog_ready):
    doc = await _register(db, files=[_file()])
    await verification.submit_for_review(db, doc)
    with pytest.raises(ConflictError, match="resubmit"):
        await service.add_file(db, doc.uuid, _file("late.pdf"))


async def test_aadhaar_never_stores_the_full_number_even_with_a_key(db, catalog_ready, monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_NUMBER_ENCRYPTION_KEY", "a-key-that-must-not-matter")
    doc = await _register(db, "AADHAAR", document_number="1234 5678 9012",
                          files=[_file("f.jpg", FRONT), _file("b.jpg", BACK)])
    assert doc.document_number_masked == "XXXXXXXX9012"
    assert doc.document_number_full_encrypted is None


async def test_the_full_number_is_encrypted_with_a_key_and_dropped_without_one(db, catalog_ready, monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_NUMBER_ENCRYPTION_KEY", "")
    keyless = await _register(db, "PAN_CARD", document_number="ABCDE1234F", files=[_file()])
    assert keyless.document_number_masked == "XXXXXX234F" and keyless.document_number_full_encrypted is None

    monkeypatch.setattr(settings, "DOCUMENT_NUMBER_ENCRYPTION_KEY", "test-passphrase")
    keyed = await _register(db, "PAN_CARD", document_number="ABCDE1234F", files=[_file()])
    stored = keyed.document_number_full_encrypted
    assert stored and "ABCDE1234F" not in stored and stored.startswith("-----BEGIN PGP MESSAGE-----")
    roundtrip = await db.scalar(text("SELECT pgp_sym_decrypt(dearmor(:c), :k)"), {"c": stored, "k": "test-passphrase"})
    assert roundtrip == "ABCDE1234F"


async def test_expiry_is_prefilled_from_the_types_default_validity(db, catalog_ready):
    photo = await _register(db, "PASSPORT_PHOTOGRAPH", issued_date=date(2026, 1, 1), files=[_file()])
    assert photo.expiry_date == date(2026, 1, 1) + timedelta(days=730)
    explicit = await _register(db, "PASSPORT_PHOTOGRAPH", expiry_date=date(2030, 1, 1), files=[_file()])
    assert explicit.expiry_date == date(2030, 1, 1)
    no_expiry = await _register(db, "PAN_CARD", files=[_file()])
    assert no_expiry.expiry_date is None


async def test_is_mandatory_follows_the_requirement_for_the_personnel_type(db, catalog_ready):
    for personnel, expected in ((PersonnelType.DRIVER, True), (PersonnelType.HELPER, False)):
        doc = await _register(db, "DRIVING_LICENSE", personnel_type=personnel)
        assert doc.is_mandatory is expected, personnel


async def test_a_deactivated_type_is_refused(db, catalog_ready):
    voter = await service.get_document_type(db, "VOTER_ID")
    voter.deactivate(reason="no longer requested")
    await db.flush()
    with pytest.raises(ConflictError, match="deactivated"):
        await _register(db, "VOTER_ID")
    assert "VOTER_ID" not in {t.code for t in await service.list_document_types(db)}
    assert "VOTER_ID" in {t.code for t in await service.list_document_types(db, include_deactivated=True)}


# ── integration: links ──────────────────────────────────────────────────────

async def test_a_document_has_at_most_one_owner(db, catalog_ready):
    with pytest.raises(DocumentRuleError):
        await _register(db, links=[_owner("user", 1), _owner("vehicle", 2)])

    doc = await _register(db, links=[_owner("vehicle", 2)])
    with pytest.raises(DocumentRuleError, match="already has an owner"):
        await service.link_document(db, doc.uuid, _owner("user", 9))
    # Other roles are unlimited: the RC scan also belongs to the vehicle's owner user.
    doc = await service.link_document(db, doc.uuid, _owner("user", 9, DocumentLinkRole.REFERENCE))
    assert {(entry.linkable_type, entry.link_role) for entry in doc.links} == {("vehicle", "owner"), ("user", "reference")}
    with pytest.raises(ConflictError):
        await service.link_document(db, doc.uuid, _owner("user", 9, DocumentLinkRole.REFERENCE))


async def test_unlinking_soft_deletes_the_link_and_hides_it(db, catalog_ready):
    doc = await _register(db, links=[_owner("user", 5)])
    link = doc.links[0]
    doc = await service.unlink_document(db, doc.uuid, link.uuid, reason="wrong person")
    assert doc.links == []
    assert await service.list_documents_for_entity(db, "user", 5) == []

    gone = await db.scalar(select(type(link)).where(type(link).id == link.id).execution_options(include_deleted=True))
    assert gone.deleted_at is not None and gone.deleted_reason == "wrong person"
    # The slot is free again: a new owner is allowed.
    assert (await service.link_document(db, doc.uuid, _owner("user", 6))).links[0].linkable_id == 6


async def test_attaching_is_idempotent_and_merges_the_link_context(db, catalog_ready):
    doc = await _register(db)
    for context in ({"is_inline": True}, {"content_id": "cid:logo"}):
        await crud.attach_documents_to_entity(db, "email", 77, [doc.uuid], context_by_id={doc.uuid: context})
    doc = await crud.get_document(db, doc.uuid, refresh=True)
    assert len(doc.links) == 1
    assert doc.links[0].link_role == "attachment" and doc.links[0].context == {"is_inline": True, "content_id": "cid:logo"}

    req = schema.AttachDocumentsRequest(linkable_type="email", linkable_id=77,
                                        document_ids=[doc.uuid, "00000000-0000-4000-8000-000000000000"])
    with pytest.raises(NotFoundError):
        await service.attach_documents(db, req)


async def test_has_documents_mixin_reads_through_the_links(db, catalog_ready):
    email = Email(email_to=["a@b.example"], all_recipients=["a@b.example"], email_from="n@x.example",
                  subject="Hi", status="pending")
    db.add(email)
    await db.flush()
    doc = await _register(db, files=[_file("att.pdf")])
    await crud.attach_documents_to_entity(db, linkable_type_of(Email), email.id, [doc.uuid])

    loaded = await db.scalar(
        select(Email).where(Email.id == email.id).options(selectinload(Email.documents)),
        execution_options={"populate_existing": True},
    )
    assert [d.uuid for d in loaded.documents] == [doc.uuid]

    link = (await crud.get_document(db, doc.uuid, refresh=True)).links[0]
    await service.unlink_document(db, doc.uuid, link.uuid)
    loaded = await db.scalar(
        select(Email).where(Email.id == email.id).options(selectinload(Email.documents)),
        execution_options={"populate_existing": True},
    )
    assert loaded.documents == []


# ── integration: verification lifecycle and trail ───────────────────────────

async def test_the_verification_lifecycle_leaves_a_trail(db, catalog_ready):
    doc = await _register(db, "PAN_CARD", files=[_file()], links=[_owner("user", 5)])
    await verification.submit_for_review(db, doc, remarks="looks legible")
    await verification.verify(db, doc, schema.VerifyRequest(
        third_party_provider="karza", third_party_reference_id="tx-1", provider_payload={"match": True}), actor_id=41)

    assert (doc.verification_status, doc.is_verified) == ("verified", True)
    assert (doc.verification_method, doc.verified_by, doc.verification_data) == ("manual_review", 41, {"match": True})
    assert doc.verified_at is not None and doc.third_party_verification_provider == "karza"
    logs = await crud.list_logs(db, doc.id)
    assert [(entry.action, entry.previous_status, entry.new_status) for entry in logs] == [
        ("uploaded", None, "uploaded"), ("in_review", "uploaded", "in_review"), ("verified", "in_review", "verified"),
    ]
    assert logs[-1].performed_by == 41 and logs[-1].actor_type == "staff" and logs[1].remarks == "looks legible"
    assert all((entry.primary_link_type, entry.primary_link_id) == ("user", 5) for entry in logs)


async def test_invalid_transitions_are_refused_with_the_allowed_ones(db, catalog_ready):
    waiting = await _register(db)                                # pending_upload: no files yet
    assert waiting.verification_status == "pending_upload"
    with pytest.raises(ConflictError) as excinfo:
        await verification.verify(db, waiting, schema.VerifyRequest())
    assert excinfo.value.data["allowed"] == ["uploaded"]

    uploaded = await _register(db, files=[_file()])
    with pytest.raises(ConflictError):
        await verification.request_resubmission(db, uploaded, "nope")   # not from 'uploaded'
    assert uploaded.verification_status == "uploaded"            # a refused transition changes nothing


async def test_rejection_then_resubmission_creates_a_new_version(db, catalog_ready):
    old = await _register(db, "PAN_CARD", files=[_file("v1.pdf")], links=[_owner("user", 5)], issued_date=date(2026, 1, 1))
    await verification.submit_for_review(db, old)
    await verification.reject(db, old, "blurry")
    assert (old.verification_status, old.is_verified, old.rejection_reason, old.verified_by) == ("rejected", False, "blurry", None)

    with pytest.raises(ConflictError):                           # only from the states that ask for it
        await service.resubmit_document(db, (await _register(db, files=[_file()])).uuid, schema.ResubmitRequest(files=[_file()]))
    await verification.request_resubmission(db, old, "please retake")
    new = await service.resubmit_document(db, old.uuid, schema.ResubmitRequest(files=[_file("v2.pdf")]))

    assert (new.version_number, new.resubmission_count, new.is_latest_version, new.verification_status) == (2, 1, True, "uploaded")
    assert new.supersedes_document_id == old.id and new.issued_date == date(2026, 1, 1)
    assert [(entry.linkable_type, entry.linkable_id, entry.link_role) for entry in new.links] == [("user", 5, "owner")]
    old = await crud.get_document(db, old.uuid, refresh=True)
    assert old.is_latest_version is False and old.verification_status == "resubmission_required"
    assert [d.uuid for d in await service.list_documents_for_entity(db, "user", 5)] == [new.uuid]
    assert {d.uuid for d in await service.list_documents_for_entity(db, "user", 5, latest_only=False)} == {old.uuid, new.uuid}
    assert (await crud.list_logs(db, new.id))[0].action == "resubmitted"


async def test_a_version_is_superseded_only_once(db, catalog_ready):
    old = await _register(db, "PAN_CARD", files=[_file()])
    await verification.reject(db, old, "bad")
    await verification.request_resubmission(db, old, "again")
    await service.resubmit_document(db, old.uuid, schema.ResubmitRequest(files=[_file("v2.pdf")]))

    with pytest.raises(ConflictError, match="latest"):
        await service.resubmit_document(db, old.uuid, schema.ResubmitRequest(files=[_file("v2b.pdf")]))
    with pytest.raises(IntegrityError):                          # and the database agrees
        await crud.create_document(db, {"document_type_id": old.document_type_id, "document_purpose": old.document_purpose,
                                        "version_number": 3, "supersedes_document_id": old.id})


async def test_the_database_keeps_the_is_verified_cache_honest(db, catalog_ready):
    doc = await _register(db)                                    # pending_upload
    with pytest.raises(IntegrityError, match="chk_document_is_verified_cache"):
        await db.execute(text("UPDATE documents SET is_verified = true WHERE id = :id"), {"id": doc.id})


async def test_verified_documents_past_their_expiry_are_expired_by_the_sweep(db, catalog_ready):
    stale = await _register(db, "PAN_CARD", files=[_file()])
    fresh = await _register(db, "PAN_CARD", files=[_file()])
    for doc, expiry in ((stale, date.today() - timedelta(days=1)), (fresh, date.today() + timedelta(days=30))):
        await verification.verify(db, doc, schema.VerifyRequest())
        doc.expiry_date = expiry
    await db.flush()

    assert await verification.expire_due_documents(db) == 1
    assert (stale.verification_status, stale.is_verified) == ("expired", False)
    assert fresh.verification_status == "verified"
    last = (await crud.list_logs(db, stale.id))[-1]
    assert (last.action, last.actor_type, last.performed_by) == ("expired", VerificationActorType.SYSTEM.value, None)
    assert await verification.expire_due_documents(db) == 0      # idempotent


# ── integration: deletion and isolation ─────────────────────────────────────

async def test_soft_delete_cascades_to_files_and_links_and_is_logged(db, catalog_ready):
    doc = await _register(db, files=[_file("a.pdf")], links=[_owner("user", 5)])
    await service.soft_delete_document(db, doc.uuid, reason="duplicate", actor_id=3)

    assert await crud.get_document(db, doc.uuid) is None
    with pytest.raises(NotFoundError):
        await service.get_document(db, doc.uuid)
    assert await service.list_documents_for_entity(db, "user", 5) == []
    child = await db.scalar(select(DocumentFile).where(DocumentFile.document_id == doc.id).execution_options(include_deleted=True))
    assert child.deleted_at is not None and child.deleted_reason == "duplicate" and child.deleted_by == 3
    last = (await crud.list_logs(db, doc.id))[-1]
    assert (last.action, last.previous_status, last.new_status, last.remarks) == ("deleted", "uploaded", None, "duplicate")
    assert last.primary_link_id == 5                             # snapshotted before the link was deleted


async def test_a_file_cannot_point_at_another_tenants_document(db, catalog_ready):
    doc = await _register(db, files=[_file()])
    other = Tenant(tenant_code="OTHER", name="Other", primary_contact_email="ops@other.example")
    db.add(other)
    await db.flush()
    db.add(DocumentFile(tenant_id=other.id, document_id=doc.id, file_name="x.pdf", file_key="k/x"))
    with pytest.raises(IntegrityError, match="fk_document_files_tenant_document"):
        await db.flush()


# ── integration: the email delivery path ────────────────────────────────────

async def test_email_attachments_load_from_links_and_skip_deleted_documents(db, catalog_ready, tmp_path):
    from app.tasks.emails import _load_attachments

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 hello")
    email = Email(email_to=["a@b.example"], all_recipients=["a@b.example"], email_from="n@x.example",
                  subject="Report", status="pending")
    db.add(email)
    await db.flush()

    doc = await _register(db, files=[schema.FileIn(file_name="report.pdf", file_key=str(path),
                                                   file_storage_provider="local_disk")])
    remote = await _register(db, files=[_file("in-s3.pdf")])     # object-store files are skipped, loudly
    await crud.attach_documents_to_entity(db, "email", email.id, [doc.uuid, remote.uuid],
                                          context_by_id={doc.uuid: {"is_inline": True, "content_id": "cid:logo"}})

    loaded = await _load_attachments(db, email)
    assert [(a.filename, a.content, a.content_id) for a in loaded] == [("report.pdf", b"%PDF-1.4 hello", "cid:logo")]

    await service.soft_delete_document(db, doc.uuid)
    assert await _load_attachments(db, email) == []              # a deleted document is never sent


async def test_composing_an_email_with_a_missing_attachment_fails_instead_of_dropping_it(db, catalog_ready, monkeypatch):
    from app.modules.emails import service as email_service
    from app.modules.emails.schema import EmailAttachmentMeta, EmailCreate

    monkeypatch.setattr(email_service, "_enqueue_delivery", lambda *a, **kw: pytest.fail("must not be queued"))
    ghost = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(NotFoundError, match=ghost):
        await email_service.compose_and_queue_email(db, EmailCreate(
            to=["a@b.example"], subject="Hi", body_text="x", attachments=[EmailAttachmentMeta(document_id=ghost)]))

    # A real attachment is linked to the email (inline data on the link) and the email is queued.
    doc = await _register(db)
    queued = []
    monkeypatch.setattr(email_service, "_enqueue_delivery", lambda email, **kw: queued.append(email.id))
    email = await email_service.compose_and_queue_email(db, EmailCreate(
        to=["a@b.example"], subject="Hi", body_text="x",
        attachments=[EmailAttachmentMeta(document_id=doc.uuid, is_inline=True, content_id="cid:logo")]))
    assert queued == [email.id]
    link = (await crud.get_document(db, doc.uuid, refresh=True)).links[0]
    assert (link.linkable_type, link.linkable_id, link.link_role) == ("email", email.id, "attachment")
    assert link.context == {"is_inline": True, "content_id": "cid:logo"}


# ── HTTP ────────────────────────────────────────────────────────────────────

def _aadhaar_body(owner_id: int) -> dict:
    return {
        "document_type_code": "AADHAAR", "document_number": "1234 5678 9012",
        "files": [{"file_name": "front.jpg", "file_key": "k/front.jpg", "page_side": "front"},
                  {"file_name": "back.jpg", "file_key": "k/back.jpg", "page_side": "back"}],
        "links": [{"linkable_type": "user", "linkable_id": owner_id, "link_role": "owner"}],
    }


async def test_api_register_read_and_list_by_entity(worlds, catalog_ready):
    client, acme, globex = worlds
    created = await client.post("/api/documents", json=_aadhaar_body(acme.member.id), headers=acme.auth(acme.member))
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["verification_status"] == "uploaded" and body["document_type_code"] == "AADHAAR"
    assert body["document_number_masked"] == "XXXXXXXX9012" and "document_number" not in body
    assert [f["page_side"] for f in body["files"]] == ["front", "back"] and body["files"][0]["is_primary"]
    assert body["links"][0]["linkable_type"] == "user" and body["created_by_name"] == acme.member.name
    assert "1234 5678" not in created.text

    fetched = await client.get(f"/api/documents/{body['id']}", headers=acme.auth(acme.member))
    assert fetched.status_code == 200 and fetched.json()["data"]["id"] == body["id"]
    listed = await client.get("/api/documents/for-entity", params={"linkable_type": "user", "linkable_id": acme.member.id},
                              headers=acme.auth(acme.member))
    assert [d["id"] for d in listed.json()["data"]] == [body["id"]]

    # Another tenant cannot see it, not even by guessing the id.
    assert (await client.get(f"/api/documents/{body['id']}", headers=globex.auth(globex.member))).status_code == 404


async def test_api_reviewer_actions_need_a_tenant_admin(worlds, catalog_ready):
    client, acme, _ = worlds
    doc = (await client.post("/api/documents", json=_aadhaar_body(acme.member.id), headers=acme.auth(acme.member))).json()["data"]
    url = f"/api/documents/{doc['id']}"

    for action, payload in (("verify", {}), ("reject", {"reason": "x"}), ("request-resubmission", {"reason": "x"})):
        denied = await client.post(f"{url}/{action}", json=payload, headers=acme.auth(acme.member))
        assert denied.status_code == 403, action

    submitted = await client.post(f"{url}/submit", headers=acme.auth(acme.member))      # the owner may submit
    assert submitted.status_code == 200 and submitted.json()["data"]["verification_status"] == "in_review"
    verified = await client.post(f"{url}/verify", json={}, headers=acme.auth(acme.admin))
    assert verified.status_code == 200 and verified.json()["data"]["is_verified"] is True

    trail = (await client.get(f"{url}/logs", headers=acme.auth(acme.member))).json()["data"]
    assert [(t["action"], t["performed_by"]) for t in trail] == [
        ("uploaded", acme.member.id), ("in_review", acme.member.id), ("verified", acme.admin.id)]
    assert (await client.post(f"{url}/reject", json={"reason": "late"}, headers=acme.auth(acme.admin))).status_code == 200
    assert (await client.post(f"{url}/verify", json={}, headers=acme.auth(acme.admin))).status_code == 409


async def test_api_rule_violations_are_422_and_unknowns_404(worlds, catalog_ready):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    two_fronts = _aadhaar_body(acme.member.id)
    two_fronts["files"][1]["page_side"] = "front"
    refused = await client.post("/api/documents", json=two_fronts, headers=headers)
    assert refused.status_code == 422 and refused.json()["code"] == "document_rule_violation"

    assert (await client.post("/api/documents", json={"document_type_code": "NOPE"}, headers=headers)).status_code == 404
    assert (await client.post("/api/documents", json={"links": [{"linkable_type": "bogus", "linkable_id": 1}]},
                              headers=headers)).status_code == 422
    types = (await client.get("/api/documents/types", headers=headers)).json()["data"]
    assert "AADHAAR" in {t["code"] for t in types}
    assert (await client.get("/api/documents/types/NOPE", headers=headers)).status_code == 404
