"""标签领域的纯单元测试：不碰数据库、不起应用。

这一层只守「规则」：slug 派生、描述归一、归属判定、软删除的可见性、状态解析……
全是纯内存对象，毫秒级，所以可以写得又细又密。
守卫挂错端点、``post_count`` 统计口径漏了草稿这类问题由
``tests/integration/test_tag_api.py`` 用真库验证，这里不重复。

为什么不测 ``post_count``：
    它是**派生值**（JOIN + GROUP BY 算出来的），实体上那个字段只有两个来源——
    仓储填的真值、或者构造时的 0。在内存里"测"它等于测自己写的字面量。
    它的对错只能在真库上验证。

为什么要对错误码写死数字：
    错误码是对外契约（前端按 40051 置灰按钮、按 40350 弹「不是你的标签」）。
    只断言异常类型的话，有人把 ``TagOperationNotAllowedError`` 的 40051
    改成 40052 测试依然全绿，而前端的置灰逻辑会静默失效。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from app.domain.blog.exceptions import InvalidTagNameError
from app.domain.blog.value_objects import TAG_NAME_MAX_LEN
from app.domain.tag.entities import Tag, TagStatus, TagType
from app.domain.tag.exceptions import (
    InvalidTagDescriptionError,
    TagNotFoundError,
    TagOperationForbiddenError,
    TagOperationNotAllowedError,
)
from app.domain.tag.value_objects import (
    TAG_DESCRIPTION_MAX_LEN,
    TagDescription,
    normalize_description,
)

# 与 domain 里的错误码一一对应，写死数字以锁住对外契约
INVALID_TAG_DESCRIPTION = 40050
TAG_OPERATION_NOT_ALLOWED = 40051
TAG_OPERATION_FORBIDDEN = 40350
TAG_NOT_FOUND = 40450

# 错误码 → 异常类型。参数化用例里用数字表达期望，最后统一翻译成类型，
# 这样「期望」读起来就是契约本身，而不必在数据里塞类对象。
_ERROR_CLASSES = {
    INVALID_TAG_DESCRIPTION: InvalidTagDescriptionError,
    TAG_OPERATION_NOT_ALLOWED: TagOperationNotAllowedError,
    TAG_OPERATION_FORBIDDEN: TagOperationForbiddenError,
    TAG_NOT_FOUND: TagNotFoundError,
}

OWNER = uuid4()
STRANGER = uuid4()


def _make_tag(
    *,
    name: str = "Python",
    author_id: UUID | None = OWNER,
    type: str = TagType.USER,
    description: str | None = None,
) -> Tag:
    """造一个已落库形态的标签（id 已生成）。

    走 ``Tag.create`` 而不是 ``Tag(...)``：直接构造会绕开
    「id 由领域生成、slug 由 name 派生」这两条规则，
    于是测试就变成了在验证一个现实中不存在的对象。
    """
    return Tag.create(name=name, author_id=author_id, type=type, description=description)


# ──────────────────────────── 构造与 slug 派生 ────────────────────────────


def test_create_strips_name_and_derives_slug() -> None:
    """名字去掉首尾空白，slug 由归一化后的名字现算。"""
    tag = _make_tag(name="  Python 入门  ")

    assert tag.name == "Python 入门"
    assert tag.slug == "python-入门"


def test_create_collapses_inner_whitespace() -> None:
    """连续的空白压成一个空格，而不是保留原样。

    不压缩的话 ``"Node  js"`` 与 ``"Node js"`` 会是两个"不同"的标签名，
    而它们派生出的 slug 相同——唯一索引会在更晚、更难懂的地方报错。
    """
    tag = _make_tag(name="Node\t\t js")

    assert tag.name == "Node js"
    assert tag.slug == "node-js"


def test_create_generates_a_fresh_id_each_time() -> None:
    """同名标签两次创建得到不同 id——唯一性靠 name/slug 的约束守住，不靠 id。"""
    first = _make_tag(name="Python")
    second = _make_tag(name="Python")

    assert isinstance(first.id, UUID)
    assert first.id != second.id


def test_create_defaults_to_user_type_normal_status_and_zero_count() -> None:
    """新标签的默认值：用户标签、正常状态、用量 0。"""
    tag = _make_tag()

    assert tag.type == TagType.USER
    assert tag.status == TagStatus.NORMAL
    assert tag.post_count == 0
    assert tag.author_id == OWNER
    assert tag.description is None


def test_create_accepts_explicit_system_type() -> None:
    """系统内置标签：type 由创建方指定，通常没有作者。"""
    tag = _make_tag(name="首页推荐", author_id=None, type=TagType.SYSTEM)

    assert tag.type == TagType.SYSTEM
    assert tag.is_system is True
    assert tag.author_id is None


def test_create_rejects_unknown_type() -> None:
    """type 白名单之外的取值明确报错，而不是静默当成 user。"""
    with pytest.raises(TagOperationNotAllowedError) as exc_info:
        _make_tag(type="official")

    assert exc_info.value.code == TAG_OPERATION_NOT_ALLOWED


def test_create_rejects_forbidden_characters_in_name() -> None:
    """``/ \\ # ? %`` 被拒——这是 blog 的 ``TagName`` 通过共享内核转发生效的证据。

    同一个名字在「写文章时按需创建标签」和「标签管理接口新建标签」两条路径上
    必须给出完全一样的结论，否则用户会看到「发文时能用、管理页建不出来」。
    """
    for bad in ("a/b", "a\\b", "a#b", "a?b", "a%b"):
        with pytest.raises(InvalidTagNameError):
            _make_tag(name=bad)


def test_create_rejects_blank_name() -> None:
    """只有空白字符的名字不是名字。"""
    with pytest.raises(InvalidTagNameError):
        _make_tag(name="   ")


def test_create_rejects_overlong_name() -> None:
    """超过上限的名字被拒，且上限与 blog 一致（不允许两边漂移）。"""
    with pytest.raises(InvalidTagNameError):
        _make_tag(name="x" * (TAG_NAME_MAX_LEN + 1))


def test_accepts_name_exactly_at_the_limit() -> None:
    """边界值本身是合法的——上限是闭区间。"""
    tag = _make_tag(name="x" * TAG_NAME_MAX_LEN)

    assert len(tag.name) == TAG_NAME_MAX_LEN


def test_distinct_names_can_collide_on_slug() -> None:
    """两个**不同**的合法名字可以归化出同一个 slug。

    这正是 ``exists_name`` 之外还必须查 ``exists_slug`` 的原因：
    只查名字的话，第二次创建会一路走到 INSERT 才撞唯一索引——
    报错时机更晚、信息更少（PG 只说"某个唯一约束冲突了"）。
    """
    dotted = _make_tag(name="Node.js")
    spaced = _make_tag(name="Node js")

    assert dotted.name != spaced.name
    assert dotted.slug == spaced.slug == "node-js"


# ──────────────────────────── 描述值对象与归一化 ────────────────────────────


def test_tag_description_strips_value() -> None:
    """描述去掉首尾空白后保存，避免数据库里存下一串看不见的空格。"""
    assert TagDescription("  一句简介  ").value == "一句简介"


def test_tag_description_rejects_blank() -> None:
    """显式构造一个空描述是误用：想表达"没有描述"应该传 None。"""
    with pytest.raises(InvalidTagDescriptionError) as exc_info:
        TagDescription("   ")

    assert exc_info.value.code == INVALID_TAG_DESCRIPTION


def test_tag_description_rejects_overlong_value() -> None:
    """超长报错而不是静默截断——静默截断会让用户以为自己的输入被保存了。"""
    with pytest.raises(InvalidTagDescriptionError) as exc_info:
        TagDescription("字" * (TAG_DESCRIPTION_MAX_LEN + 1))

    assert exc_info.value.code == INVALID_TAG_DESCRIPTION


def test_tag_description_accepts_value_at_the_limit() -> None:
    """边界值合法。"""
    value = TagDescription("字" * TAG_DESCRIPTION_MAX_LEN).value

    assert len(value) == TAG_DESCRIPTION_MAX_LEN


def test_normalize_description_turns_blank_into_none() -> None:
    """``""`` 与全空白都理解成「不要描述」，与 ``None`` 同义。

    不归一的话，前端会拿到 ``description === ''`` 并渲染出一个空白行，
    而 ``None`` 时它什么都不渲染——同一个意思两种表现。
    """
    assert normalize_description("") is None
    assert normalize_description("   ") is None
    assert normalize_description(None) is None


def test_normalize_description_trims_and_validates() -> None:
    """有内容时走完整的 ``TagDescription`` 校验。"""
    assert normalize_description("  简介  ") == "简介"

    with pytest.raises(InvalidTagDescriptionError):
        normalize_description("字" * (TAG_DESCRIPTION_MAX_LEN + 1))


def test_create_normalizes_description() -> None:
    """``Tag.create`` 里的描述已经归一化过，不需要调用方再处理。"""
    assert _make_tag(description="  简介  ").description == "简介"
    assert _make_tag(description="").description is None


# ──────────────────────────── 状态与类型解析 ────────────────────────────


@pytest.mark.parametrize("value", sorted(TagStatus.ALL))
def test_tag_status_parse_accepts_every_declared_value(value: str) -> None:
    """白名单里的取值原样返回。"""
    assert TagStatus.parse(value) == value


def test_tag_status_parse_rejects_typo() -> None:
    """拼错的状态明确报错，而不是被当成"不筛选"。

    静默忽略的后果是前端收到整份列表、看起来完全正常，
    直到有人发现「筛了已删除却还是全都在」。
    """
    with pytest.raises(TagOperationNotAllowedError) as exc_info:
        TagStatus.parse("delteed")

    assert exc_info.value.code == TAG_OPERATION_NOT_ALLOWED


def test_tag_type_parse_rejects_unknown_value() -> None:
    """同 TagStatus.parse。"""
    assert TagType.parse(TagType.SYSTEM) == TagType.SYSTEM

    with pytest.raises(TagOperationNotAllowedError) as exc_info:
        TagType.parse("admin")

    assert exc_info.value.code == TAG_OPERATION_NOT_ALLOWED


# ──────────────────────────── 归属判定 ────────────────────────────


@pytest.mark.parametrize(
    ("is_system", "owner", "can_manage_any", "expected"),
    [
        # 别人的用户标签：普通人被拒，管理员放行
        (False, "other", False, TAG_OPERATION_FORBIDDEN),
        (False, "other", True, None),
        # 自己的标签：谁都能改（管理员改自己的当然也行）
        (False, "own", False, None),
        (False, "own", True, None),
        # 无主标签（创建者已注销）：普通人一律拒绝
        (False, "none", False, TAG_OPERATION_FORBIDDEN),
        (False, "none", True, None),
        # 系统内置标签：不是"谁的"问题，而是"它不该被改"
        (True, "none", False, TAG_OPERATION_NOT_ALLOWED),
        (True, "none", True, None),
    ],
)
def test_ensure_manageable_by_matrix(
    is_system: bool,
    owner: str,
    can_manage_any: bool,
    expected: int | None,
) -> None:
    """归属判定的完整真值表（四种分支 × 两种身份）。

    表格化的价值在于「例外」也是被测的一条：
    管理员能改别人的标签、能改系统标签、能改无主标签——
    这三条如果只写在实现里而没写进测试，某次"统一收紧权限"的重构
    很容易把它们一起收掉，而副作用要到产品来问「为什么我改不了首页标签」才被发现。
    """
    author_id = {"own": STRANGER, "other": OWNER, "none": None}[owner]
    tag = _make_tag(
        author_id=author_id,
        type=TagType.SYSTEM if is_system else TagType.USER,
    )

    if expected is None:
        tag.ensure_manageable_by(STRANGER, actor_can_manage_any=can_manage_any)
        return

    with pytest.raises(_ERROR_CLASSES[expected]) as exc_info:
        tag.ensure_manageable_by(STRANGER, actor_can_manage_any=can_manage_any)

    assert exc_info.value.code == expected


def test_system_tag_reports_status_problem_not_ownership_problem() -> None:
    """系统标签对普通人报 40051 而不是 40350。

    40350 会让人以为「这是别人的标签，去要权限就行」——
    而正确答案是「它谁都不能改」。两种错判导致两种完全不同的用户行为，
    所以判定顺序（先 type 后归属）是被刻意固定在测试里的。
    """
    tag = _make_tag(name="首页推荐", author_id=None, type=TagType.SYSTEM)

    with pytest.raises(TagOperationNotAllowedError) as exc_info:
        tag.ensure_manageable_by(STRANGER)

    assert exc_info.value.code == TAG_OPERATION_NOT_ALLOWED


def test_own_tag_is_manageable_without_the_override_key() -> None:
    """作者改自己的标签不需要 ``tag:manage``——越权钥匙只用来改别人的。"""
    assert _make_tag(author_id=STRANGER).ensure_manageable_by(STRANGER) is None


# ──────────────────────────── 软删除的可见性 ────────────────────────────


def test_ensure_not_deleted_passes_for_live_tag() -> None:
    """正常标签通过。"""
    assert _make_tag().ensure_not_deleted() is None


def test_ensure_not_deleted_raises_404_for_deleted_tag() -> None:
    """已删除的标签对写路径等同于不存在（抛 404，而不是 40051）。

    报 404 而不是「已删除」是为了不泄漏「这个 id 曾经存在过」——
    否则 404 与 40051 的差异就成了一种探测别人删过什么的手段。
    """
    deleted = _make_tag().mark_deleted()

    with pytest.raises(TagNotFoundError) as exc_info:
        deleted.ensure_not_deleted()

    assert exc_info.value.code == TAG_NOT_FOUND


def test_is_deleted_only_for_deleted_status() -> None:
    """``abnormal`` 是"受限"不是"删除"——它仍然存在，只是不再被推荐。"""
    assert _make_tag().change_status(TagStatus.ABNORMAL).is_deleted is False
    assert _make_tag().mark_deleted().is_deleted is True


# ──────────────────────────── 变更返回新实例 ────────────────────────────


def test_rename_rederives_slug() -> None:
    """改名必须连带重算 slug，否则会出现"名字叫 Python、地址是 java"。"""
    renamed = _make_tag(name="Python").rename("Python 进阶")

    assert renamed.name == "Python 进阶"
    assert renamed.slug == "python-进阶"


def test_rename_does_not_mutate_the_original() -> None:
    """实体是不可变的：变更返回新实例，原实例一个字段都没动。"""
    original = _make_tag(name="Python")
    original.rename("Java")

    assert original.name == "Python"
    assert original.slug == "python"


def test_rename_validates_the_new_name() -> None:
    """改名走的是同一套 ``TagName`` 校验，不会因为"是改不是建"就放行。"""
    with pytest.raises(InvalidTagNameError):
        _make_tag().rename("a/b")


def test_rename_rechecks_uniqueness_only_at_the_repository() -> None:
    """改名本身**不**查重（查库是仓储的事），所以它总能成功。

    这条测试锁住的是职责边界：哪天有人把 exists_name 调用塞进实体，
    实体就会开始依赖仓储，这一层的测试立刻会因为没有 session 而失败。
    """
    assert _make_tag(name="Python").rename("Python").slug == "python"


def test_change_description_can_be_cleared_with_blank_input() -> None:
    """清空描述：``None`` 与 ``""`` 都必须落到 ``None``，不能落到空串。"""
    tag = _make_tag(description="简介")

    assert tag.change_description(None).description is None
    assert tag.change_description("").description is None
    assert tag.change_description("新简介").description == "新简介"


def test_change_status_parses_and_returns_new_instance() -> None:
    """改状态可以来回切：下架 → 恢复，恢复是同一个动作的反向使用。"""
    tag = _make_tag()

    abnormal = tag.change_status(TagStatus.ABNORMAL)
    assert abnormal.status == TagStatus.ABNORMAL
    assert tag.status == TagStatus.NORMAL
    assert abnormal.change_status(TagStatus.NORMAL).status == TagStatus.NORMAL


def test_change_status_rejects_unknown_value() -> None:
    """状态不合法时报 40051（状态问题），不是 400 的入参格式问题——
    格式在 Pydantic 那层就挡住了，这里一定是"格式对但取值不认识"。"""
    with pytest.raises(TagOperationNotAllowedError) as exc_info:
        _make_tag().change_status("archived")

    assert exc_info.value.code == TAG_OPERATION_NOT_ALLOWED


def test_mark_deleted_is_idempotent() -> None:
    """重复删除返回同样的结果而不是报错——网络重试是常态，DELETE 该幂等。"""
    once = _make_tag().mark_deleted()

    assert once.mark_deleted().status == TagStatus.DELETED
    assert once.mark_deleted() == once


def test_mark_deleted_keeps_id_and_slug() -> None:
    """软删除只是换状态，标识与 slug 都不动——
    否则"恢复"就没有可以还回去的东西了。"""
    tag = _make_tag(name="Python")
    deleted = tag.mark_deleted()

    assert deleted.id == tag.id
    assert deleted.slug == tag.slug
    assert deleted.name == tag.name


def test_tag_is_frozen() -> None:
    """不可变是结构保证，不是自觉遵守的约定。"""
    tag = _make_tag()

    with pytest.raises(FrozenInstanceError):
        tag.name = "Java"  # type: ignore[misc]


def test_repr_is_short_and_identifying() -> None:
    """``repr`` 只放定位信息，不放描述等长文本——调试输出要能一眼扫完。"""
    tag = _make_tag(name="Python", description="一段很长的简介")

    text = repr(tag)

    assert "Python" in text
    assert "一段很长的简介" not in text
    assert text.startswith("<Tag ")
