"""博客上下文（blog）。

继 identity（用户）、access（角色权限）之后的第三个限界上下文，
承载「文章」这一核心资源：起草 → 发布 → 归档 → 软删除的生命周期，
以及「谁能改这篇文章」的行级归属规则。

与其他上下文的关系（单向）：
    blog ──依赖──> identity（要知道作者是谁，``Post.author_id``）
    blog 不依赖 access：它只认「权限码字符串」这一份契约，
    至于「谁拥有 post:update_any」是 access 的编排结果，由表现层注入。

层内结构与其他上下文完全一致：``entities`` / ``value_objects`` /
``repositories`` / ``exceptions``，依赖方向严格由外向内。
"""
