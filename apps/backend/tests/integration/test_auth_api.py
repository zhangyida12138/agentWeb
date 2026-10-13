"""认证接口集成测试（真库 + 真 ASGI 应用，见 tests/conftest.py 的策略说明）。

覆盖 PLAN.md P2.7 的验收项：
    注册 → 登录 → /me 全链路打通；错误密码 401；重复邮箱 409。
外加几条「容易在重构中被无声改坏」的契约：
    出参不得泄露 password_hash；登录不区分「用户不存在」与「密码错误」；
    PATCH 语义（没传的字段不动）；邮箱大小写归一化。
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.models.user import UserModel

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"

PASSWORD = "Sup3r-secret"


# ──────────────────────────── 测试辅助 ────────────────────────────


def _new_payload(**overrides: str) -> dict[str, str]:
    """生成一个「全新用户」的注册载荷。

    邮箱/用户名必须每个用例都不一样：唯一索引是**库级**的，
    两个用例撞了同一个邮箱，后一个会莫名其妙地拿到 409。
    """
    suffix = uuid.uuid4().hex[:10]
    payload: dict[str, str] = {
        "email": f"user_{suffix}@example.com",
        "username": f"user_{suffix}",
        "password": PASSWORD,
    }
    payload.update(overrides)
    return payload


async def _register(client: AsyncClient, **overrides: str) -> tuple[dict[str, str], dict]:
    """注册并返回 (载荷, 响应体)。返回载荷是为了断言时能对得上归一化后的值。"""
    payload = _new_payload(**overrides)
    response = await client.post(REGISTER_URL, json=payload)
    return payload, response.json()


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> dict:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    return {"status": response.status_code, "body": response.json()}


async def _auth_headers(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> dict[str, str]:
    result = await _login(client, email, password)
    assert result["status"] == 200, result["body"]
    token = result["body"]["data"]["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────── 注册 ────────────────────────────


async def test_register_creates_user_and_hides_password_hash(client: AsyncClient) -> None:
    payload, body = await _register(client)

    assert body["code"] == 0
    data = body["data"]
    assert data["email"] == payload["email"]
    assert data["username"] == payload["username"]
    assert data["is_active"] is True
    # display_name 留空时用用户名兜底，保证前端列表页永远有字可显示
    assert data["display_name"] == payload["username"]
    # 出参模型里就没有这个字段——这条断言是防止将来有人图省事直接返回 ORM 模型
    assert "password_hash" not in data


async def test_register_response_status_is_201(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_new_payload())
    assert response.status_code == 201


async def test_register_normalizes_email_to_lowercase(client: AsyncClient) -> None:
    payload, body = await _register(client, email="Mixed.Case@Example.COM")
    assert body["data"]["email"] == "mixed.case@example.com"
    # 归一化后仍能正常登录（若忘了归一化，注册时存的是大写，登录查小写就查不到）
    assert (await _login(client, payload["email"].lower()))["status"] == 200


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    payload, _ = await _register(client)

    # 换一个用户名、复用同一个邮箱
    _, body = await _register(client, email=payload["email"])

    assert body["code"] == 40910
    assert body["data"]["field"] == "email"


async def test_register_duplicate_username_returns_409(client: AsyncClient) -> None:
    payload, _ = await _register(client)

    _, body = await _register(client, username=payload["username"])

    assert body["code"] == 40911
    assert body["data"]["field"] == "username"


async def test_register_rejects_bad_payload_with_envelope(client: AsyncClient) -> None:
    """schema 校验失败也要走统一信封，而不是 FastAPI 默认的 {"detail": [...]}。"""
    response = await client.post(
        REGISTER_URL,
        json={"email": "not-an-email", "username": "a", "password": "1"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 40000
    assert "errors" in body["data"]


# ──────────────────────────── 登录 ────────────────────────────


async def test_login_returns_token_and_user(client: AsyncClient) -> None:
    payload, _ = await _register(client)

    result = await _login(client, payload["email"])

    assert result["status"] == 200
    data = result["body"]["data"]
    assert data["token"]["access_token"]
    assert data["token"]["token_type"] == "bearer"
    assert data["token"]["expires_in"] > 0
    # 顺带把用户带回来，前端登录后不必再打一次 /me
    assert data["user"]["email"] == payload["email"]
    assert "password_hash" not in data["user"]


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    payload, _ = await _register(client)

    result = await _login(client, payload["email"], password="wrong-password")

    assert result["status"] == 401
    assert result["body"]["code"] == 40110


async def test_login_with_unknown_email_is_indistinguishable(client: AsyncClient) -> None:
    """邮箱不存在与密码错误必须完全同款响应，否则接口就是个邮箱枚举器。"""
    payload, _ = await _register(client)
    wrong_password = await _login(client, payload["email"], password="wrong-password")
    unknown_email = await _login(client, "nobody@example.com")

    assert unknown_email["status"] == wrong_password["status"] == 401
    assert unknown_email["body"]["code"] == wrong_password["body"]["code"]
    assert unknown_email["body"]["message"] == wrong_password["body"]["message"]


# ──────────────────────────── 当前用户 ────────────────────────────


async def test_me_returns_current_user(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["username"] == payload["username"]


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == 40111


async def test_me_with_garbage_token_returns_401(client: AsyncClient) -> None:
    """签名不符 / 结构损坏都归为「登录态无效」，不对外区分具体原因。"""
    response = await client.get(ME_URL, headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    assert response.json()["code"] == 40111


async def test_me_rejects_token_of_deleted_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    payload, body = await _register(client)
    headers = await _auth_headers(client, payload["email"])

    user_id = uuid.UUID(body["data"]["id"])
    await db_session.execute(
        update(UserModel).where(UserModel.id == user_id).values(is_active=False)
    )
    # expire_all 是同步方法（只是标记过期，不发 SQL）；不标的话守卫会命中
    # identity map 里的旧对象，读到过期的 is_active=True，用例假绿
    db_session.expire_all()

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == 40310


async def test_disabled_user_cannot_login(client: AsyncClient, db_session: AsyncSession) -> None:
    payload, body = await _register(client)

    user_id = uuid.UUID(body["data"]["id"])
    await db_session.execute(
        update(UserModel).where(UserModel.id == user_id).values(is_active=False)
    )
    db_session.expire_all()

    result = await _login(client, payload["email"])

    assert result["status"] == 403
    assert result["body"]["code"] == 40310


# ──────────────────────────── 修改资料 ────────────────────────────


async def test_update_profile_patches_only_provided_fields(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])

    first = await client.patch(
        ME_URL, headers=headers, json={"bio": "hello", "avatar_url": "http://a/b.png"}
    )
    assert first.status_code == 200
    assert first.json()["data"]["bio"] == "hello"

    # 只改昵称：上一步写入的 bio / avatar_url 必须原样保留（PATCH 而不是 PUT）
    second = await client.patch(ME_URL, headers=headers, json={"display_name": "New Name"})
    data = second.json()["data"]
    assert data["display_name"] == "New Name"
    assert data["bio"] == "hello"
    assert data["avatar_url"] == "http://a/b.png"

    # 落库确认：重新查一次 /me，而不是只信 PATCH 的响应
    me = await client.get(ME_URL, headers=headers)
    assert me.json()["data"]["display_name"] == "New Name"
    assert me.json()["data"]["bio"] == "hello"


async def test_update_profile_empty_string_clears_optional_field(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])
    await client.patch(ME_URL, headers=headers, json={"bio": "hello"})

    response = await client.patch(ME_URL, headers=headers, json={"bio": ""})

    # 空串 = 清空（null 会被当成「没传」丢掉，所以清空只能靠空串表达）
    assert response.json()["data"]["bio"] is None


async def test_empty_patch_does_not_touch_record(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])
    before = (await client.get(ME_URL, headers=headers)).json()["data"]

    response = await client.patch(ME_URL, headers=headers, json={})

    assert response.json()["data"]["updated_at"] == before["updated_at"]


# ──────────────────────────── 修改密码 ────────────────────────────


async def test_change_password_requires_correct_old_password(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])

    response = await client.post(
        CHANGE_PASSWORD_URL,
        headers=headers,
        json={"old_password": "not-the-old-one", "new_password": "Brand-new-1"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 40110


async def test_change_password_then_old_password_stops_working(client: AsyncClient) -> None:
    payload, _ = await _register(client)
    headers = await _auth_headers(client, payload["email"])
    new_password = "Brand-new-1"

    changed = await client.post(
        CHANGE_PASSWORD_URL,
        headers=headers,
        json={"old_password": PASSWORD, "new_password": new_password},
    )
    assert changed.status_code == 200
    assert changed.json()["code"] == 0

    assert (await _login(client, payload["email"], password=new_password))["status"] == 200
    assert (await _login(client, payload["email"], password=PASSWORD))["status"] == 401
