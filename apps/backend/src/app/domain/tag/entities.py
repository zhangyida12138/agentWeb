"""标签上下文的实体：``Tag``。

标签从「文章的附属品」升格为一个**独立资源**之后，多出来的唯一问题是：
**谁能改这个标签？**

旧模型（写文章时按需创建）里这个问题不需要回答——谁写文章谁就在建标签，
标签甚至没有一个可以对外暴露的 id。现在它有了独立 id、有了描述、有了状态，
就必须回答归属。答案沿用 blog / interaction 已经验证过的两层模型：

    守卫（表现层）   tag:update / tag:delete   →  「你这个身份能不能改标签」
    实体（这里）     ensure_manageable_by()     →  「这一个是不是你的」

于是错误码也分成两类，前端能据此给出不同提示：
    40350 TagOperationForbiddenError    —— 你有权限，但这个标签是别人的
    40051 TagOperationNotAllowedError   —— 这个标签的性质不允许被改
                                           （系统内置标签、已删除的标签）
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final
from uuid import UUID, uuid4

from app.domain.tag.exceptions import (
    TagNotFoundError,
    TagOperationForbiddenError,
    TagOperationNotAllowedError,
)
from app.domain.tag.value_objects import TagName, normalize_description


class TagStatus:
    """标签状态取值。

    用「类 + 常量」而不是 ``enum.Enum``：
        库里的就是字符串、接口里也是字符串、前端比较的也是字符串，
        中间套一层枚举只会多出一堆 ``.value`` 与 JSON 序列化的转换。
        这是全项目一致的取舍（``RoleCode`` / ``PostStatus`` 同样处理）。

    ⚠️ 这三个常量**不是类型**。它们所在的类只当命名空间用，
       所以任何形如 ``status: TagStatus`` 的参数注解都是错的——
       应当写 ``status: str``。写成 ``TagStatus`` 不会在运行时报错
       （Python 不检查注解），但类型检查器会认为「任何值都合法」，
       于是这个字段的所有拼写错误都会溜过去。

    状态语义：::

        normal   正常。出现在列表、联想、文章标签里，可以被打标。
        abnormal 受限。不再出现在联想与公开列表里，但**已打标的文章仍然显示它**——
                 用于「标签被玩坏了，先停止新使用，但历史文章不动」这种情况。
        deleted  已删除。对所有读路径不可见，等价于软删除。

    为什么 ``deleted`` 是一个**状态**而不是一个 ``deleted_at`` 列：
        标签的「删除」没有「谁什么时候删的」这种审计需求，
        而且它必须和 ``abnormal`` 互斥（一个标签不可能既受限又已删除）。
        互斥的一组取值天生就该是单列枚举——两个独立字段会让
        「都不是」「都是」这些无意义组合在数据库里真实存在。
    """

    NORMAL: Final = "normal"
    ABNORMAL: Final = "abnormal"
    DELETED: Final = "deleted"

    ALL: Final = frozenset({NORMAL, ABNORMAL, DELETED})

    @classmethod
    def parse(cls, value: str) -> str:
        """把外部传入的状态字符串校验成合法取值（列表筛选用）。

        不合法时抛错而不是静默忽略：
            ``?status=delteed`` 这种笔误如果被当成「不筛选」，
            前端会收到整份列表而且看起来完全正常，问题会被埋到很久以后。
        """
        if value not in cls.ALL:
            raise TagOperationNotAllowedError(f"未知的标签状态：{value}")
        return value


class TagType:
    """标签类型。系统内置标签供产品预置（例如首页的分类入口），用户标签由作者创建。

    ⚠️ 同样**不是类型**，注解请写 ``str``。

    ``SYSTEM`` 的可用人群被刻意收窄：它只允许管理员改动，
    因为它存在的原因是「产品需要它」，而不是「某个作者建了它」——
    让作者能改名或删掉它，等于让一个普通用户改掉首页的导航。
    """

    SYSTEM: Final = "system"
    USER: Final = "user"

    ALL: Final = frozenset({SYSTEM, USER})

    @classmethod
    def parse(cls, value: str) -> str:
        """同 ``TagStatus.parse``：非法取值明确报错，不静默忽略。"""
        if value not in cls.ALL:
            raise TagOperationNotAllowedError(f"未知的标签类型：{value}")
        return value


@dataclass(frozen=True, slots=True)
class Tag:
    """标签实体。

    为什么是 ``frozen``（与可变的 ``Post`` 实体不同）：
        ``Post`` 的状态机里有「改字段后必须刷新 updated_at」这种副作用，
        所以它需要 ``_touch()``，天然是可变的。
        ``Tag`` 的全部操作都是**整体替换**：改名就是换一个 ``Tag``，
        改描述就是换一个 ``Tag``，删除也是换一个 ``Tag``——
        没有一处需要在原地改一个字段再让别的字段跟着变。
        ``frozen`` 把「标签一旦构造出来就不会被谁顺手改掉」变成编译期（类型检查期）保证。

    ``post_count`` 是**派生值，不是 ``tags`` 表的列**：
        它只能由 ``JOIN post_tags`` 算出来，存下来就一定会过期
        （删一篇文章要记得减、软删除也要记得减、改状态还得记得减……漏一处就是脏数据）。
        只有 ``list_tags`` 会填它；其余路径一律是 ``0``，
        表示「这次查询没有统计用量」，而不是「这个标签没人用」。
    """

    id: UUID
    name: str
    slug: str
    type: str
    author_id: UUID | None
    description: str | None = None
    status: str = TagStatus.NORMAL
    post_count: int = 0

    # ────────────── 构造 ──────────────

    @classmethod
    def create(
        cls,
        *,
        name: str,
        author_id: UUID | None,
        description: str | None = None,
        type: str = TagType.USER,
    ) -> Tag:
        """建一个新标签（校验 + 生成标识）。

        ``id`` 由领域生成而不是交给数据库的 ``insert_default``：
            「这个标签的标识是什么」是业务决定，不是持久化细节。
            仓储只负责原样搬运，于是同一段创建逻辑在内存里跑测试时
            和连库跑时得到的结果完全一致。

        ``slug`` 由 ``name`` **现算**，不接受入参：
            收一个 slug 参数就等于允许「名字叫 Python、地址是 java」这种状态存在，
            而 ``?tag=python`` 的筛选又是按 slug 走的——
            于是用户点一个标签得到另一批文章，还没有任何一处代码是错的。

        ``description`` 走 ``normalize_description`` 而不是 ``TagDescription``：
            来自界面的空输入应当被理解成「不要描述」，而不是一个错误。
        """
        tag_name = TagName(name)
        return cls(
            id=uuid4(),
            name=tag_name.value,
            slug=tag_name.slug,
            type=TagType.parse(type),
            author_id=author_id,
            description=normalize_description(description),
        )

    # ────────────── 派生属性 ──────────────

    @property
    def is_deleted(self) -> bool:
        """是否已软删除。"""
        return self.status == TagStatus.DELETED

    @property
    def is_system(self) -> bool:
        """是否系统内置标签。"""
        return self.type == TagType.SYSTEM

    # ────────────── 规则 ──────────────

    def ensure_not_deleted(self) -> None:
        """已删除的标签等同于不存在。

        与 ``Post.ensure_not_deleted`` / ``Comment.ensure_not_deleted`` 同一套语义，
        也抛出同样的 404：对调用方来说「这个 id 对应一个已删除的标签」
        和「这个 id 根本不存在」应当是同一件事——差异只在数据库里，
        不该泄漏到接口上（泄漏出去就成了"用 404 探测某标签是否被删过"）。
        """
        if self.is_deleted:
            raise TagNotFoundError()

    def ensure_manageable_by(self, actor_id: UUID, *, actor_can_manage_any: bool = False) -> None:
        """确认 ``actor`` 有权改动这个标签，不合规就抛领域异常。

        四条分支，覆盖两种失败原因（详细对照见模块顶部）：

        ====================  ==========================  ==============================
        标签类型 / 归属        调用者                       结果
        ====================  ==========================  ==============================
        system                管理员                       允许（产品预置的标签只有管理员能碰）
        system                普通人                       40051 不是权限问题，是它不该被改
        user · 我的            任何人                       允许
        user · 别人的         管理员                       允许（越权钥匙）
        user · 别人的（或无主） 普通人                       40350
        ====================  ==========================  ==============================

        ⚠️ 为什么先判 ``type`` 再判归属，与 ``Post.ensure_owned_by`` 的顺序相反：
            对文章来说「是不是我的」信息量更大——文章正文本来就公开可读，
            说出归属不泄露任何东西。
            对标签来说，``type == system`` 是**平台元信息**（这一条是首页入口），
            先报 40350 会让一个不知道有内置标签的人以为「这台标签是别人的」，
            继而去找管理员要权限——而正确答案是「它谁都不能改」。
            顺序不同不是不一致，是两种信息敏感度不同。
        """
        if self.is_system:
            if actor_can_manage_any:
                return
            raise TagOperationNotAllowedError("系统内置标签只能由管理员修改")

        if actor_can_manage_any:
            return

        # ``author_id is None`` 的标签（历史数据、或创建者已注销）
        # 对普通人一律拒绝：它没有主人，于是只有拿越权钥匙的人能动。
        # 注意这里**不能**写成 ``self.author_id != actor_id``：那样
        # ``None != actor_id`` 恰好也是 True，逻辑上等价，
        # 但读起来像是「有个主人，只是不是你」——把「无主」这个真实存在的状态藏掉了。
        if self.author_id is not None and self.author_id == actor_id:
            return
        raise TagOperationForbiddenError()

    # ────────────── 变更（返回新实例，不原地改） ──────────────

    def rename(self, name: str) -> Tag:
        """改名，``slug`` 随之重新派生。

        唯一性**不在这里检查**——那要查库，是仓储的活儿
        （同 ``Slug.from_title`` 的说明：值对象只保证"给什么都能产出一个合法值"）。

        ⚠️ 改名会改变 slug，而 ``GET /posts?tag=<slug>`` 是按 slug 筛选的，
            所以已经发出去的筛选链接会失效。这与「改文章 slug 会断链」是同一件事实，
            文档里明说，让调用方知道改名的代价不止一个字段。
        """
        tag_name = TagName(name)
        return self._replace(name=tag_name.value, slug=tag_name.slug)

    def change_description(self, description: str | None) -> Tag:
        """改描述。传 ``None`` 或空串表示清空。"""
        return self._replace(description=normalize_description(description))

    def change_status(self, status: str) -> Tag:
        """改状态（下架 / 恢复 / 软删除共用）。"""
        return self._replace(status=TagStatus.parse(status))

    def mark_deleted(self) -> Tag:
        """软删除。

        不做「已经删了就不许再删」的判断：DELETE 是幂等动作，
        重复调用返回同样的结果比报错更有用（网络重试是常态）。
        """
        return self._replace(status=TagStatus.DELETED)

    # ────────────── 内部 ──────────────

    def _replace(self, **changes: object) -> Tag:
        """返回一个「字段被替换过」的新实例。

        用 ``dataclasses.replace`` 而不是 ``copy.copy`` + ``object.__setattr__``：
            后者能绕过 frozen 的拦截，于是「不可变」就退化成一句自觉遵守的约定；
            ``replace`` 走的是 ``__init__``，任何构造期校验都会重新跑一遍。
        """
        return replace(self, **changes)

    def __repr__(self) -> str:
        return f"<Tag id={self.id!r} name={self.name!r} status={self.status!r}>"


__all__ = ["Tag", "TagStatus", "TagType"]
