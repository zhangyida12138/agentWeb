"""标签上下文的领域异常。

错误码沿用 core 规范：HTTP 状态码 × 100 + 同类序号，**全局唯一**。
完整的编号表在 ``domain/blog/exceptions.py`` 顶部（那是唯一的事实来源），
本上下文取下一个空闲的 **50** 段：identity=10 / access=20 / blog=30 / interaction=40。

    400 类（入参非法）
        40050  tag：description 超长
        40051  tag：当前状态 / 标签类型不支持该操作

    403 类（禁止访问）
        40350  tag：有 tag:update / tag:delete 权限，但**这个标签不是你的**

    404 类（资源不存在）
        40450  tag：标签不存在 / 已删除

    409 类（冲突）
        40950  tag：name 或 slug 已被占用

⚠️ 这里**刻意不再定义** ``InvalidTagNameError`` 与 ``TooManyTagsError``：

    这两个名字已经存在于 ``domain/blog/exceptions.py``（40036 / 40037）。
    它们的语义是「写文章时填的标签名不合法」与「一篇文章标签太多」——
    属于**写文章这条路径**上的规则，由 blog 上下文的 ``TagName`` 值对象守护。

    同名类在两个模块各定义一份，是那种「看起来没事、出事时极难查」的写法：
    ``except InvalidTagNameError`` 只会捕获自己 import 的那一个，
    另一个模块抛出的同名异常会一路穿过所有处理器，最后变成 500。
    同一个概念只留一个类，才能让这件事在结构上不可能发生。

有两组异常长得像、其实分得很开：

``PermissionDeniedError``(40320) vs ``TagOperationForbiddenError``(40350)
    前者回答「你**这个身份**能不能碰标签」——角色 / 权限层面的事，
    由表现层的守卫在进用例之前抛出。
    后者回答「**这一个**是不是你的」——行级归属层面的事，
    只有已经过了权限守卫、拿到 ``tag:update``、却在比对 ``author_id`` 时才发现越界，
    才会由领域实体抛出。

``TagOperationNotAllowedError``(40051) 为什么不是 403
    它不是「你没资格」，而是「这件事本身不成立」：系统内置标签不许改名、
    已删除的标签不能再改。**同一个人、同样合法的动作**，
    只因为对象状态不同就得到不同结论——这是状态问题，不是权限问题。
    前端据此可以做不同处理：403 该把入口整个藏掉，40051 该把按钮置灰。

命名遵循 ruff N818：异常类名以 Error 结尾。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError

# ──────────────────────────── 400 · 入参 / 状态不支持 ────────────────────────────


class InvalidTagDescriptionError(DomainError):
    """标签描述不合法（只有空白字符，或超长）。"""

    def __init__(self, message: str = "标签描述不合法") -> None:
        super().__init__(40050, message, {"field": "description"})


class TagOperationNotAllowedError(DomainError):
    """当前状态 / 标签类型不支持该操作。

    刻意**不带** ``field``：它描述的是「这个对象现在不能被这么动」，
    而不是「你哪个字段填错了」。前端要提示的话，该展示的是这个标签的状态，
    而不是某个输入框。
    """

    def __init__(self, message: str = "当前状态不支持该操作") -> None:
        super().__init__(40051, message)


# ──────────────────────────── 403 · 归属越界 ────────────────────────────


class TagOperationForbiddenError(DomainError):
    """身份合法，但目标标签不属于调用者。

    **不会**附上 ``author_id``：
        把「创建者是谁」回给一个已经越界的人，等于顺手送出一个信息泄露面
        （能用来枚举谁建过哪些标签）。
        前端要显示创建者，应该走列表接口里的公开 ``author_id`` 字段——
        那条路径本来就允许任何人看到。
    """

    def __init__(self, message: str = "只能编辑或删除自己的标签") -> None:
        super().__init__(40350, message)


# ──────────────────────────── 404 · 不存在 ────────────────────────────


class TagNotFoundError(DomainError):
    """标签不存在，或已被软删除。

    对「不存在」和「已删除」**一视同仁**，理由与 ``PostNotFoundError`` 相同：
        如果删掉之后改回「存在但没权限」，等于用响应差异告诉了外人
        「这里曾经有一个标签」。统一 404 把两种情况合并成一个答案。
    但这不等于「什么都伪装成 404」：归属越界仍然是 403——
    标签本来就是公开可读的，伪装 404 只会让创建者自己都排不出错。
    """

    def __init__(self, message: str = "标签不存在") -> None:
        super().__init__(40450, message, {"field": "tag"})


# ──────────────────────────── 409 · 冲突 ────────────────────────────


class TagAlreadyExistsError(DomainError):
    """标签已存在（``name`` 或 ``slug`` 与已有标签撞车）。

    ``name`` 与 ``slug`` 共用这一个异常：
        对调用方来说，「Python 这个名字被占了」和
        「另一个名字归化出的 slug 也叫 python」是同一件事——
        **这个名字我不能用**。拆成两个错误码只会让前端多写一个分支，
        而那个分支里做的事一模一样。
    """

    def __init__(self, message: str = "标签已存在") -> None:
        super().__init__(40950, message, {"field": "name"})


__all__ = [
    "InvalidTagDescriptionError",
    "TagAlreadyExistsError",
    "TagNotFoundError",
    "TagOperationForbiddenError",
    "TagOperationNotAllowedError",
]
