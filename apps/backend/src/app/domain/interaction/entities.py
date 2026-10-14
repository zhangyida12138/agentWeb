"""互动上下文的实体。

本上下文只有一个聚合根 ``Comment``。点赞没有实体（理由见 ``__init__.py``），
所以这个文件比 ``domain/blog/entities.py`` 短得多——这是好事，
说明「互动」这个概念本身的状态机确实很小。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.interaction.exceptions import (
    CommentForbiddenError,
    CommentNotFoundError,
)
from app.domain.interaction.value_objects import CommentContent


def _utc_now() -> datetime:
    """当前时间（带时区）。

    绝不用 ``datetime.now()``：那是**本地时间且不带 tzinfo**，
    存进 ``TIMESTAMP WITH TIME ZONE`` 列时会被按「服务器所在时区」解释一次，
    于是同一个瞬间在不同机器上得到不同结果。测试本机通过、CI 换个时区就挂。
    """
    return datetime.now(UTC)


@dataclass(slots=True)
class Comment:
    """评论实体（聚合根）。

    「聚合根」的意思是：回复（``parent_id`` 指向另一条评论）仍然由
    ``CommentRepository`` 单独存取，而不是作为 ``Comment`` 的子集合挂在实体上。
    理由是回复的数量没有天然上限（一篇热文的根评论可能挂几百条回复），
    把整个子树塞进一个聚合里，意味着「改一条回复」要把整棵树加载进来——
    并发写会互相锁，内存也会随讨论规模线性膨胀。
    所以这里只保留一个 ``parent_id`` 引用，树的组装交给用例（一次性批量查）。

    删除语义是**墓碑（tombstone）而不是级联**：
        作者撤回一条评论时，它下面的回复**不会**被删除——
        那些回复是别人写的内容，凭什么因为楼上撤回而消失。
        于是已删除的评论仍然保留这一行（内容不外传、界面显示「该评论已删除」），
        作用是让它的回复有个落点，不至于变成孤儿。
        真正的清理（保留期后物理删除）将来做成离线任务，与请求路径无关。

    树的形状是**任意深度**：
        ``parent_id`` 指向真实的被回复者，不做任何归一，于是
        「A 回复 B、C 回复 A」这样的链完整保存在库里。
        缩进几层是界面的事（前端只缩进一层），数据模型不为界面做取舍。

    本实体唯一需要保证的结构性不变量是**父链无环**：
        它由**时序**而不是校验保证——一条新评论的 ``parent_id`` 必然指向
        一条已经落库的评论，而新评论自身在那之后才存在，
        所以它不可能成为自己祖先的祖先。
        能造出环的只有直接改库的人；真改出了环，读评论树的请求会一直转下去
        （SQL 的递归 CTE 与内存里的拼树都不自备环检测）。
        加一层环检测会让**每一次正常读取**都多做一次集合运算，
        换一个只可能由人工弄坏的状态，性价比不成立。
        真要查这类坏数据，一条 ``UNION``（而不是 ``UNION ALL``）的递归 CTE
        会在遇到重复行时停下来，可以直接拿它当探针。
    """

    post_id: uuid.UUID
    author_id: uuid.UUID
    content: str

    id: uuid.UUID | None = None
    # 自引用父评论。为 None 表示这是一条**根评论**。
    #
    # ⚠️ 这里存的是**真实的被回复者**，不做任何归一：
    #    回复一条回复时，parent_id 就是那条回复的 id。于是树的深度不设上限，
    #    「A 回复 B、C 回复 A」这条链在库里和读出来之后都完整保留。
    #
    # 早先的版本会把 parent_id 折到根评论上（树恒为两层），
    # 代价是**信息永久丢失**：落库那一刻「他到底在回谁」就被抹平了，
    # 事后无论怎么改代码都还原不出来（这一点已在真实数据上验证过）。
    # 层级该压多少是**展示**问题——前端只缩进一层即可，
    # 不该由数据模型替界面做决定。
    parent_id: uuid.UUID | None = None
    deleted_at: datetime | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    # ────────────── 构造 ──────────────

    @classmethod
    def create(
        cls,
        *,
        post_id: uuid.UUID,
        author_id: uuid.UUID,
        content: CommentContent,
        parent_id: uuid.UUID | None = None,
    ) -> Comment:
        """工厂方法：造一条**尚未落库**的新评论。

        为什么必须有 ``id=uuid.uuid4()`` 这一行（而不是交给数据库）：
            底层的 ``UuidPk`` 用的是 ``insert_default``——那是**列级默认值**，
            而本项目的实体→模型映射是「把实体字段显式搬进模型」，
            构造 ``CommentModel`` 时不会去读列默认值。所以 id 必须由领域先生成，
            否则 ``to_model`` 断言 id 非空时就会炸。
            （详见 infrastructure/persistence/base.py 的说明。）

        为什么 ``content`` 收的是**值对象**：
            「评论不能为空」这条规则必须只存在一处。收裸 ``str`` 就等于
            把校验推迟到某个不一定发生的时刻（甚至可能永远不发生）。

        ``author_id`` 由用例从 token 推导后传入，**不接受客户端指定**：
            否则任何登录用户都能以别人的名义发评论。

        ``parent_id`` 原样落库，**不做归一**：
            用例只负责确认「这个父评论存在、没被撤回、而且属于同一篇文章」，
            至于它是根评论还是第 N 层回复，实体不关心也不需要知道。
            唯一的不变量是**无环**，而它由「新评论的父评论必然已经存在」
            这一时序事实保证——见本类的模块说明。
        """
        return cls(
            id=uuid.uuid4(),
            post_id=post_id,
            author_id=author_id,
            content=content.value,
            parent_id=parent_id,
        )

    # ────────────── 派生属性 ──────────────

    @property
    def is_deleted(self) -> bool:
        """是否已被撤回（软删除）。判断只写在这里，别处一律用它。"""
        return self.deleted_at is not None

    @property
    def public_content(self) -> str:
        """对外可见的正文：已撤回的评论一律是空串。

        内容**留在库里**而不是就地清空，有两个好处：
            ① 误删可以由管理员恢复（原始文本还在）；
            ② 「已删除」可以是一个纯粹的表现层状态，将来想改成「保留 7 天再清理」
               不需要动数据模型。
        但对外必须一律为空——撤回的语义就是「这段话不再存在」，
        如果 API 还把它发出去，前端只要不按 flag 处理就能看到原文，
        「撤回」就成了摆设。
        """
        return "" if self.deleted_at is not None else self.content

    # ────────────── 不变量 ──────────────

    def ensure_not_deleted(self) -> None:
        """已撤回的评论对**所有**入口都等同于不存在。

        为什么「回复一条已删除的评论」要报 404 而不是允许：
            它的正文已经不外传了，新回复挂上去之后读者看到的是一条
            指向空白的对话——像是界面出了 bug。不如直接拒绝。
        """
        if self.deleted_at is not None:
            raise CommentNotFoundError()

    def ensure_deletable_by(self, actor_id: uuid.UUID, *, has_override: bool) -> None:
        """行级归属判定：``actor_id`` 是不是这条评论的作者（或持有管理特权）。

        与 ``Post.ensure_owned_by`` 完全同构，两把尺子、顺序不能反：
            ① ``has_override`` —— 由表现层查出来「调用者是否有 ``comment:delete_any``」。
               管理员需要能删任何人的评论（处置广告、人身攻击），
               这类内容由作者自己删是不现实的。
            ② 否则比对 ``author_id`` —— 「只能删自己写的评论」的落点。

        本方法**不负责**判断「你有没有 comment:delete 权限」：
            那是权限层面的事，由表现层守卫负责（40320）。
        """
        self.ensure_not_deleted()
        if has_override:
            return
        if self.author_id != actor_id:
            raise CommentForbiddenError()

    # ────────────── 状态变更 ──────────────

    def soft_delete(self) -> None:
        """标记撤回（幂等）。

        幂等的对象是**这一行**：重复调用不会把 ``deleted_at`` 刷新成新时间，
        也不会抛错。它是必需的，因为网关重试、用户连点、前端超时重发
        都会让同一条评论被删两次。

        ★ 但「用户第二次点删除」拿到的**不是** 204：删除流程的入口
          （``ensure_deletable_by`` → ``ensure_not_deleted``）先就把他拦下了，
          回 40440。接口的语义是「已撤回的评论等同于不存在」，
          这一点比“重试友好”更重要（见 ``DELETE /comments/{id}`` 的说明）。
          所以这里保证的是**行状态**幂等，而不是**接口**幂等——
          两者不是一回事，混起来读很容易得出错误结论。

        为什么是软删除而不是 ``DELETE FROM comments``：
            回复是外键指向本行的（``parent_id`` → ``comments.id``）。
            物理删除要么连带删掉别人的回复（CASCADE），要么让回复的
            ``parent_id`` 指向不存在的行，在树里表现为「凭空少了一整个分支」。
            墓碑既保住了回复的位置，又让内容彻底不再外传。
        """
        if self.deleted_at is not None:
            return
        self.deleted_at = _utc_now()
        self._touch()

    # ────────────── 内部 ──────────────

    def _touch(self) -> None:
        """任何字段变更后手动刷新 ``updated_at``（理由同 ``Post._touch``）。"""
        self.updated_at = _utc_now()


__all__ = ["Comment"]
