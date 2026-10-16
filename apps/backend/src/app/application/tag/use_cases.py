"""标签上下文的用例。

一个用例 = 一次完整的业务动作。形态与 ``application/blog/use_cases.py`` 一致：

    ① 把命令里的裸值变成值对象（触发校验）
    ② 调领域实体做决策（``ensure_manageable_by`` / ``rename`` / ``mark_deleted``）
    ③ 调仓储把结果落库

**事务边界不在这一层**。用例只通过仓储 ``flush``，
真正的 ``commit`` 由 ``core/database.py::get_db`` 在请求结束时统一做。

所有用例都不 import FastAPI：授权（你这个身份有没有 tag:manage）归表现层守卫，
归属（这一个标签是不是你的）归领域实体，
用例只负责按正确顺序调用它们——这样它才能被非 HTTP 的入口复用。

⚠️ 两个「查重」出现在这里（而不是只在仓储里）：见 ``CreateTagUseCase``
   与 ``UpdateTagUseCase`` 的说明。一句话——
   用例里的查重是为了**给出好的错误信息**，仓储里的唯一约束才是**正确性保证**。
   两者都必须有，少任何一个都会出问题。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.application.tag.dto import (
    ChangeTagStatusCommand,
    CreateTagCommand,
    DeleteTagCommand,
    ListTagsQuery,
    TagDTO,
    TagPageDTO,
    UpdateTagCommand,
)
from app.domain.tag.entities import Tag, TagStatus, TagType
from app.domain.tag.exceptions import TagAlreadyExistsError, TagNotFoundError

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from app.domain.tag.repositories import TagRepository


async def _load(tags: TagRepository, tag_id: uuid.UUID) -> Tag:
    """按 id 取标签，取不到就抛 404。

    抽成公共函数而不是每个用例各写一遍：这三行里隐含一条规则——
    「软删除的标签在写路径上等同于不存在」。
    写一次，所有入口自动一致；分散写法迟早出现某个入口忘了判，
    于是「已删除的标签还能被改名」。

    ⚠️ 注意这里**只判 None、不判 status**：
        ``get_by_id`` 明确不过滤 status，因为「把删掉的标签恢复回来」
        要求能拿到已删除的实体。谁该拒绝已删除的标签，谁自己调
        ``ensure_not_deleted()``——目前只有 ``UpdateTagUseCase`` 需要。
    """
    tag = await tags.get_by_id(tag_id)
    if tag is None:
        raise TagNotFoundError()
    return tag


class ListTagsUseCase:
    """标签列表（公开，任何人都能调，包括未登录）。

    **没有归属过滤**，也不校验任何权限：
        标签是公共词汇表，它的价值恰恰在于「所有人都看得到有哪些标签可用」。
        要按作者筛就传 ``author_id``，那是筛选而不是权限。
    """

    def __init__(self, tags: TagRepository) -> None:
        self._tags = tags

    async def execute(self, query: ListTagsQuery) -> TagPageDTO:
        # 状态与类型都要显式校验：``?status=delteed`` 这种笔误若被当成「不筛选」，
        # 前端会收到整份列表而且看起来完全正常，问题要很久以后才暴露。
        # （与 ``ListMyPostsUseCase`` 对 ``PostStatus.parse`` 的处理同一套。）
        status = TagStatus.parse(query.status) if query.status else None
        tag_type = TagType.parse(query.tag_type) if query.tag_type else None

        # 筛选条件在两处必须逐字一致。这里的保证**不**靠"抄得仔细"，而是靠
        # ``SqlTagRepository._filtered_query``——list 与 count 共用同一段条件构造，
        # 所以这两次调用哪怕参数写错了，最多是「传错值」，不可能出现「条件集合不同」。
        # 后者才是分页 bug 的真正来源（「共 10 条」但翻到第 2 页是空白）。
        items = await self._tags.list_tags(
            status=status,
            type=tag_type,
            keyword=query.keyword,
            author_id=query.author_id,
            offset=query.offset,
            limit=query.limit,
        )
        total = await self._tags.count_tags(
            status=status,
            type=tag_type,
            keyword=query.keyword,
            author_id=query.author_id,
        )
        return TagPageDTO(
            items=tuple(TagDTO.from_entity(tag) for tag in items),
            total=total,
            offset=query.offset,
            limit=query.limit,
        )


class CreateTagUseCase:
    """新建标签（管理员）。

    为什么管理员要能单独建标签，而不是只能靠写文章时顺手创建：
        1. 平台可以预置一批 ``type=system`` 的标签（首页分类入口之类），
           它们不该依赖"先有人写一篇带这个标签的文章"；
        2. 作者想在自己动笔之前先把术语定下来（写个描述说明它该怎么用）。

    ``type=system`` 只能从这个入口产生：
        写文章的路径永远建 ``user`` 标签（见 ``repositories/post.py``），
        否则作者只要在文章里打上「首页推荐」，就能造出一个管理员才该拥有的东西。
    """

    def __init__(self, tags: TagRepository) -> None:
        self._tags = tags

    async def execute(self, command: CreateTagCommand) -> TagDTO:
        # Tag.create 里会跑 TagName 的校验（空 / 超长 / 非法字符）并派生出 slug。
        tag = Tag.create(
            name=command.name,
            author_id=command.actor_id,
            description=command.description,
            type=command.type,
        )

        # 先查一次重，是为了**给出清楚的中文错误**；
        # 真正的正确性保证是 ``ix_tags_name`` / ``ix_tags_slug`` 两个唯一索引
        # （见仓储里对 IntegrityError 的翻译）。
        #
        # ⚠️ 两次判断**都不能省**：
        #    ``exists_name`` 挡不住「不同名字归化出同一 slug」（``Node.js`` 与
        #    ``Node js`` 都是合法的标签名，却都会变成 ``node-js``），
        #    ``exists_slug`` 也挡不住「名字一样但 slug 不同」的历史脏数据。
        #    只管一个，另一个就会以 40950 的形式从 flush 里冒出来——
        #    错误码相同，但错误信息里没有名字，用户不知道该改什么。
        if await self._tags.exists_name(tag.name):
            raise TagAlreadyExistsError(f"标签「{tag.name}」已经存在")
        if await self._tags.exists_slug(tag.slug):
            raise TagAlreadyExistsError(
                f"标签「{tag.name}」归化后的网址 {tag.slug!r} 已被其他标签占用，请换一个名字"
            )

        return TagDTO.from_entity(await self._tags.add(tag))


class UpdateTagUseCase:
    """编辑标签的名字与描述（作者本人，或管理员）。

    ⚠️ 状态**不在**这里改，走 ``ChangeTagStatusUseCase``。
       原因见 ``application/tag/dto.py`` 顶部：两个动作的授权层级不同，
       混在一个 body 里会让「有的字段普通人能改、有的只有管理员能改」
       这条规则既写不进 schema、也容易在后续改动里被漏掉。
    """

    def __init__(self, tags: TagRepository) -> None:
        self._tags = tags

    async def execute(self, command: UpdateTagCommand) -> TagDTO:
        tag = await _load(self._tags, command.tag_id)
        tag.ensure_not_deleted()

        # 归属判定**排在字段解析之前**（与 ``UpdatePostUseCase`` 同一个顺序）：
        #   如果放在后面，一个越权请求仍会先跑完名字的校验，
        #   于是攻击者能通过「400 还是 403」的差异，探测出哪些名字是合法的——
        #   在不该有任何信息泄露的路径上泄露了信息。
        #
        # ⚠️ 这一行是「行级归属」，与路由上的 ``tag:manage`` 是两回事：
        #   路由回答「你这个身份能不能碰标签」，这里回答「这一个是不是你的」。
        #   少了这一行，任何登录用户都能改掉别人的标签。
        tag.ensure_manageable_by(
            command.actor_id, actor_can_manage_any=command.actor_can_manage_any
        )

        renamed = tag.rename(command.name)
        if renamed.name != tag.name:
            # 只有名字**真的变了**才查重：
            #   名字没变时 ``exists_name`` 一定查得到自己（它占着这个名字），
            #   不排除就会得到「把 Python 改成 Python → 409」这种莫名其妙的结果。
            #   用 ``exclude_id`` 排除自己也能解决，但那样每次改描述都要白跑两条 SQL。
            if await self._tags.exists_name(renamed.name, exclude_id=tag.id):
                raise TagAlreadyExistsError(f"标签「{renamed.name}」已经存在")
            if await self._tags.exists_slug(renamed.slug, exclude_id=tag.id):
                raise TagAlreadyExistsError(
                    f"标签「{renamed.name}」归化后的网址 {renamed.slug!r} 已被其他标签占用"
                )

        updated = renamed.change_description(command.description)
        return TagDTO.from_entity(await self._tags.update(updated))


class ChangeTagStatusUseCase:
    """变更标签状态（下架 / 恢复 / 软删除），只有管理员。

    授权是**路由**的责任（``tag:manage`` 挂在 ``PATCH /tags/{id}/status`` 上），
    所以这里不做归属判断：管理员对任何标签都有权，包括系统标签——
    一条被玩坏的内置标签也得有办法下架，否则错误只能靠改数据库修。

    刻意**不**调用 ``ensure_not_deleted()``：
        这个方法就是「把删掉的标签恢复回来」的唯一入口。
        加上那句检查，软删除会变成不可逆操作——而「误删了想撤销」
        是标签管理里排第一的真实需求。
    """

    def __init__(self, tags: TagRepository) -> None:
        self._tags = tags

    async def execute(self, command: ChangeTagStatusCommand) -> TagDTO:
        tag = await _load(self._tags, command.tag_id)
        # ``change_status`` 内部走 ``TagStatus.parse``：
        # 非法状态值在这里变成 40051，而不是被写进库、
        # 让所有读到这个标签的地方都开始出现"未知状态"的分支。
        updated = tag.change_status(command.status)
        return TagDTO.from_entity(await self._tags.update(updated))


class DeleteTagUseCase:
    """软删除标签，只有管理员。

    返回 ``None``：删除之后没有「剩余的表示」可回。
    与 ``DeletePostUseCase`` 一致——HTTP 层已经用 204 表达了同一件事，
    再在 body 里说一遍只会多一个需要保持同步的地方。

    幂等：对已经删除的标签再删一次直接返回成功，不报 404 也不报错。
        DELETE 是幂等动作，网络重试是常态；报错会让客户端不得不先查一次状态，
        而那一次查询同样可能失败。

    ⚠️ 为什么删除**不**像 ``UpdateTagUseCase`` 那样给作者留口子：
        改名/改描述只影响这个标签自己的展示，作者是在修正自己造成的问题；
        删除会让**所有**用过它的文章少一个标签——那是处置公共资源，
        不能由「碰巧第一个用了这个名字」的人决定。
        作者写错了名字，走编辑接口改掉即可。
    """

    def __init__(self, tags: TagRepository) -> None:
        self._tags = tags

    async def execute(self, command: DeleteTagCommand) -> None:
        tag = await _load(self._tags, command.tag_id)
        if tag.is_deleted:
            return
        await self._tags.update(tag.mark_deleted())


__all__ = [
    "ChangeTagStatusUseCase",
    "CreateTagUseCase",
    "DeleteTagUseCase",
    "ListTagsUseCase",
    "UpdateTagUseCase",
]
