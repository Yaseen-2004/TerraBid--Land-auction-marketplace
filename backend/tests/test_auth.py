from tests.conftest import PASSWORD, auth_headers, create_user

from app.models import UserRole


async def test_register_returns_token_and_never_exposes_password(client):
    response = await client.post(
        "/api/auth/register",
        json={"name": "Asha Rao", "email": "Asha@Example.com", "password": "Str0ngPass!"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == "asha@example.com"
    assert body["user"]["role"] == "BIDDER"
    assert "password" not in response.text and "hashed_password" not in response.text


async def test_register_cannot_self_assign_admin(client):
    response = await client.post(
        "/api/auth/register",
        json={"name": "Mallory", "email": "m@example.com", "password": "Str0ngPass!", "role": "ADMIN"},
    )
    assert response.status_code == 422
    assert response.json()["success"] is False


async def test_register_duplicate_email(client):
    payload = {"name": "Asha", "email": "dup@example.com", "password": "Str0ngPass!"}
    assert (await client.post("/api/auth/register", json=payload)).status_code == 201
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["error_code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_rejects_weak_password(client):
    response = await client.post(
        "/api/auth/register", json={"name": "Weak", "email": "weak@example.com", "password": "password"}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


async def test_login_and_me(client):
    user = await create_user(UserRole.SELLER, email="seller@example.com")
    response = await client.post("/api/auth/login", json={"email": "SELLER@example.com", "password": PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == user.id
    assert me.json()["role"] == "SELLER"


async def test_login_invalid_credentials(client):
    await create_user(email="known@example.com")
    wrong_password = await client.post("/api/auth/login", json={"email": "known@example.com", "password": "nope12345"})
    unknown_email = await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope12345"})
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json() == {
            "success": False,
            "message": "Invalid email or password.",
            "error_code": "INVALID_CREDENTIALS",
        }


async def test_unauthorized_access(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})).json()["error_code"] == "INVALID_TOKEN"
    assert (await client.post("/api/auctions/1/bid", json={"amount": 100})).status_code == 401
    assert (await client.get("/api/admin/stats")).status_code == 401


async def test_role_based_authorization(client):
    bidder = await create_user(UserRole.BIDDER)
    response = await client.get("/api/admin/stats", headers=auth_headers(bidder))
    assert response.status_code == 403
    response = await client.post("/api/properties", json={}, headers=auth_headers(bidder))
    assert response.status_code in (403, 422)


async def test_disabled_account_token_is_rejected(client, db):
    user = await create_user()
    headers = auth_headers(user)
    db_user = await db.get(type(user), user.id)
    db_user.is_active = False
    await db.commit()
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
