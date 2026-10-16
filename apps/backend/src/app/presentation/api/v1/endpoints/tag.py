"""标签接口：公开词汇表 + 管理员维护。

权限设计（本文件是整个标签上下文里**唯一**决定授权的地方）：

    GET    /tags                 无需登录     标签是公共词汇表，看不到就没法用
    POST   /tags                 tag:manage   只有管理员能往词汇表里加新词
    PUT    /tags/{id}            仅需登录     作者可改自己的名字/描述，管理员可改任何
    PATCH  /tags/{id}/status     tag:manage   下架/恢复是审核动作
    DELETE /tags/{id}            tag:manage   删除会影响所有用过它的文章

三条看起来「不一致」但都是有意的规则：

① **写接口之间存在差异，因为它们的破坏半径不同。**
   改一个标签的名字只影响这个标签自己的展示；改它的状态或把它删掉，
   会让别人的文章少一个标签、或者从标签页上消失。
   破坏半径不一样的动作，就不该共用同一把钥匙。

② ``PUT`` 是「认证 + 行级归属」而不是「权限码」。
   权限系统是**基于角色**的，而这里的规则是「你能改你自己建的那些标签」——
   一个逐行的、没有任何角色能表达的规则。硬要表达它只能给每个标签建一个角色。
   所以这一条的守卫只负责认证，归属由 ``Tag.ensure_manageable_by`` 判。
   两个动作对应两个错误码：40320（没这个能力）与 40350（这不是你的东西），
   客户端据此知道该「去申请权限」还是「去找管理员」。

③ ``PUT`` 而不是 ``PATCH``（与本项目其他编辑接口相反）。
   标签只有 name / description 两个可编辑字段，而它俩在同一个表单里，
   提交时必然都在。用 PUT 的代价是「不传 = 清空」，
   而这里的客户端从不会漏传——于是省掉了整套 ``Unset`` 哨兵机制。
   这不是笔误，是「只有两个字段」这个事实带来的简化。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from agent_web_shared.pagination import DEFAULT_LIMIT, MAX_LIMIT, normalize_pagination
from app.application.tag.dto import (
    ChangeTagStatusCommand,
    CreateTagCommand,
    DeleteTagCommand,
    ListTagsQuery,
    UpdateTagCommand,
)
from app.application.tag.use_cases import (
    ChangeTagStatusUseCase,
    CreateTagUseCase,
    DeleteTagUseCase,
    ListTagsUseCase,
    UpdateTagUseCase,
)
from app.domain.access.entities import PermissionCode
from app.domain.tag.entities import TagStatus
from app.presentation.api.v1.schemas.tag import (
    ChangeTagStatusRequest,
    CreateTagRequest,
    TagPageResponse,
    TagResponse,
    UpdateTagRequest,
)
from app.presentation.dependencies import (
    CurrentUserId,
    PermissionCodes,
    get_change_tag_status_use_case,
    get_create_tag_use_case,
    get_delete_tag_use_case,
    get_list_tags_use_case,
    get_update_tag_use_case,
    require_permission,
)

router = APIRouter(prefix="/tags", tags=["tag"])


# ──────────────────────────── 公开读 ────────────────────────────


@router.get(
    "",
    response_model=TagPageResponse,
    summary="标签列表（公开，无需登录）",
)
async def list_tags(
    use_case: Annotated[ListTagsUseCase, Depends(get_list_tags_use_case)],
    # 与文章/用户列表同一套收敛口径：越界的 offset/limit 不报 422，直接收敛到合法区间，
    # 并把收敛后的值回填进响应，让客户端看出「我传的 1000 变成了 100」
    offset: Annotated[int, Query(description="偏移量，负数按 0 处理")] = 0,
    limit: Annotated[int, Query(description=f"每页条数，上限 {MAX_LIMIT}")] = DEFAULT_LIMIT,
    # 默认值放在这里、而不是放进用例或仓储：
    #   「不传 status 时只看正常标签」是一条 **API 契约**，不是业务规则。
    #   放在用例里，非 HTTP 的调用方（脚本、后台任务）会继承一个它看不到、
    #   也无从覆盖的隐藏默认值；放在参数上，契约就写在接口签名里。
    tag_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="按状态过滤：normal（默认）/ abnormal / deleted",
        ),
    ] = TagStatus.NORMAL,
    # Python 侧叫 tag_type 是为了和 FastAPI 的 Query 参数名分开，
    # 对外仍通过 alias 暴露成 ?type=，与 status 同一手法。
    tag_type: Annotated[
        str | None,
        Query(alias="type", description="按类型过滤：user / system；不传则两类都返回"),
    ] = None,
    keyword: Annotated[
        str | None,
        Query(description="按名称模糊搜索，忽略大小写；只含空白的值视为不筛选"),
    ] = None,
    author_id: Annotated[
        uuid.UUID | None,
        Query(description="只看某个作者创建的标签"),
    ] = None,
) -> TagPageResponse:
    """列出标签，按「被引用次数」倒序。

    默认只返回 ``normal`` 状态：
        一个列表接口的默认结果应当是「用户可以拿去用的东西」。
        把已下架、已删除的标签混进默认结果里，用户会以为它们还能用，
        然后在编辑器里打出来再发现不对——一个本可以不发生的失败。
        要审阅垃圾数据就显式传 ``?status=deleted``。

    排序按引用数而不是名称：
        标签列表的实际用法是「挑一个现成的用」，那么被用过 50 次的标签
        显然比从没用过的更值得放在第一屏。同引用数再按名称升序，
        否则 Postgres 对相同排序键不保证稳定顺序，翻页会出现重复/缺项。

    ``type`` 不过滤时两类都会返回（包括平台内置的 system 标签）：
        内置标签是给人用的入口，藏起来等于它不存在。
        但客户端能通过 ``type`` 认出来并给它加个「官方」标记。
    """
    safe_offset, safe_limit = normalize_pagination(offset, limit)
    page = await use_case.execute(
        ListTagsQuery(
            offset=safe_offset,
            limit=safe_limit,
            status=tag_status,
            tag_type=tag_type,
            keyword=keyword,
            author_id=author_id,
        )
    )
    return TagPageResponse.from_dto(page)


# ──────────────────────────── 写 ────────────────────────────


@router.post(
    "",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建标签（管理员）",
    dependencies=[Depends(require_permission(PermissionCode.TAG_MANAGE))],
)
async def create_tag(
    payload: CreateTagRequest,
    actor_id: CurrentUserId,
    use_case: Annotated[CreateTagUseCase, Depends(get_create_tag_use_case)],
) -> TagResponse:
    """管理员建立一个新标签。

    普通用户**也能**创建标签——但必须通过写文章时的自动创建
    （``post_tags`` 里没见过的新名字会落库，见 ``SqlPostRepository``）。
    两条路径都保留，是因为它们的语义不同：
        写文章时创建 = 「我顺手用了这个词」，作者自动成为它的 owner；
        这里创建    = 「我维护一份公共词汇表」，包括预置 ``type=system`` 的官方标签。

    返回 201 + 完整对象（而不是只回 id）：
        前端建完标签通常立刻要把它插进当前列表或下拉框，
        只回 id 的话还得再发一次 GET，而那次 GET 可能读到别的请求造成的中间态。

    ``author_id`` 从 token 推导，请求体里没有这个字段——
        让客户端指定归属等于允许以别人的名义建标签，
        而「谁该对这个标签负责」一旦可以伪造，归属校验就失去意义了。
    """
    tag = await use_case.execute(
        CreateTagCommand(
            name=payload.name,
            actor_id=actor_id,
            description=payload.description,
            type=payload.type,
        )
    )
    return TagResponse.model_validate(tag)


@router.put(
    "/{tag_id}",
    response_model=TagResponse,
    summary="编辑标签的名称与说明（作者本人，或管理员）",
)
async def update_tag(
    tag_id: uuid.UUID,
    payload: UpdateTagRequest,
    actor_id: CurrentUserId,
    codes: PermissionCodes,
    use_case: Annotated[UpdateTagUseCase, Depends(get_update_tag_use_case)],
) -> TagResponse:
    """更新标签的名称与说明。

    ⚠️ 这里**没有** ``require_permission`` 守卫，是刻意的：
        规则是「你能改你自己创建的标签」，而权限码是角色的属性，不是某一行的属性——
        没有任何权限码能表达「你自己建的」。硬套一个（比如要求 ``post:update``）
        会得到一个既拦不住越权（别人拿同样的权限照样调）又误伤正当用途的守卫。

        真正起作用的判断在用例里（``Tag.ensure_manageable_by``），
        它同时处理三种情况：系统标签（非管理员 40350）、别人的标签（40350）、
        以及无归属的存量标签（``author_id IS NULL``，对普通用户同样 40350——
        没有主人就不等于人人可改）。

    ``codes`` 只用来算 ``actor_can_manage_any``（是否持有 ``tag:manage``）：
        管理员需要能改任何标签，包括系统标签和离职同事留下的标签。
        这个钥匙**必须**来自服务端自己查到的权限集合，
        绝不能让客户端用一个字段自称管理员。

    为什么是 PUT 而不是 PATCH：本文件顶部 ③ 已说明。
    这里的实际好处是``name`` 一定存在，所以不存在「改名还是只改描述」的歧义，
    用例可以直接比较新旧名字来决定要不要查重。
    """
    tag = await use_case.execute(
        UpdateTagCommand(
            tag_id=tag_id,
            actor_id=actor_id,
            actor_can_manage_any=PermissionCode.TAG_MANAGE in codes,
            name=payload.name,
            description=payload.description,
        )
    )
    return TagResponse.model_validate(tag)


@router.patch(
    "/{tag_id}/status",
    response_model=TagResponse,
    summary="变更标签状态（管理员）",
    dependencies=[Depends(require_permission(PermissionCode.TAG_MANAGE))],
)
async def change_tag_status(
    tag_id: uuid.UUID,
    payload: ChangeTagStatusRequest,
    use_case: Annotated[ChangeTagStatusUseCase, Depends(get_change_tag_status_use_case)],
) -> TagResponse:
    """下架 / 恢复一个标签。

    状态用**动作子资源**（``/status``）表达，而不是塞进 ``PUT /tags/{id}`` 的 body：
        两者的授权层级不同（自己 vs 管理员）。混在一个请求里，
        就会出现「同一个 body 里有的字段普通人能改、有的只有管理员能改」——
        这条规则既写不进 schema（Pydantic 无法表达字段级权限），
        也无法靠路由装饰器一刀切，只能靠用例里的 if，最容易在后续改动里被漏掉。
        拆成两条路由，权限边界就是两行 ``dependencies``，一眼可查。

    返回更新后的对象而不只是 204：
        下架/恢复是列表页上的开关，前端要立刻把那一行渲染成新状态。
        回 204 的话前端只能乐观更新或再查一次，两种都比直接拿返回值差。

    为什么 ``deleted`` 也能从这条路由设置：
        它是「恢复」的逆操作，也是误删的补救手段——
        状态机是 ``normal ↔ abnormal ↔ deleted`` 全连通的，没有单向边。
    """
    tag = await use_case.execute(ChangeTagStatusCommand(tag_id=tag_id, status=payload.status))
    return TagResponse.model_validate(tag)


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除标签（软删除，管理员）",
    dependencies=[Depends(require_permission(PermissionCode.TAG_MANAGE))],
)
async def delete_tag(
    tag_id: uuid.UUID,
    use_case: Annotated[DeleteTagUseCase, Depends(get_delete_tag_use_case)],
) -> None:
    """把标签置为已删除。

    回 204 而不是 200 + 空对象：删除之后没有「剩余的表示」可回，
    再包一层 ``{"ok": true}`` 只是多一个需要和后端保持同步的字段。

    软删除（写 ``status='deleted'``）而不是 ``DELETE FROM tags``：
        ``post_tags`` 对它是有外键的，物理删除要么被约束挡住，
        要么连带删掉关联却必须自己负责清理顺序；而且误删无法恢复。
        软删除之后名字与 slug **仍然被占用**（唯一索引不认 status），
        所以「删了再建一个同名的」会拿到 40950 而不是悄悄复活一个旧 id——
        对已经引用过它的文章来说，这是更安全的行为。

    删除后已发布文章上的该标签也不再展示（查询会过滤 ``deleted``），
    但文章本身不受影响：软删除只作用于标签自己这一行。
    """
    await use_case.execute(DeleteTagCommand(tag_id=tag_id))


__all__ = ["router"]
