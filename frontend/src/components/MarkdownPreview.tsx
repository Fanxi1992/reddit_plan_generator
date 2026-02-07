import { isValidElement, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github.css'

type TocItem = {
  level: number
  text: string
  id: string
}

function createSlugger() {
  const seen = new Map<string, number>()
  return {
    slug(text: string) {
      const base = text
        .trim()
        .toLowerCase()
        .replace(/[^\w\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
      const current = seen.get(base) ?? 0
      seen.set(base, current + 1)
      return current === 0 ? base : `${base}-${current + 1}`
    },
  }
}

function extractToc(markdown: string): TocItem[] {
  const slugger = createSlugger()
  const lines = markdown.split(/\r?\n/g)
  const toc: TocItem[] = []

  for (const line of lines) {
    const m = /^(#{1,3})\s+(.+?)\s*$/.exec(line)
    if (!m) continue
    const level = m[1].length
    const text = m[2]
    const id = slugger.slug(text)
    toc.push({ level, text, id })
  }

  return toc
}

function toPlainText(children: unknown): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(toPlainText).join('')
  if (isValidElement<{ children?: unknown }>(children)) return toPlainText(children.props.children)
  return ''
}

type Props = {
  markdown: string
}

export default function MarkdownPreview({ markdown }: Props) {
  const toc = useMemo(() => extractToc(markdown), [markdown])
  const scrollerRef = useRef<HTMLDivElement | null>(null)

  // Re-create a fresh slugger on every render so heading ids stay deterministic.
  const slugger = createSlugger()

  function scrollTo(id: string) {
    const root = scrollerRef.current
    if (!root) return
    const el = root.querySelector<HTMLElement>(`#${CSS.escape(id)}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="preview">
      {toc.length > 0 ? (
        <aside className="preview__toc">
          <div className="preview__tocTitle">目录</div>
          <div className="preview__tocList">
            {toc.map((item) => (
              <button
                className={`tocItem tocItem--lvl${item.level}`}
                type="button"
                key={`${item.id}-${item.level}`}
                onClick={() => scrollTo(item.id)}
                title={item.text}
              >
                {item.text}
              </button>
            ))}
          </div>
        </aside>
      ) : null}

      <div className="preview__body" ref={scrollerRef}>
        <div className="md">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
              h1: ({ children, ...props }) => {
                const text = toPlainText(children)
                const id = slugger.slug(text)
                return (
                  <h1 id={id} {...props}>
                    {children}
                  </h1>
                )
              },
              h2: ({ children, ...props }) => {
                const text = toPlainText(children)
                const id = slugger.slug(text)
                return (
                  <h2 id={id} {...props}>
                    {children}
                  </h2>
                )
              },
              h3: ({ children, ...props }) => {
                const text = toPlainText(children)
                const id = slugger.slug(text)
                return (
                  <h3 id={id} {...props}>
                    {children}
                  </h3>
                )
              },
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
