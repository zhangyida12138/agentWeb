import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../stores/auth'

/**
 * 登录守卫：未登录时重定向到登录页。
 *
 * 判断依据是本地有没有 token，**不做**「token 是否已被服务端吊销」的校验——
 * 那需要一次网络往返，且每个路由都要等它。做法改为：
 * 先放行，让页面自己的请求去撞 401，api 层清掉登录态后这里会自动重定向。
 * 结果是「过期用户最多看到一次失败提示」，代价远小于每次进入都阻塞一次。
 *
 * 原目标路径放进 location.state.from，登录成功后回到用户原本想去的地方。
 */
export function RequireAuth() {
  const { token } = useAuth()
  const location = useLocation()

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  return <Outlet />
}
