from uuid import UUID

from fastapi.testclient import TestClient

from app.modules.identity.schemas import OrganizationCreate
from app.modules.identity.store import MemoryIdentityStore
from tests.conftest import auth_header


async def _seed_org(store: MemoryIdentityStore, user_id: UUID, name: str, kind: str = "pharmacy"):
    await store.ensure_profile(user_id, full_name=name, account_kind="staff")
    return await store.create_organization(
        user_id, OrganizationCreate(name=name, type=kind)  # type: ignore[arg-type]
    )


def test_user_sees_own_profile(client: TestClient, store: MemoryIdentityStore, user_a_id) -> None:
    token_headers = auth_header(str(user_a_id), "a@example.com")
    response = client.get("/api/v1/me", headers=token_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user_a_id)
    assert body["email"] == "a@example.com"
    assert body["memberships"] == []


def test_create_pharmacy_org_and_list_members(
    client: TestClient, store: MemoryIdentityStore, user_a_id
) -> None:
    headers = auth_header(str(user_a_id), "a@example.com")
    created = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Al-Noor Pharmacy", "type": "pharmacy"},
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["id"]
    members = client.get(f"/api/v1/organizations/{org_id}/members", headers=headers)
    assert members.status_code == 200
    rows = members.json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == str(user_a_id)
    assert rows[0]["role"] == "pharmacy_admin"


def test_cannot_create_platform_org(client: TestClient, user_a_id) -> None:
    headers = auth_header(str(user_a_id), "a@example.com")
    response = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Platform", "type": "platform"},
    )
    assert response.status_code == 403


def test_idor_other_pharmacy_is_not_found(
    client: TestClient, store: MemoryIdentityStore, user_a_id, user_b_id
) -> None:
    headers_a = auth_header(str(user_a_id), "a@example.com")
    headers_b = auth_header(str(user_b_id), "b@example.com")
    org_a = client.post(
        "/api/v1/organizations",
        headers=headers_a,
        json={"name": "Pharmacy A", "type": "pharmacy"},
    ).json()
    org_b = client.post(
        "/api/v1/organizations",
        headers=headers_b,
        json={"name": "Pharmacy B", "type": "pharmacy"},
    ).json()

    forbidden = client.get(f"/api/v1/organizations/{org_a['id']}", headers=headers_b)
    assert forbidden.status_code == 404

    members = client.get(f"/api/v1/organizations/{org_a['id']}/members", headers=headers_b)
    assert members.status_code == 404

    audit = client.get(f"/api/v1/organizations/{org_a['id']}/audit-logs", headers=headers_b)
    assert audit.status_code == 404

    patch = client.patch(
        f"/api/v1/organizations/{org_a['id']}",
        headers=headers_b,
        json={"name": "Hijacked"},
    )
    assert patch.status_code == 404

    still_a = client.get(f"/api/v1/organizations/{org_a['id']}", headers=headers_a)
    assert still_a.status_code == 200
    assert still_a.json()["name"] == "Pharmacy A"
    assert org_b["id"] != org_a["id"]


def test_staff_cannot_create_invite_or_read_audit(
    client: TestClient, store: MemoryIdentityStore, user_a_id, user_b_id
) -> None:
    headers_admin = auth_header(str(user_a_id), "admin@example.com")
    org = client.post(
        "/api/v1/organizations",
        headers=headers_admin,
        json={"name": "Staff Test Pharmacy", "type": "pharmacy"},
    ).json()
    invite = client.post(
        f"/api/v1/organizations/{org['id']}/invites",
        headers=headers_admin,
        json={"role": "pharmacy_staff", "expires_in_hours": 24},
    )
    assert invite.status_code == 201
    code = invite.json()["code"]

    headers_staff = auth_header(str(user_b_id), "staff@example.com")
    accepted = client.post("/api/v1/invites/accept", headers=headers_staff, json={"code": code})
    assert accepted.status_code == 200

    staff_invite = client.post(
        f"/api/v1/organizations/{org['id']}/invites",
        headers=headers_staff,
        json={"role": "pharmacy_staff"},
    )
    assert staff_invite.status_code == 403

    staff_audit = client.get(f"/api/v1/organizations/{org['id']}/audit-logs", headers=headers_staff)
    assert staff_audit.status_code == 403

    admin_audit = client.get(f"/api/v1/organizations/{org['id']}/audit-logs", headers=headers_admin)
    assert admin_audit.status_code == 200
    actions = {row["action"] for row in admin_audit.json()}
    assert "organization.create" in actions
    assert "invite.create" in actions


def test_invite_cannot_assign_supplier_role_to_pharmacy(
    client: TestClient, user_a_id
) -> None:
    headers = auth_header(str(user_a_id), "a@example.com")
    org = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Role Guard Pharmacy", "type": "pharmacy"},
    ).json()
    response = client.post(
        f"/api/v1/organizations/{org['id']}/invites",
        headers=headers,
        json={"role": "supplier_admin"},
    )
    assert response.status_code == 422


def test_supplier_admin_cannot_read_pharmacy(
    client: TestClient, user_a_id, user_b_id
) -> None:
    pharmacy = client.post(
        "/api/v1/organizations",
        headers=auth_header(str(user_a_id), "pharm@example.com"),
        json={"name": "Only Pharmacy", "type": "pharmacy"},
    ).json()
    client.post(
        "/api/v1/organizations",
        headers=auth_header(str(user_b_id), "sup@example.com"),
        json={"name": "Only Supplier", "type": "supplier"},
    )
    response = client.get(
        f"/api/v1/organizations/{pharmacy['id']}",
        headers=auth_header(str(user_b_id), "sup@example.com"),
    )
    assert response.status_code == 404


def test_profile_update(client: TestClient, user_a_id) -> None:
    headers = auth_header(str(user_a_id), "a@example.com")
    response = client.patch("/api/v1/me", headers=headers, json={"full_name": "Lina Hassan", "phone": "+970555"})
    assert response.status_code == 200
    assert response.json()["full_name"] == "Lina Hassan"
    assert response.json()["phone"] == "+970555"

    refreshed = client.get("/api/v1/me", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["phone"] == "+970555"


def test_validation_errors_do_not_echo_submitted_values(client: TestClient, user_a_id) -> None:
    secret_value = "sensitive-invalid-organization-name"
    response = client.post(
        "/api/v1/organizations",
        headers=auth_header(str(user_a_id), "a@example.com"),
        json={"name": secret_value, "type": "unknown-type"},
    )
    assert response.status_code == 422
    assert secret_value not in response.text
    assert '"input"' not in response.text
