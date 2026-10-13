import { useEffect, useId } from 'react'
import type { ReactNode } from 'react'

/**
 * 轻量弹窗。
 *
 * 为什么自己写而不用库（Radix / headlessui）：
 *   目前只用到「一个标题 + 一段内容 + 关闭」这一种形态，
 *   为它引入一个依赖 + 一套主题定制不划算。真正需要复杂交互
 *   （下拉、焦点循环、动画）时再换，替换点只有这一个文件。
 *
 * 但有三件事**不能**因为「轻量」而省掉，它们是弹窗可用性的底线：
 *   ① `role="dialog"` + `aria-modal="true"`：屏幕阅读器才知道
 *      「现在进入了一个模态区域」，否则它会继续读后面的表格内容；
 *   ② Escape 关闭：键盘用户唯一的退出方式（鼠标点击遮罩对键盘不可达）；
 *   ③ 遮罩点击关闭：这是用户最自然的「我不小心点进来了」的退出动作。
 *
 * 刻意**没有**实现完整的焦点陷阱（focus trap）：
 *   它需要遍历可聚焦元素、拦截 Tab、记住进入前的焦点，代码量比这个组件本身还大。
 *   作为折中，`autoFocus` 交给调用方在第一个输入框上设置，
 *   让「打开就能直接输入」这件最常发生的事先顺起来。
 */

interface ModalProps {
  title: string
  /** 描述性副标题，会作为 `aria-describedby` 的目标 */
  description?: string
  onClose: () => void
  children: ReactNode
}

export function Modal({ title, description, onClose, children }: ModalProps) {
  // useId 而不是写死 "modal-title"：同一页面上可能同时存在两个弹窗
  //（比如将来把「编辑角色」套在「重置密码」之上），写死 id 会造出重复节点，
  // aria-labelledby 就会指向错误的那一个
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    // 卸载时必须摘掉监听：本组件会随弹窗开关反复挂载，
    // 漏掉清理就会累积出一堆监听器，一次 Escape 触发多次 onClose
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/*
        遮罩单独一层、`aria-hidden`：它只是视觉上的「变暗 + 点击关闭」，
        对辅助技术而言没有任何语义，读出来只会变成噪音。
      */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
        data-testid="modal-overlay"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-gray-900">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="mt-1 text-xs text-gray-500">
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="-mt-1 text-lg leading-none text-gray-400 transition-colors hover:text-gray-700"
          >
            ✕
          </button>
        </div>

        {children}
      </div>
    </div>
  )
}
