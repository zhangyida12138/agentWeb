from fastapi import APIRouter

from app.presentation.api.v1.endpoints.auth import router as auth_router
from app.presentation.api.v1.endpoints.comments import comments_router
from app.presentation.api.v1.endpoints.comments import router as post_comments_router
from app.presentation.api.v1.endpoints.health import router as health_router
from app.presentation.api.v1.endpoints.likes import (
    posts_router as post_interaction_router,
)
from app.presentation.api.v1.endpoints.likes import router as likes_router
from app.presentation.api.v1.endpoints.posts import me_router as posts_me_router
from app.presentation.api.v1.endpoints.posts import router as posts_router
from app.presentation.api.v1.endpoints.roles import router as roles_router
from app.presentation.api.v1.endpoints.users import router as users_router

# v1 总路由：所有业务 endpoint 都在这里 include
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
# access 上下文：路径前缀已由各自 router 声明（/users、/roles），这里不再加二次前缀
api_router.include_router(users_router)
api_router.include_router(roles_router)
# blog 上下文：/posts（公开读 + 写作）与 /me/posts（仅本人，含草稿）。
# 两个 router 刻意分开，避免「当前用户的资源」和「按 slug 取文章」共用同一段路径模板。
api_router.include_router(posts_router)
api_router.include_router(posts_me_router)
# interaction 上下文：三个 router 各自表达一种资源归属——
#   /posts/{id}/comments  集合挂在文章下（父资源是文章）
#   /comments/{id}        单条评论的操作（父资源是已知的评论 id）
#   /likes/toggle         与目标无关的一个动作（目标是多态的）
#   /posts/{id}/interactions  文章的一个派生属性（赞数 / 评论数）
api_router.include_router(post_comments_router)
api_router.include_router(comments_router)
api_router.include_router(likes_router)
api_router.include_router(post_interaction_router)

__all__ = ["api_router"]
