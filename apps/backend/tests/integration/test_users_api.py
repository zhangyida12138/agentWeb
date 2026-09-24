from httpx import AsyncClient


async def test_create_then_list_users(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"email": "Alice@Example.com", "display_name": "Alice"},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["email"] == "alice@example.com"
    assert created["is_active"] is True

    listing = await client.get("/api/v1/users")
    assert listing.status_code == 200
    assert [user["email"] for user in listing.json()] == ["alice@example.com"]


async def test_duplicate_email_returns_409(client: AsyncClient) -> None:
    payload = {"email": "alice@example.com", "display_name": "Alice"}
    await client.post("/api/v1/users", json=payload)

    response = await client.post("/api/v1/users", json=payload)

    assert response.status_code == 409


async def test_get_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


async def test_invalid_email_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"email": "not-an-email", "display_name": "Alice"},
    )

    assert response.status_code == 422
