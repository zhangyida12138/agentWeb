"""博客上下文的值对象。

值对象 = 「构造即校验、之后不可变」的小类型。它们存在的意义是：
**领域内的任何一处都拿不到非法值**，于是「标题是不是空的」这种判断
只写一次、只写在这里，而不是散落在用例和表现层里各写一遍。

本模块同时是**长度上限的唯一事实来源**：
    下面这些常量被 mapper 拿去当数据库列宽（``String(POST_TITLE_MAX_LEN)``）。
    写两遍（领域一遍、建表一遍）迟早会漂移成「代码允许 200 字、列只装得下 100 字」，
    而那种 bug 要等到线上有人写了 150 字的标题才会以 500 的形式炸出来。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.domain.blog.exceptions import (
    InvalidPostContentError,
    InvalidPostCoverUrlError,
    InvalidPostSlugError,
    InvalidPostSummaryError,
    InvalidPostTitleError,
    InvalidTagNameError,
    TooManyTagsError,
)

# ──────────────────────────── 长度上限（同时是数据库列宽） ────────────────────────────

POST_TITLE_MAX_LEN: Final = 200
POST_SLUG_MAX_LEN: Final = 120
POST_SUMMARY_MAX_LEN: Final = 500
# 正文用 Text 列（无长度限制），这个常量只是「防呆」：
# 拦住把整个文件塞进 body 的调用方，而不是假装数据库有 10 万的上限
POST_CONTENT_MAX_LEN: Final = 100_000
POST_COVER_URL_MAX_LEN: Final = 512

TAG_NAME_MAX_LEN: Final = 50
TAG_SLUG_MAX_LEN: Final = 50
MAX_TAGS_PER_POST: Final = 10

# ──────────────────────────── slug 规则 ────────────────────────────
# 允许的字符：小写字母 / 数字 / 中日韩统一表意文字（U+4E00–U+9FFF）。
#
# 为什么把中文放进来：
#   中文标题经 ASCII 化之后会**全部为空**，于是所有中文文章只能退化成
#   ``post`` / ``post-2`` / ``post-3``——URL 完全失去辨识度。
#   允许 CJK 后 ``/posts/如何设计权限`` 直接可用，浏览器与 FastAPI 会自动处理百分号编码。
# 为什么不进一步放宽：
#   一旦允许 ``/``、``.``、``%``、空格，slug 就会和路径分隔符、编码语义打架，
#   变成路由层的一个坑。白名单窄一点，代价只是「特殊符号请自己改写成中文或英文」。
_SLUG_CHARS: Final = r"a-z0-9\u4e00-\u9fff"
_SLUG_RE: Final = re.compile(rf"^[{_SLUG_CHARS}]+(?:-[{_SLUG_CHARS}]+)*$")
# 把「一段非 slug 字符」压成一个连字符，顺带完成压缩（``a  b`` → ``a-b`` 而不是 ``a--b``）
_SLUG_SEPARATOR_RE: Final = re.compile(rf"[^{_SLUG_CHARS}]+")
# 中文标题全被过滤后的兜底 slug，保证 ``slugify`` 永不返回空串
_FALLBACK_SLUG: Final = "post"

# ──────────────────────────── 标签名规则 ────────────────────────────
# 允许任意可见字符，但把下面这些挡在门外：
#   ``/ \ # ? %`` 会在 URL 里改变语义（路径分隔、片段、查询串、百分号编码）；
#   空白仅在词与词之间允许一个空格，首尾与连续空白在归一化阶段被压平。
_TAG_FORBIDDEN: Final = r"/\\#?%"
_TAG_RE: Final = re.compile(rf"^[^\s{_TAG_FORBIDDEN}]+(?: [^\s{_TAG_FORBIDDEN}]+)*$")
_TAG_WHITESPACE_RE: Final = re.compile(r"\s+")


def slugify(text: str) -> str:
    """把任意文本压成 slug 形态（不校验，只做规范化）。

    单独抽成函数而不是塞进 ``Slug.from_title``：
        标签 slug 也要用它，而标签没有独立的 ``Slug`` 值对象——
        标签的一切都从 ``name`` 派生，复用同一个变换才能保证两者永远同步。
    """
    collapsed = _SLUG_SEPARATOR_RE.sub("-", text.strip().lower()).strip("-")
    if not collapsed:
        return _FALLBACK_SLUG
    # 按「字符」截断后可能留下尾部连字符，再修一次
    return collapsed[:POST_SLUG_MAX_LEN].strip("-") or _FALLBACK_SLUG


# ──────────────────────────── 值对象 ────────────────────────────


@dataclass(frozen=True, slots=True)
class PostTitle:
    """文章标题。

    ``frozen=True`` 让实例不可变；要「改标题」只能整个换一个新对象，
    这样才能放心把值对象当字典键、当缓存的键，也不会出现
    「某处拿到了引用顺手改了它，另一个持有者莫名其妙跟着变」。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise InvalidPostTitleError()
        if len(normalized) > POST_TITLE_MAX_LEN:
            raise InvalidPostTitleError(f"标题最多 {POST_TITLE_MAX_LEN} 字")
        # frozen 数据类的赋值只能绕过 __setattr__ 的拦截，这是官方推荐写法
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Slug:
    """URL 标识（永久链接）。

    slug 一旦生成就**尽量不再变**——它不是展示字段，是地址。
    把它换掉，所有已有的链接、收藏、外部引用会一起失效。
    所以更新接口允许改 slug 是「明确要求」而非默认行为（见 ``UpdatePostUseCase``）。

    构造函数对入参先做一次 ``slugify``：``"Hello World!"`` 与 ``"hello-world"``
    得到同一个 slug。好处是前端不做任何预处理也不会收到 400。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = slugify(self.value)
        if not _SLUG_RE.fullmatch(normalized):
            raise InvalidPostSlugError()
        if len(normalized) > POST_SLUG_MAX_LEN:  # pragma: no cover - slugify 已经截断过
            raise InvalidPostSlugError(f"slug 最多 {POST_SLUG_MAX_LEN} 个字符")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def from_title(cls, title: str) -> Slug:
        """由标题推导 slug（客户端没给 slug 时的默认行为）。

        不做唯一性检查——那是仓储的活儿（要查库）。
        本方法只保证「给什么标题都能产出一个合法的 slug」。
        """
        return cls(slugify(title))

    def with_suffix(self, suffix: int | str) -> Slug:
        """拼一个后缀，用于「标题撞车」时派生 ``xxx-2`` / ``xxx-a1b2c3d4``。

        从头截断而不是从尾：``head`` 越短越好认，
        并且必须重新 ``strip('-')``，否则截断点正好落在连字符上会产生
        ``xxx--2`` 这种非法形态。
        """
        tail = f"-{suffix}"
        head = self.value[: POST_SLUG_MAX_LEN - len(tail)].strip("-")
        return Slug(f"{head}{tail}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PostContent:
    """文章正文（Markdown 源文本）。

    这里**不做 Markdown 解析**，将来也不做：
        渲染是表现层的事（前端用 react-markdown），领域只负责「这段文本是否可接受」。
        把渲染器搬进领域，等于把「换前端渲染库」变成「改领域层」。
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise InvalidPostContentError("正文不能为空")
        if len(self.value) > POST_CONTENT_MAX_LEN:
            raise InvalidPostContentError(f"正文最多 {POST_CONTENT_MAX_LEN} 字符")
        # 正文**不 strip**：Markdown 里的行首空格（缩进代码块、列表续行）是有语义的，
        # 顺手 strip 会在保存后悄悄改掉用户的排版


@dataclass(frozen=True, slots=True)
class TagName:
    """标签名。

    用**名字**而不是 id 作为对外标识：作者写文章时脑子里是「给这篇打上 Python」，
    ``POST /posts {"tag_names": ["Python"]}`` 应当开箱可用，
    而不是要求前端先调一次「创建标签」拿到 id。
    于是标签在写入路径上被当作「按需创建」的资源（见 SqlPostRepository）。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = _TAG_WHITESPACE_RE.sub(" ", self.value.strip())
        if not normalized:
            raise InvalidTagNameError("标签名不能为空")
        if len(normalized) > TAG_NAME_MAX_LEN:
            raise InvalidTagNameError(f"标签名最多 {TAG_NAME_MAX_LEN} 位字符")
        if not _TAG_RE.fullmatch(normalized):
            raise InvalidTagNameError(r"标签名不能包含 / \ # ? %")
        object.__setattr__(self, "value", normalized)

    @property
    def slug(self) -> str:
        """派生 slug。始终由 ``value`` 现算，不存字段——
        存下来就会有「改名字忘了改 slug」的可能，派生出来则从不存在这种状态。"""
        return slugify(self.value)[:TAG_SLUG_MAX_LEN].strip("-") or _FALLBACK_SLUG

    def __str__(self) -> str:
        return self.value


# ──────────────────────────── 可选字段的校验函数 ────────────────────────────
# 摘要、封面地址是纯装饰字段，没有「标识性」，不值得各造一个值对象
# （identity 上下文的 display_name / bio 也是这么处理的）。
# 但仍然必须校验，否则「领域内无非法值」这条保证就在这两个字段上破了个洞。


def _normalize_optional_text(
    value: str | None,
    *,
    max_len: int,
    error: type[InvalidPostSummaryError] | type[InvalidPostCoverUrlError],
    label: str,
) -> str | None:
    """把空串归一成 ``None``、校验长度，返回规范化结果。

    「空串 → None」这一步很关键：``""`` 和 ``None`` 在数据库里是两个值，
    在「有没有摘要」的判断里却应该是同一个意思。不归一，前端就会遇到
    ``summary === ''`` 时渲染出一个空白摘要块。
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise error(f"{label}最多 {max_len} 字符")
    return text


def normalize_summary(value: str | None) -> str | None:
    """校验并归一化摘要。"""
    return _normalize_optional_text(
        value,
        max_len=POST_SUMMARY_MAX_LEN,
        error=InvalidPostSummaryError,
        label="摘要",
    )


def normalize_cover_url(value: str | None) -> str | None:
    """校验并归一化封面图地址。

    只查长度，不查「是不是合法 URL」：
        封面图允许是站内相对路径（``/uploads/xxx.png``），
        用 ``HttpUrl`` 这类严格类型会把正常用法判死。
    """
    return _normalize_optional_text(
        value,
        max_len=POST_COVER_URL_MAX_LEN,
        error=InvalidPostCoverUrlError,
        label="封面图地址",
    )


def normalize_tags(values: Iterable[object] | None) -> tuple[TagName, ...]:
    """校验并归一化标签集合。

    做三件事，每一件都对应一种真实的脏输入：
        ① 逐个 ``TagName`` 构造 → 校验 + 空白归一；
        ② 按 slug 去重（``Python`` / ``python`` 视为同一个标签）；
        ③ 上限检查——没有上限的话，一个脚本能往一篇文章塞一万个标签。
    """
    if values is None:
        return ()
    tags = [TagName(str(item)) for item in values]
    if len(tags) > MAX_TAGS_PER_POST:
        raise TooManyTagsError()
    deduped: dict[str, TagName] = {}
    for tag in tags:
        deduped.setdefault(tag.slug, tag)
    return tuple(deduped.values())


__all__ = [
    "MAX_TAGS_PER_POST",
    "POST_CONTENT_MAX_LEN",
    "POST_COVER_URL_MAX_LEN",
    "POST_SLUG_MAX_LEN",
    "POST_SUMMARY_MAX_LEN",
    "POST_TITLE_MAX_LEN",
    "TAG_NAME_MAX_LEN",
    "TAG_SLUG_MAX_LEN",
    "PostContent",
    "PostTitle",
    "Slug",
    "TagName",
    "normalize_cover_url",
    "normalize_summary",
    "normalize_tags",
    "slugify",
]
