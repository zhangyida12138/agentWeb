"""互动上下文（interaction）的领域异常。

错误码沿用 ``core`` 规范：HTTP 状态码 × 100 + 同类序号。
**编号必须全局唯一**——完整的分配表在 ``domain/blog/exceptions.py`` 的模块文档里，
新增错误码时先去看那张表，别在本地拍一个数字：

    400 类（入参非法）
        40040        interaction：评论内容为空 / 超长
        40041        interaction：点赞目标类型不是 post / comment

    403 类（禁止访问）
        40340        interaction：有 comment:delete 权限，但**这条评论不是你的**

    404 类（资源不存在）
        40440        interaction：评论不存在 / 已删除
        40441        interaction：互动目标（文章或评论）不存在

    409 类（与资源当前状态冲突）
        40940        interaction：目标文章当前状态不开放互动（草稿 / 已归档）

三条值得单独说明的取舍：

``CommentForbiddenError``(40340) 与 ``PermissionDeniedError``(40320) 一样是「两把尺子」：
    40320 由表现层守卫抛出，回答「你**这个身份**能不能删评论」（要不要给你 ``comment:delete``）；
    40340 由领域实体抛出，回答「**这一条**是不是你写的」。
    为什么非要把删评也拆成两个码：与文章一样，``comment:delete`` 同时发给读者与管理员，
    单靠它无法表达「只能删自己的」；再开一个 admin 专用的 ``comment:delete_any``
    才能把「入场券」和「免检牌」分开。管理员能删别人的评论是必要的
    （违规内容要能处置），但读者不该顺带获得这个能力。

``CommentNotFoundError``(40440) 对「不存在」和「已删除」一视同仁：
    与 ``PostNotFoundError`` 同一逻辑——软删除必须对调用方不可见。
    另外「回复一条属于别的文章的评论」也复用这个码：
    对调用方而言，「那条评论不在我这里」和「那条评论不存在」是同一个结果，
    多一个码只会让前端多一个要处理的分支。

``InteractionClosedError``(40940) 用 409 而不是 404 或 400：
    文章**确实存在**，调用方也**看得见**它（作者看自己的草稿、所有人看已归档文章），
    只是它当前的状态不允许加评论/点赞。这不是「找不到」，也不是「参数写错了」，
    而是「与资源当前状态冲突」——正是 409 的定义。
    伪装成 404 会让作者以为自己的文章没了。

命名遵循 ruff N818：异常类名以 Error 结尾。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError

# ──────────────────────────── 400 · 入参非法 ────────────────────────────


class InvalidCommentContentError(DomainError):
    """评论内容为空、只有空白，或超出长度上限。"""

    def __init__(self, message: str = "评论内容不能为空且不超过 2000 字") -> None:
        super().__init__(40040, message, {"field": "content"})


class InvalidLikeTargetError(DomainError):
    """点赞的 ``target_type`` 不在允许的取值里。

    这是一个**必须显式报错**的情况，而不是「默认当成文章处理」：
    ``target_type`` 是前端传上来的字符串，拼成 ``"post "``/``"posts"`` 太容易了，
    静默兜底会让点赞写到错误的键上——表现为「点了没反应」「赞数不对」，
    而且排查时数据库里那一行看起来完全合法。
    """

    def __init__(self, message: str = "点赞对象类型只能是 post 或 comment") -> None:
        super().__init__(40041, message, {"field": "target_type"})


# ──────────────────────────── 403 · 禁止访问 ────────────────────────────


class CommentForbiddenError(DomainError):
    """身份合法，但这条评论不属于调用者，且调用者没有越权权限。

    **不会**附上作者的 ``author_id``：把「这条评论是谁写的」回给一个已经越界的人，
    等于用响应差异泄露了他人的身份信息。前端拿到 40340 只需要把「删除」按钮收起来。
    """

    def __init__(self, message: str = "只能删除自己发表的评论") -> None:
        super().__init__(40340, message)


# ──────────────────────────── 404 · 资源不存在 ────────────────────────────


class CommentNotFoundError(DomainError):
    """按 id 找不到评论、评论已被删除，或评论不属于指定的文章。"""

    def __init__(self, message: str = "评论不存在或已被删除") -> None:
        super().__init__(40440, message, {"field": "comment_id"})


class InteractionTargetNotFoundError(DomainError):
    """要评论 / 点赞的目标不存在（文章被删除、评论被删除）。

    与 40430（文章不存在）分开是刻意的：两者都会出现在同一个页面上，
    但前端的处理不同——40430 该整页显示「找不到这篇文章」，
    40441 只该把互动区收起来（文章正文其实是好的）。
    """

    def __init__(self, message: str = "互动目标不存在或已被删除") -> None:
        super().__init__(40441, message, {"field": "target_id"})


# ──────────────────────────── 409 · 状态冲突 ────────────────────────────


class InteractionClosedError(DomainError):
    """文章当前状态不允许评论 / 点赞（草稿或已归档）。"""

    def __init__(self, message: str = "这篇文章当前不开放评论与点赞") -> None:
        super().__init__(40940, message, {"field": "post_id"})


__all__ = [
    "CommentForbiddenError",
    "CommentNotFoundError",
    "InteractionClosedError",
    "InteractionTargetNotFoundError",
    "InvalidCommentContentError",
    "InvalidLikeTargetError",
]
