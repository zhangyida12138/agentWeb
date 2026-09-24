import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import HomePage from './HomePage'

describe('HomePage', () => {
  it('渲染欢迎标题与技术栈说明', () => {
    render(<HomePage />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('欢迎使用 AgentWeb')
    expect(screen.getByText(/Vite \+ React \+ TypeScript/)).toBeInTheDocument()
  })
})
