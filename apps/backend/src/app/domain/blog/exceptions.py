"""博客上下文的领域异常。

错误码沿用 core 规范：HTTP 状态码 × 100 + 同类序号。
**编号必须全局唯一**，所以这里刻意从 ``30`` 段起跳，给前两个上下文让位：

    400 类（入参非法）
        40010~40012  identity：email / username / password
        40030~40037  blog ：title / slug / content / summary / cover_url /
                            status_transition / tag_name / too_many_tags
        40040~40041  interaction：comment_content / like_target_type

    403 类（禁止访问）
        40310        identity：账号已停用
        40320        access  ：缺少权限码
        40330        blog    ：有 post:update 权限，但**这篇文章不是你的**
        40340        interaction：有 comment:delete 权限，但**这条评论不是你的**

    404 类（资源不存在）
        40410        identity：用户不存在
        40420        access  ：角色不存在
        40430        blog    ：文章不存在 / 已软删除
        40440        interaction：评论不存在 / 已删除
        40441        interaction：互动目标（文章或评论）不存在

    409 类（冲突）
        40910~40911  identity：邮箱、用户名已被占用
        40920        access  ：角色编码已被占用
        40930        blog    ：slug 已被占用
        40940        interaction：目标文章当前状态不开放互动（草稿 / 已归档）

有两组异常长得像、其实分得很开，值得单独说明：

``PermissionDeniedError``(40320) vs ``PostForbiddenError``(40330)
    前者回答「你**这个身份**能不能碰文章」——是角色/权限层面的事，
    由表现层的守卫在进用例之前抛出。
    后者回答「**这一篇**是不是你的」——是行级归属层面的事，
    只有已经过了权限守卫、拿到 ``post:update``、却在比对 ``author_id`` 时才发现越界，
    才会由领域实体抛出。
    前端据此可以做不同处理：40320 该把入口整个藏掉，40330 该提示「只能编辑自己的文章」。

``PostNotFoundError``(40430) 对「不存在」和「已删除」一视同仁
    软删除必须对调用方**不可见**：如果删除后改回「存在但没权限」，
    等于用响应差异告诉了外人「这里曾经有一篇文章」。所以统一 404。
    但这不等于「什么都伪装成 404」——见 404/403 的分工：归属越界是 403，
    因为文章正文本来就是公开可读的，伪装 404 只会让作者自己都排不出错。
命名遵循 ruff N818：异常类名以 Error 结尾。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError

# ──────────────────────────── 400 · 入参非法 ────────────────────────────
# 值对象构造失败时抛这些，保证领域内永远不存在非法的字段值


class InvalidPostTitleError(DomainError):
    """标题为空或超长。"""

    def __init__(self, message: str = "标题不能为空且不超过 200 字") -> None:
        super().__init__(40030, message, {"field": "title"})


class InvalidPostSlugError(DomainError):
    """slug 为空、含非法字符或超长。"""

    def __init__(self, message: str = "slug 只能由小写字母、数字、中文与连字符组成") -> None:
        super().__init__(40031, message, {"field": "slug"})


class InvalidPostContentError(DomainError):
    """正文为空或超长。"""

    def __init__(self, message: str = "正文不能为空且不超过 100000 字符") -> None:
        super().__init__(40032, message, {"field": "content"})


class InvalidPostSummaryError(DomainError):
    """摘要超长。"""

    def __init__(self, message: str = "摘要不超过 500 字") -> None:
        super().__init__(40033, message, {"field": "summary"})


class InvalidPostCoverUrlError(DomainError):
    """封面图地址超长。"""

    def __init__(self, message: str = "封面图地址不超过 512 字符") -> None:
        super().__init__(40034, message, {"field": "cover_url"})


class InvalidPostStatusTransitionError(DomainError):
    """不允许的状态流转。

    状态机是 ``draft → published → archived``（可再 publish 回 published）。
    这个异常的意义不是「技术上报了错」，而是**把非法流转挡在代码里**：
    没有它，"已归档的文章再次 unpublish" 会被静默接受，
    然后在某个更晚的时刻以「数据看起来对但语义已经错」的形式暴露出来。
    """

    def __init__(self, message: str = "当前状态不支持该操作") -> None:
        super().__init__(40035, message, {"field": "status"})


class InvalidTagNameError(DomainError):
    """标签名不合法（空、超长、含非法字符，或 slug 与已有标签撞车）。"""

    def __init__(self, message: str = "标签名需为 1~50 位字符") -> None:
        super().__init__(40036, message, {"field": "tag_names"})


class TooManyTagsError(DomainError):
    """单篇文章的标签数量超出上限。"""

    def __init__(self, message: str = "单篇文章最多 10 个标签") -> None:
        super().__init__(40037, message, {"field": "tag_names"})


# ──────────────────────────── 403 · 禁止访问 ────────────────────────────


class PostForbiddenError(DomainError):
    """身份合法，但目标文章不属于调用者。

    **不会**附上 ``author_id``：把「作者是谁」回给一个已经越界的人，
    等于顺手送出一个信息泄露面（能用来枚举谁写了什么）。
    前端要显示作者名，应该走列表里的公开 ``author_id`` 字段。
    """

    def __init__(self, message: str = "只能编辑或删除自己的文章") -> None:
        super().__init__(40330, message)


# ──────────────────────────── 404 · 资源不存在 ────────────────────────────


class PostNotFoundError(DomainError):
    """文章不存在，或已被软删除（两者对外不可区分）。"""

    def __init__(self, message: str = "文章不存在") -> None:
        super().__init__(40430, message)


# ──────────────────────────── 409 · 冲突 ────────────────────────────


class SlugAlreadyTakenError(DomainError):
    """slug 已被其他文章占用。

    409 而不是 400：请求本身没毛病，是**当前资源状态**让它不能成立，
    客户端改个 slug 重试就能成功——这正是 409 的语义。
    """

    def __init__(self, message: str = "该 slug 已被占用，请换一个") -> None:
        super().__init__(40930, message, {"field": "slug"})


__all__ = [
    "InvalidPostContentError",
    "InvalidPostCoverUrlError",
    "InvalidPostSlugError",
    "InvalidPostStatusTransitionError",
    "InvalidPostSummaryError",
    "InvalidPostTitleError",
    "InvalidTagNameError",
    "PostForbiddenError",
    "PostNotFoundError",
    "SlugAlreadyTakenError",
    "TooManyTagsError",
]
