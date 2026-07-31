"""Unit tests for the Authentik sync field-mapping helpers (pure, no I/O)."""

from app.modules.users import authentik_sync as aks
from app.modules.users.model import User


def _user(**kw) -> User:
    u = User()
    u.id = kw.pop("id", 1)
    u.email = kw.pop("email", "jane@example.com")
    for k, v in kw.items():
        setattr(u, k, v)
    return u


def test_username_falls_back_to_email():
    assert aks._authentik_username(_user(username=None)) == "jane@example.com"
    assert aks._authentik_username(_user(username="jane")) == "jane"


def test_name_prefers_first_last_then_name():
    assert aks._authentik_name(_user(first_name="Jane", last_name="Doe")) == "Jane Doe"
    assert aks._authentik_name(_user(first_name="Jane", last_name=None)) == "Jane"
    assert aks._authentik_name(_user(name="Display Only")) == "Display Only"
    assert aks._authentik_name(_user()) == "jane@example.com"


def test_attributes_include_local_id_and_optional_phone():
    assert aks._authentik_attributes(_user(phone=None)) == {"local_user_id": 1}
    assert aks._authentik_attributes(_user(phone="+1555")) == {"local_user_id": 1, "phone": "+1555"}


def test_is_active_reflects_deactivation_and_soft_delete():
    assert aks._is_active(_user(is_deactivated=False, deleted_at=None)) is True
    assert aks._is_active(_user(is_deactivated=True, deleted_at=None)) is False


def test_profile_patch_only_emits_changed_fields():
    user = _user(username="jane", first_name="Jane", last_name="Doe",
                 email="jane@example.com", phone="+1555", is_deactivated=True)

    assert aks._profile_patch(user, {"email"}) == {"email": "jane@example.com"}
    assert aks._profile_patch(user, {"first_name"}) == {"name": "Jane Doe"}
    assert aks._profile_patch(user, {"phone"}) == {"attributes": {"local_user_id": 1, "phone": "+1555"}}
    assert aks._profile_patch(user, {"is_deactivated"}) == {"is_active": False}
    assert aks._profile_patch(user, set()) == {}


def test_link_existing_sets_pk_and_backfills_external_id():
    user = _user(external_id=None)
    aks.link_existing(user, {"pk": 42, "uuid": "abc-uuid"})
    assert user.authentik_pk == "42"
    assert user.external_id == "abc-uuid"
    assert user.authentik_sync_status == "synced"


def test_link_existing_does_not_overwrite_external_id():
    user = _user(external_id="already-set")
    aks.link_existing(user, {"pk": 42, "uuid": "abc-uuid"})
    assert user.external_id == "already-set"
