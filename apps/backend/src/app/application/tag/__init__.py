"""标签上下文的应用层。

形态与 ``application/blog`` 完全一致：用例只做**编排**与**事务内的顺序**，
不 import FastAPI。表现层把请求翻成 ``*Command`` / ``*Query``，
再把返回的 ``*DTO`` 翻成响应。

标签这一层有两处和博客不一样，都是被业务本身逼出来的：

**① 用例分成两组：读全是公开的，写全是管理动作。**

    ``ListTagsUseCase``        任何人可调（包括未登录）。
    ``CreateTagUseCase`` 等   需要 ``tag:manage``，且**只有管理员**持有这个权限码。

    读公开写受限，正是「标签是公共词汇表」这个定位的体现：
    大家都需要看到有哪些标签可用，但不该人人都有权改动公共词汇表——
    否则一个人可以把「Python」改成别的东西，全站文章看起来都会错位。

**② 归属判定要跟「越权钥匙」一起用。**

    ``ListTagsUseCase`` 不需要调用者身份；
    写用例需要传 ``actor_can_manage_any``，它由表现层查权限后传进来
    （理由与 ``UpdatePostCommand.actor_can_override`` 相同：
    用例不该直接依赖另一个上下文的仓储）。

    例外是 ``UpdateTagUseCase`` / ``DeleteTagUseCase``：
    它们**同时**需要调用者 id 和这把钥匙——
    标签是可以属于某个作者的，所以「有权限」不等于「能改这一个」，
    这两层判断缺一不可，顺序也不能颠倒（见 ``Tag.ensure_manageable_by``）。
"""
