import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'

import '@unocss/reset/tailwind.css'
import 'virtual:uno.css'
import './index.css'

import { queryClient } from './lib/query-client'
import { router } from './router'

const container = document.getElementById('root')
if (!container) throw new Error('#root 容器不存在，检查 index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
