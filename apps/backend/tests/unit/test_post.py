"""博客领域的纯单元测试：不碰数据库、不起应用。

这一层专门守「规则」，不守「接线」：
    slug 派生规则、状态机、归属判定、可见性、PATCH 哨兵语义……
    全是纯函数 / 纯内存对象，跑起来是毫秒级，因此可以写得又细又密。
    接口层挂错守卫、依赖装配漏仓储这类问题由
    ``tests/integration/test_posts_api.py`` 负责，这里不重复。

为什么要对错误码做断言：
    错误码是**对外契约**（前端按 40320/40330 分支提示不同文案）。
    只断言异常类型的话，有人把 ``PostNotFoundError`` 的 40430 改成 40431
    测试依然全绿，而前端的提示会静默失效。这里把数字写死，
    改动就必须同时改测试——这正是我们想要的摩擦。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.blog.entities import UNSET, Post, PostStatus
from app.domain.blog.exceptions import (
    InvalidPostContentError,
    InvalidPostStatusTransitionError,
    InvalidPostSummaryError,
    InvalidPostTitleError,
    InvalidTagNameError,
    PostForbiddenError,
    PostNotFoundError,
    TooManyTagsError,
)
from app.domain.blog.value_objects import (
    MAX_TAGS_PER_POST,
    POST_SLUG_MAX_LEN,
    POST_TITLE_MAX_LEN,
    PostContent,
    PostTitle,
    Slug,
    TagName,
    normalize_cover_url,
    normalize_summary,
    normalize_tags,
    slugify,
)

# 与 domain 里的错误码一一对应，写死数字以锁住对外契约
INVALID_POST_TITLE = 40030
INVALID_POST_SLUG = 40031
INVALID_POST_STATUS = 40035
INVALID_TAG_NAME = 40036
TOO_MANY_TAGS = 40037
POST_FORBIDDEN = 40330
POST_NOT_FOUND = 40430


# ──────────────────────────── slug 派生 ────────────────────────────


def test_slugify_collapses_punctuation_into_single_hyphen() -> None:
    """连续的非 slug 字符压成**一个**连字符。

    若压成多个，``Hello  World!`` 会变成 ``hello--world``——
    一个合法但丑陋且无法通过 ``_SLUG_RE`` 反查的形态（该正则不允许连续连字符）。
    """
    assert slugify("  Hello  World!!!  ") == "hello-world"


def test_slugify_keeps_chinese() -> None:
    """中文必须保留，否则所有中文文章都会退化成 ``post`` / ``post-2`` / ``post-3``。"""
    assert slugify("如何设计权限模型") == "如何设计权限模型"


def test_slugify_falls_back_when_everything_filtered_out() -> None:
    """全是不允许的字符时兜底成 ``post``，保证永不返回空串。

    空 slug 会让 ``/posts/`` 这种路由撞上列表接口，比一个丑陋的 slug 危险得多。
    """
    assert slugify("!!!") == "post"
    assert slugify("   ") == "post"


def test_slugify_truncates_without_leaving_trailing_hyphen() -> None:
    """按字符截断后可能正好切在连字符上，必须再修一次尾。"""
    result = slugify("a" * POST_SLUG_MAX_LEN + "-b")

    assert len(result) <= POST_SLUG_MAX_LEN
    assert not result.endswith("-")


def test_slug_normalizes_input_so_frontend_needs_no_preprocessing() -> None:
    """``Slug("Hello World!")`` 与 ``Slug("hello-world")`` 必须等价。

    前端不做任何预处理就能拿到 200，而不是收到一个 400 之后
    自己再实现一遍 slug 规则（然后两套规则慢慢漂移）。
    """
    assert Slug("Hello World!").value == "hello-world"
    assert Slug("Hello World!") == Slug("hello-world")


def test_slug_from_title_is_a_derivation_of_slugify() -> None:
    assert Slug.from_title("Rust 所有权笔记") == Slug("rust-所有权笔记")


def test_slug_with_suffix_truncates_head_and_strips_hyphen() -> None:
    """派生 ``xxx-2`` 时从**头**截断，并且不能留下 ``xxx--2`` 这种尾巴。"""
    long_slug = Slug("a" * POST_SLUG_MAX_LEN)
    derived = long_slug.with_suffix(2)

    assert derived.value.endswith("-2")
    assert "--" not in derived.value
    assert len(derived.value) <= POST_SLUG_MAX_LEN


def test_empty_slug_is_rejected() -> None:
    """空 / 纯空白 slug 兜底成 ``post`` 而不是报错——它是个合法值。"""
    assert Slug("---").value == "post"


# ──────────────────────────── 标题 / 正文 ────────────────────────────


def test_post_title_trims_and_rejects_blank() -> None:
    assert PostTitle("  标题  ").value == "标题"
    with pytest.raises(InvalidPostTitleError) as excinfo:
        PostTitle("   ")
    assert excinfo.value.code == INVALID_POST_TITLE


def test_post_title_rejects_overlong() -> None:
    with pytest.raises(InvalidPostTitleError):
        PostTitle("字" * (POST_TITLE_MAX_LEN + 1))


def test_post_content_keeps_leading_whitespace() -> None:
    """正文**不做 strip**：Markdown 的行首缩进（代码块、列表续行）是有语义的。

    顺手 strip 会在保存后悄悄改掉用户的排版——那种 bug 用户很难描述清楚。
    """
    content = PostContent("    缩进代码块\n正文")

    assert content.value.startswith("    ")


def test_post_content_rejects_blank() -> None:
    with pytest.raises(InvalidPostContentError) as excinfo:
        PostContent("   \n  ")
    assert excinfo.value.code == 40032


# ──────────────────────────── 标签 ────────────────────────────


def test_tag_name_collapses_whitespace_and_derives_slug() -> None:
    tag = TagName("  Machine   Learning  ")

    assert tag.value == "Machine Learning"
    assert tag.slug == "machine-learning"


def test_tag_name_rejects_url_semantic_characters() -> None:
    """``/ \\ # ? %`` 会改变 URL 语义（路径分隔 / 片段 / 查询串 / 编码），必须挡住。"""
    with pytest.raises(InvalidTagNameError) as excinfo:
        TagName("c++/python")
    assert excinfo.value.code == INVALID_TAG_NAME


def test_normalize_tags_dedupes_by_slug_keeping_first_spelling() -> None:
    """``Python`` / ``python`` 是同一个标签。

    保留**第一次**出现的拼写：用户先写的那一个更可能是他想要的展示形态。
    """
    tags = normalize_tags(["Python", "python", "PYTHON", "FastAPI"])

    assert [tag.value for tag in tags] == ["Python", "FastAPI"]


def test_normalize_tags_rejects_too_many() -> None:
    with pytest.raises(TooManyTagsError) as excinfo:
        normalize_tags([f"tag{i}" for i in range(MAX_TAGS_PER_POST + 1)])
    assert excinfo.value.code == TOO_MANY_TAGS


def test_normalize_tags_accepts_none() -> None:
    assert normalize_tags(None) == ()


# ──────────────────────────── 可选字段归一 ────────────────────────────


def test_empty_optional_text_becomes_none() -> None:
    """空串必须归一成 ``None``。

    否则前端会拿到 ``summary === ''``，判断「有没有摘要」时多出一种假值，
    页面上会渲染出一个空白摘要块。
    """
    assert normalize_summary("") is None
    assert normalize_summary("   ") is None
    assert normalize_cover_url(None) is None
    assert normalize_summary(" 摘要 ") == "摘要"


def test_overlong_summary_is_rejected() -> None:
    with pytest.raises(InvalidPostSummaryError) as excinfo:
        normalize_summary("字" * 501)
    assert excinfo.value.code == 40033


def test_cover_url_accepts_relative_path() -> None:
    """封面对内允许站内相对路径，所以不能用严格 URL 类型校验。"""
    assert normalize_cover_url("/uploads/a.png") == "/uploads/a.png"


# ──────────────────────────── 状态机 ────────────────────────────


def test_status_parse_accepts_known_values() -> None:
    assert PostStatus.parse("draft") == PostStatus.DRAFT
    assert PostStatus.parse("published") == PostStatus.PUBLISHED


def test_status_parse_rejects_typo_instead_of_silently_ignoring() -> None:
    """``?status=publihsed`` 必须报错而不是「当没传」。

    静默忽略的话前端会收到完整列表并且看起来完全正常，问题被埋到很久以后。
    """
    with pytest.raises(InvalidPostStatusTransitionError) as excinfo:
        PostStatus.parse("publihsed")
    assert excinfo.value.code == INVALID_POST_STATUS


# ──────────────────────────── 实体工厂 ────────────────────────────


def _new_post(**overrides: object) -> Post:
    """造一篇草稿。默认值让每个用例只写自己关心的那一个参数。"""
    params: dict[str, object] = {
        "author_id": uuid4(),
        "title": PostTitle("标题"),
        "slug": Slug("biaoti"),
        "content": PostContent("# 正文"),
    }
    params.update(overrides)
    return Post.create(**params)  # type: ignore[arg-type]


def test_create_generates_id_in_domain() -> None:
    """id 必须由领域生成。

    ``UuidPk`` 用的是列级 ``insert_default``，而实体→模型映射是「显式搬字段」，
    不会去读列默认值；所以交给数据库生成 id 的话，``to_model`` 的断言会直接炸。
    """
    post = _new_post()

    assert post.id is not None
    assert post.status == PostStatus.DRAFT
    assert post.published_at is None
    assert post.view_count == 0
    assert post.deleted_at is None


def test_create_normalizes_optional_fields() -> None:
    post = _new_post(summary="  ", cover_url="")

    assert post.summary is None
    assert post.cover_url is None


def test_two_posts_never_share_an_id() -> None:
    assert _new_post().id != _new_post().id


# ──────────────────────────── 归属判定 ────────────────────────────


def test_owner_may_edit_own_post_without_override() -> None:
    author = uuid4()
    _new_post(author_id=author).ensure_owned_by(author, has_override=False)


def test_other_author_is_forbidden_with_40330_not_404() -> None:
    """越界给 403 而不是 404：已发布文章的内容本来就是公开的，它的存在不是秘密。

    假装「不存在」只会让被拒的作者拿着 404 去查前端路由，白跑一圈。
    """
    post = _new_post()

    with pytest.raises(PostForbiddenError) as excinfo:
        post.ensure_owned_by(uuid4(), has_override=False)
    assert excinfo.value.code == POST_FORBIDDEN


def test_override_lets_admin_edit_other_posts() -> None:
    """管理员持有 ``post:update_any`` 时可越过归属限制（违规处置、勘误）。"""
    _new_post().ensure_owned_by(uuid4(), has_override=True)


def test_deleted_post_is_not_found_even_for_its_owner() -> None:
    """软删除对**任何**入口都等同于不存在——包括作者自己。"""
    author = uuid4()
    post = _new_post(author_id=author)
    post.soft_delete()

    with pytest.raises(PostNotFoundError) as excinfo:
        post.ensure_owned_by(author, has_override=True)
    assert excinfo.value.code == POST_NOT_FOUND


# ──────────────────────────── 可见性 ────────────────────────────


def test_published_post_is_visible_to_everyone_including_anonymous() -> None:
    """「未登录也能看」这条产品决策在领域里的落点就是 ``viewer_id is None`` 放行。"""
    post = _new_post()
    post.publish()

    post.ensure_visible_to(None)
    post.ensure_visible_to(uuid4())


def test_draft_is_invisible_to_anonymous_and_other_users() -> None:
    """别人的草稿给 404 而不是 403：否则可以据此枚举出「这里有一篇文章」。

    草稿的内容与**存在性**都属于作者私有，对外应当完全不存在。
    """
    post = _new_post()

    with pytest.raises(PostNotFoundError) as anonymous:
        post.ensure_visible_to(None)
    assert anonymous.value.code == POST_NOT_FOUND

    with pytest.raises(PostNotFoundError):
        post.ensure_visible_to(uuid4())


def test_draft_is_visible_to_its_author() -> None:
    author = uuid4()
    _new_post(author_id=author).ensure_visible_to(author)


def test_archived_post_is_hidden_from_the_public() -> None:
    """下架后从公开列表消失，但作者（含用预览链接看自己的归档）仍可访问。"""
    author = uuid4()
    post = _new_post(author_id=author)
    post.publish()
    post.unpublish()

    post.ensure_visible_to(author)
    with pytest.raises(PostNotFoundError):
        post.ensure_visible_to(None)


# ──────────────────────────── 状态流转 ────────────────────────────


def test_publish_is_idempotent() -> None:
    """发布按钮连点 / 超时重试必须都成功。

    第二次抛错的话用户看到「发布失败」而文章其实已经发布——最糟的一类反馈。
    """
    post = _new_post()
    post.publish()
    first_published_at = post.published_at

    post.publish()

    assert post.status == PostStatus.PUBLISHED
    assert post.published_at == first_published_at


def test_republish_does_not_refresh_published_at() -> None:
    """``published_at`` 表示「第一次面向读者是什么时候」，反复上下架不能篡改它。

    一旦刷新，文章会莫名其妙跳到按发布时间排序的列表最前面。
    """
    post = _new_post()
    post.publish()
    original = post.published_at
    post.unpublish()

    post.publish()

    assert post.published_at == original


def test_unpublish_archives_rather_than_returning_to_draft() -> None:
    """下架是 ``published → archived``，不是退回草稿。

    退回 draft 会让文章从所有列表凭空消失，那更像删除，就该走软删除。
    """
    post = _new_post()
    post.publish()

    post.unpublish()

    assert post.status == PostStatus.ARCHIVED
    assert post.published_at is not None  # 历史信息保留


def test_unpublish_a_draft_is_invalid() -> None:
    """草稿没发布过，没有「下架」这个动作。"""
    post = _new_post()

    with pytest.raises(InvalidPostStatusTransitionError) as excinfo:
        post.unpublish()
    assert excinfo.value.code == INVALID_POST_STATUS


def test_soft_delete_is_idempotent_and_keeps_first_timestamp() -> None:
    post = _new_post()
    post.soft_delete()
    first = post.deleted_at

    post.soft_delete()

    assert post.deleted_at == first


# ──────────────────────────── PATCH 语义 ────────────────────────────


def test_update_content_only_touches_provided_fields() -> None:
    """只改标题时，摘要 / 封面 / 标签必须原样保留。

    这就是 ``UNSET`` 哨兵存在的全部理由：把「没传」和「传了 null」分开。
    合在一起的话，改个标题会顺手抹掉摘要——一个非常容易被漏测的数据丢失。
    """
    post = _new_post(
        summary="原摘要",
        cover_url="/a.png",
        tags=normalize_tags(["Python"]),
    )

    post.update_content(title=PostTitle("新标题"))

    assert post.title.value == "新标题"
    assert post.summary == "原摘要"
    assert post.cover_url == "/a.png"
    assert [tag.value for tag in post.tags] == ["Python"]


def test_update_content_with_explicit_none_clears_optional_fields() -> None:
    post = _new_post(summary="原摘要", cover_url="/a.png", tags=normalize_tags(["Python"]))

    post.update_content(summary=None, cover_url=None, tags=())

    assert post.summary is None
    assert post.cover_url is None
    assert post.tags == ()


def test_update_content_does_not_touch_slug() -> None:
    """改内容不该动 slug——它是地址，必须走独立的 ``change_slug``。

    把危险操作从批量更新里摘出去，比在文档里写一句「请不要改 slug」可靠得多。
    """
    post = _new_post(slug=Slug("original"))
    before = post.slug

    post.update_content(title=PostTitle("换个标题"), content=PostContent("换个正文"))

    assert post.slug == before


def test_update_content_refreshes_updated_at() -> None:
    post = _new_post()
    before = post.updated_at

    post.update_content(title=PostTitle("新标题"))

    assert post.updated_at >= before


def test_unset_is_not_none() -> None:
    """哨兵与 ``None`` 必须是两个不同的对象，否则 PATCH 语义直接失效。"""
    assert UNSET is not None
    assert repr(UNSET) == "UNSET"


# ──────────────────────────── 浏览量 ────────────────────────────


def test_register_view_accepts_database_returned_count() -> None:
    """浏览量由数据库 ``view_count = view_count + 1`` 原子自增后回传。

    在 Python 里 ``self.view_count += 1`` 再整体 update 会丢更新：
    两个并发请求读到同一个旧值，第二次写入覆盖第一次。
    """
    post = _new_post()

    post.register_view(7)

    assert post.view_count == 7


# ──────────────────────────── 值的可哈希性 ────────────────────────────


def test_value_objects_are_hashable_and_comparable() -> None:
    """值对象必须可哈希可比——否则没法当字典键（标签去重就依赖这一点）。"""
    assert len({Slug("a-b"), Slug("a-b"), Slug("a b")}) == 1
    assert {TagName("Python").slug: "x"}["python"] == "x"


def test_invalid_slug_error_code_is_stable() -> None:
    """``InvalidPostSlugError``（40031）目前**不可达**：``slugify`` 已保证产物合法。

    把「不可达」当受测事实写下来，而不是写一个永远跑不到的分支测试——
    将来有人放宽 ``_SLUG_RE`` 或改掉 slugify，这个不变式会先报错，
    提醒他回来看一眼这层兜底是否真的还需要。
    """
    for raw in ["---", "\x00", "!!!", "A  B", "  \t\n  ", "你好 世界!"]:
        value = Slug(raw).value
        assert value
        assert not value.startswith("-")
        assert not value.endswith("-")
        assert "--" not in value
