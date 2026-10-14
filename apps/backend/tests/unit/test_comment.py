"""互动领域的纯单元测试：不碰数据库、不起应用。

这一层专门守「规则」，不守「接线」：
    评论正文的收敛、两层树的归一、墓碑式删除的幂等、删除归属的两把尺子……
    全是纯内存对象，跑起来是毫秒级，因此可以写得又细又密。
    守卫挂错端点、软删除过滤漏了某个查询这类问题由
    ``tests/integration/test_interaction_api.py`` 负责，这里不重复。

为什么要对错误码做断言：
    错误码是**对外契约**（前端按 40040 在输入框下标红字、按 40340 弹「无权删除」）。
    只断言异常类型的话，有人把 ``CommentForbiddenError`` 的 40340 改成 40341
    测试依然全绿，而前端的提示会静默失效。这里把数字写死，改动就必须同时改测试。

点赞没有实体，所以这里也没有「点赞实体」的测试——
    点赞的规则（唯一约束 + 幂等）本质上由数据库承担，
    归到集成测试里用真库验证才有效；在内存里 mock 一个「唯一约束」
    只能测出 mock 写得对不对。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.domain.interaction.entities import Comment
from app.domain.interaction.exceptions import (
    CommentForbiddenError,
    CommentNotFoundError,
    InvalidCommentContentError,
    InvalidLikeTargetError,
)
from app.domain.interaction.value_objects import (
    COMMENT_CONTENT_MAX_LEN,
    LIKE_TARGET_TYPE_MAX_LEN,
    CommentContent,
    LikeTargetType,
)

# 与 domain 里的错误码一一对应，写死数字以锁住对外契约
INVALID_COMMENT_CONTENT = 40040
INVALID_LIKE_TARGET = 40041
COMMENT_FORBIDDEN = 40340
COMMENT_NOT_FOUND = 40440


def _make_comment(
    *,
    content: str = "第一条评论",
    parent_id: object = None,
    author_id: object = None,
) -> Comment:
    """造一条已落库形态的评论（id 已生成）。

    走 ``Comment.create`` 而不是直接 ``Comment(...)``：
    直接构造会绕开「id 必须由领域生成」这条规则，
    那样测试用例就变成了在验证一个现实中不存在的对象。
    """
    return Comment.create(
        post_id=uuid4(),
        author_id=author_id if author_id is not None else uuid4(),  # type: ignore[arg-type]
        content=CommentContent(content),
        parent_id=parent_id,  # type: ignore[arg-type]
    )


# ──────────────────────────── 正文收敛 ────────────────────────────


def test_content_strips_surrounding_whitespace() -> None:
    """首尾空白被抹平。

    这行的价值在于「内容为空」的判断只需要看归一化之后的结果：
    如果保留原文，``"  \\n  "`` 会通过非空检查，库里就多了一条
    看不见的评论，还带一个赞数。
    """
    assert CommentContent("  \n 你好  \n ").value == "你好"


def test_content_keeps_inner_newlines() -> None:
    """只削首尾，不动内部换行——多段评论是正常的。"""
    assert CommentContent("\n第一段\n\n第二段\n").value == "第一段\n\n第二段"


def test_blank_content_is_rejected() -> None:
    """纯空白等于空，必须拒绝。"""
    with pytest.raises(InvalidCommentContentError) as excinfo:
        CommentContent("   \n\t ")

    assert excinfo.value.code == INVALID_COMMENT_CONTENT


def test_content_over_limit_is_rejected() -> None:
    """长度按**归一化之后**的字符数算。

    若按原文长度算，客户端只要在开头补一堆空格就能绕过上限，
    而入库的正是削过空格的内容——上限形同虚设。
    """
    with pytest.raises(InvalidCommentContentError) as excinfo:
        CommentContent("x" * (COMMENT_CONTENT_MAX_LEN + 1) + "   ")

    assert excinfo.value.code == INVALID_COMMENT_CONTENT


def test_content_at_limit_is_accepted() -> None:
    """正好到上限必须放行（边界不能写成 ``>=``）。"""
    assert len(CommentContent("x" * COMMENT_CONTENT_MAX_LEN).value) == COMMENT_CONTENT_MAX_LEN


def test_content_value_object_is_frozen() -> None:
    """值对象不可变：校验完还能被改，等于校验从未发生。

    断言的是 ``FrozenInstanceError`` 而不是宽泛的 ``Exception``：
    ``@dataclass(frozen=True)`` 的赋值失败**必须**是这一个异常。
    写 ``Exception`` 的话，将来有人把 ``frozen=True`` 丢了（变成可变），
    而赋值同时又因为别的原因报错，测试依然绿——
    不变量被悄悄拆掉却没人发现，而且是在“守不变量”的测试里。
    """
    content = CommentContent("内容")

    with pytest.raises(FrozenInstanceError):
        content.value = "改一下"  # type: ignore[misc]


# ──────────────────────────── 点赞目标类型 ────────────────────────────


@pytest.mark.parametrize("raw", ["post", "POST", "Post", "  post  "])
def test_target_type_parse_normalizes_case_and_space(raw: str) -> None:
    """大小写与首尾空格都归一到唯一形态。

    大小写宽容是刻意的（``"Post"`` 与 ``"post"`` 显然是同一个意思），
    而 strip 是必需的——query / 表单里带空格是常见现象，
    为此回 400 属于无谓的严格。
    """
    assert LikeTargetType.parse(raw) == "post"


def test_target_type_parse_rejects_plural() -> None:
    """复数不做「智能修正」：``posts`` 是真实的前端笔误。

    宽容到能接受复数，就意味着这个笔误会悄悄写到 ``target_type='posts'``
    这个不存在的分区上——数据写进去了、计数永远为 0，
    而错误要到用户投诉「我点的赞不见了」时才被发现。
    """
    with pytest.raises(InvalidLikeTargetError) as excinfo:
        LikeTargetType.parse("posts")

    assert excinfo.value.code == INVALID_LIKE_TARGET


def test_target_type_parse_rejects_unknown_value() -> None:
    """未知类型直接 40041，而不是落库成任意字符串。"""
    with pytest.raises(InvalidLikeTargetError) as excinfo:
        LikeTargetType.parse("article")

    assert excinfo.value.code == INVALID_LIKE_TARGET


def test_target_type_all_covers_every_constant() -> None:
    """``ALL`` 必须与常量同步。

    它是「遍历所有合法值」的唯一来源（schema 的提示文案、校验集合），
    漏掉一个常量的表现是「这种目标类型永远被拒绝」——
    而常量本身还在、别处还在用，很难一眼看出问题。
    """
    assert {LikeTargetType.POST, LikeTargetType.COMMENT} == LikeTargetType.ALL
    assert max(len(value) for value in LikeTargetType.ALL) <= LIKE_TARGET_TYPE_MAX_LEN


# ──────────────────────────── 构造 ────────────────────────────


def test_create_generates_id_and_defaults() -> None:
    """id 由领域生成，parent_id 默认 None（根评论）。

    id 必须在这一步就有值：映射层是按「把实体字段显式搬进模型」写的，
    不会去读数据库列默认值；把 id 留给数据库就等于让映射层拿到 None。
    """
    comment = _make_comment()

    assert comment.id is not None
    assert comment.parent_id is None
    assert comment.deleted_at is None
    assert comment.created_at == comment.updated_at


def test_create_takes_plain_text_out_of_value_object() -> None:
    """实体里存裸字符串，不是值对象。

    持久化层与表现层都不该知道「CommentContent」这个类型存在，
    否则把值对象的 import 扩散到整个代码库，将来换校验方式要改一大片。
    """
    comment = _make_comment(content=" 正文 ")

    assert comment.content == "正文"
    assert isinstance(comment.content, str)


# ────────────────────── 任意深度（parent 原样保留） ──────────────────────


def test_root_comment_has_no_parent() -> None:
    """根评论的 ``parent_id`` 为空——这是“这是一段对话的开头”的唯一标记。"""
    root = _make_comment()

    assert root.parent_id is None


def test_reply_to_a_reply_keeps_its_real_parent() -> None:
    """回复一条回复时，``parent_id`` 存的是**那条回复**，不是根评论。

    这是“树可以任意深度”在领域层的落点，也是这次重设计的核心改动：
        早先的版本会把 parent 归一到根（``thread_root_id``），
        于是「他回的是谁」在落库那一刻就被抹掉了，而且不可逆——
        后来想显示“xxx 回复 xxx”时，库里的信息已经不够了。

    领域层在这里**不做任何校验**（比如“父评论必须同属一篇文章”）:
        那需要去查库，而领域实体不该拿仓储。
        存在性 / 未撤回 / 同文章三条都由用例在调用前确认。
        这里只验证“如实记录”这一件事。
    """
    root = _make_comment()
    reply = _make_comment(parent_id=root.id)

    # 用户想回复那条回复
    nested = Comment.create(
        post_id=root.post_id,
        author_id=uuid4(),
        content=CommentContent("我也说一句"),
        parent_id=reply.id,
    )

    assert nested.parent_id == reply.id
    # 明确断言“没被归一”：改回老行为时这个断言会当场红
    assert nested.parent_id != root.id


def test_chain_of_replies_keeps_every_level() -> None:
    """三级链逐层可追：每一条的 parent 都是上一条。

    领域层不设深度上限（那个常量已经被删掉了）：
        “最多几层”是界面缩进的事，不是数据的事。
        三层不算长，但足以盖住“恰好能推一层”的错误实现（
        比如把 parent 当成 root 后用 ``parent_id or id`` 拼出两层）。
    """
    first = _make_comment()
    second = _make_comment(parent_id=first.id)
    third = _make_comment(parent_id=second.id)

    assert first.parent_id is None
    assert second.parent_id == first.id
    assert third.parent_id == second.id


# ──────────────────────────── 撤回（墓碑） ────────────────────────────


def test_soft_delete_blanks_public_content_but_keeps_row() -> None:
    """撤回后对外正文为空，原文仍在行里。

    原文留在库里有两个目的：管理员可恢复、将来改成「保留 7 天再物理清理」
    不需要改数据模型。但对外必须一律为空——API 还把它发出去的话，
    前端只要不按 flag 处理就能看到原文，「撤回」就成了摆设。
    """
    comment = _make_comment(content="说错话了")

    comment.soft_delete()

    assert comment.is_deleted
    assert comment.public_content == ""
    assert comment.content == "说错话了"


def test_soft_delete_is_idempotent_and_keeps_first_timestamp() -> None:
    """重复撤回不报错，而且不会把撤回时间刷新成「第二次」。

    ``deleted_at`` 是业务时间（「这条评论何时被撤回」），
    被第二次误触刷新会让审计记录失真。这里用「时间戳不变」把这一点钉住。
    """
    comment = _make_comment()

    comment.soft_delete()
    first = comment.deleted_at
    comment.soft_delete()

    assert comment.deleted_at == first


def test_soft_delete_does_not_touch_replies() -> None:
    """撤回父评论不删除子回复。

    在纯内存对象上，这条只能验到「实体自己不持有子节点」这个结构事实；
    真正的「回复仍在树上、内容仍在」由集成测试验证
    （``test_replies_survive_root_deletion``）——那里才是这个行为发生的地方。
    """
    root = _make_comment()
    reply = _make_comment(parent_id=root.id)

    root.soft_delete()

    assert not reply.is_deleted


def test_deleted_comment_is_not_found_for_every_entry_point() -> None:
    """已撤回的评论对所有入口都等同于不存在。

    「回复一条已撤回的评论」如果放行，读者看到的是一条指向空白的对话，
    像是界面出了 bug——不如直接拒绝（40440）。
    """
    comment = _make_comment()
    comment.soft_delete()

    with pytest.raises(CommentNotFoundError) as excinfo:
        comment.ensure_not_deleted()

    assert excinfo.value.code == COMMENT_NOT_FOUND


# ──────────────────────────── 删除归属：两把尺子 ────────────────────────────


def test_author_can_delete_own_comment() -> None:
    """作者删自己的评论：无需任何特权。"""
    author_id = uuid4()
    comment = _make_comment(author_id=author_id)

    comment.ensure_deletable_by(author_id, has_override=False)  # 不抛异常即为通过


def test_other_user_cannot_delete_without_override() -> None:
    """非作者且无特权 → 40340。

    这里刻意断言「是 40340 而不是 40440」：
    对**已存在且可见**的评论越权，必须明确回「你没权限」，
    而不是假装它不存在。评论本来就是公开内容，
    假装不存在没有保护任何东西，只会让调用方以为 id 写错了。
    """
    comment = _make_comment(author_id=uuid4())

    with pytest.raises(CommentForbiddenError) as excinfo:
        comment.ensure_deletable_by(uuid4(), has_override=False)

    assert excinfo.value.code == COMMENT_FORBIDDEN


def test_admin_override_can_delete_any_comment() -> None:
    """持有 ``comment:delete_any`` 的管理员可以删任何人的评论。"""
    comment = _make_comment(author_id=uuid4())

    comment.ensure_deletable_by(uuid4(), has_override=True)  # 不抛异常即为通过


def test_override_cannot_delete_already_deleted_comment() -> None:
    """特权也救不回一条已撤回的评论：先判「存在」，再判「归属」。

    顺序不能反。如果先判归属，管理员删一条已撤回的评论会得到成功，
    而作者自己删会得到……也成功（has_override 为真时直接 return）。
    看起来无害，但意味着「撤回」这个动作是幂等的、而「删别人的」不是——
    两个本应同构的入口出现行为差异，是权限 bug 最常见的温床。
    """
    comment = _make_comment()
    comment.soft_delete()

    with pytest.raises(CommentNotFoundError):
        comment.ensure_deletable_by(uuid4(), has_override=True)
