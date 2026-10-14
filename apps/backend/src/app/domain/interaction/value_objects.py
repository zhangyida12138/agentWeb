"""互动上下文的值对象。

与 ``domain/blog/value_objects.py`` 同一套写法：``@dataclass(frozen=True, slots=True)``，
构造即校验，非法值在领域内根本不存在。

``COMMENT_CONTENT_MAX_LEN`` 同样是**唯一事实来源**：被 mapper 拿去当数据库列宽。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.domain.interaction.exceptions import (
    InvalidCommentContentError,
    InvalidLikeTargetError,
)

# ──────────────────────── 长度上限 ────────────────────────

# 评论比文章正文短得多：一则跟帖写到 2000 字已经远超「评论」的语义
COMMENT_CONTENT_MAX_LEN: Final = 2000

# ``LikeTargetType`` 那几个取值的最大长度（``comment`` 7 个字符）。
#
# 它放在领域而不是持久化层，是因为它同一个数字要服务三处：
#   数据库列宽、请求 schema 的长度上限、值对象的合法性检查。
# 三处各写一个 20，改宽的时候一定会漏掉一处，而漏掉的表现是
# 「schema 放行了、列写入被截断」这种只在极端输入下才出现的怪现象。
LIKE_TARGET_TYPE_MAX_LEN: Final = 20

# 这里曾经有一个 ``COMMENT_TREE_DEPTH = 2``，用来把「回复一条回复」归一到根评论下。
# 它被删掉是因为那个做法**不可逆**：归一发生在落库那一刻，
# 「他到底在回谁」的信息当场就没了，事后想把树还原成真实的层级也做不到。
# 而它想解决的问题（窄屏上越缩越窄）本来就不该由数据模型来管——
# 那是渲染问题，前端只需从第二层起不再加缩进即可，
# 库里照样存真实的父子关系。
#
# 所以现在这个上下文里**没有**树的层数上限常量：
# 层数上限由界面决定，数据层不设限，也不需要额外的校验。


# ──────────────────────────── 值对象 ────────────────────────────


@dataclass(frozen=True, slots=True)
class CommentContent:
    """评论正文。

    与 ``PostContent`` 不同，这里**要 strip**：
        评论没有 Markdown 语义（前端按纯文本渲染，不解析缩进代码块），
        行首空格不具备任何含义，而「一个只敲了空格的评论」显然是误操作。
        首尾空白在入库前被抹平，于是「内容为空」的判断只需要看 strip 之后的结果。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise InvalidCommentContentError("评论内容不能为空")
        if len(normalized) > COMMENT_CONTENT_MAX_LEN:
            raise InvalidCommentContentError(f"评论内容最多 {COMMENT_CONTENT_MAX_LEN} 字")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


class LikeTargetType:
    """允许被点赞的资源类型。

    与 ``PostStatus`` 一样用「类 + 常量」而不是 ``Enum``：
    库里存的是普通字符串，Enum 成员改名后旧数据就对不上了。
    ``ALL`` 是给「遍历所有合法值」用的（例如生成 OpenAPI 的 enum 列表）。
    """

    POST: Final = "post"
    COMMENT: Final = "comment"

    ALL: Final[frozenset[str]] = frozenset({POST, COMMENT})

    @staticmethod
    def parse(value: str) -> str:
        """把外部传来的字符串收敛成合法类型，不合法则抛 40041。

        ``str.lower()`` 是刻意加上的：``"Post"`` / ``"POST"`` 与 ``"post"`` 显然
        是同一个意思，为大小写差异回一个 400 属于无谓的严格。
        但**不做**去掉复数、去掉空格之类的「智能修正」——
        那种宽容会让 ``"posts"``（真实的前端笔误）悄悄写到错误的分区上。
        """
        normalized = value.strip().lower()
        if normalized not in LikeTargetType.ALL:
            raise InvalidLikeTargetError()
        return normalized


__all__ = [
    "COMMENT_CONTENT_MAX_LEN",
    "LIKE_TARGET_TYPE_MAX_LEN",
    "CommentContent",
    "LikeTargetType",
]
