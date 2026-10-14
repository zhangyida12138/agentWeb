import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Markdown 渲染。
 *
 * 为什么用 react-markdown 而不是 `marked` / `markdown-it` + `dangerouslySetInnerHTML`：
 *   ① 它把 Markdown 转成 **React 元素**，整个过程不产生 innerHTML，
 *      因此「正文里写 `<script>` 或 `<img onerror=...>`」这类注入在结构上就不可能成立，
 *      不需要再串一个 DOMPurify 进来（sanitizer 忘了配就是一次 XSS）；
 *   ② 它**默认不解析内联 HTML**，所以正文里的 `<div>` 会被原样显示成文字。
 *      对一个「多人写内容」的系统来说，这是比「支持 HTML」更划算的默认值。
 *
 * `remark-gfm` 补上 GitHub 风味：表格、删除线、任务列表、自动链接。
 * 不装数学公式、代码高亮那两套：本期没有需求，装了就是两份额外体积和两份升级负担；
 * 将来正文里真出现公式，再按需加 `remark-math` + `rehype-katex` 即可，接入点就在这里。
 *
 * 样式走 `.markdown-body` 类（在 index.css 里）而不是 `@unocss/preset-typography`：
 *   正文的排版规则是「一堆元素选择器」（h2 的上下边距、ul 的缩进、blockquote 的左边框……），
 *   用工具类表达意味着每渲染一个标签都要手工挑 class，而 Markdown 的标签集合是**内容决定的**、
 *   编译期根本不知道会出现哪些。一份 CSS 是这里唯一合适的形式。
 */
export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}
