import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: '首页', end: true },
  { to: '/users', label: '用户', end: false },
]

export default function AppLayout() {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <nav className="mx-auto flex max-w-4xl items-center gap-6 px-6 py-4">
          <span className="text-lg font-bold text-brand">AgentWeb</span>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? 'font-medium text-brand' : 'text-gray-600 hover:text-gray-900'
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
