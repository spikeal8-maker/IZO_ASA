import { useState, type ReactNode } from 'react'
import { Check, Copy } from 'lucide-react'

import './chatCore.css'

function safeUrl(value: string): string | null {
  const url = value.trim()
  if (url.startsWith('/api/')) return url
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

function Inline({ value }: { value: string }) {
  const token = /(!\[[^\]]*\]\([^\s)]+\)|\[[^\]]+\]\([^\s)]+\)|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|\`[^\`\n]+\`)/g
  const parts = value.split(token).filter(Boolean)
  return (
    <>
      {parts.map((part, index) => {
        const image = part.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
        if (image) {
          const src = safeUrl(image[2])
          return src ? <img className="portable-chat-inline-image" src={src} alt={image[1]} key={index} /> : <span key={index}>{image[1]}</span>
        }
        const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
        if (link) {
          const href = safeUrl(link[2])
          return href ? <a href={href} target="_blank" rel="noreferrer noopener" key={index}>{link[1]}</a> : <span key={index}>{link[1]}</span>
        }
        if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) return <strong key={index}>{part.slice(2, -2)}</strong>
        if ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_'))) return <em key={index}>{part.slice(1, -1)}</em>
        if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
        return <span key={index}>{part}</span>
      })}
    </>
  )
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return (
    <section className="portable-chat-code">
      <header>
        <span>{language || 'code'}</span>
        <button type="button" onClick={() => void copy()}>{copied ? <Check /> : <Copy />}{copied ? 'Скопировано' : 'Copy'}</button>
      </header>
      <pre><code>{code}</code></pre>
    </section>
  )
}

function TextBlocks({ value }: { value: string }) {
  const blocks = value.split(/\n{2,}/).filter((block) => block.trim())
  return (
    <>
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n')
        const unordered = lines.every((line) => /^\s*[-*]\s+/.test(line))
        const ordered = lines.every((line) => /^\s*\d+[.)]\s+/.test(line))
        if (unordered) return <ul key={blockIndex}>{lines.map((line, index) => <li key={index}><Inline value={line.replace(/^\s*[-*]\s+/, '')} /></li>)}</ul>
        if (ordered) return <ol key={blockIndex}>{lines.map((line, index) => <li key={index}><Inline value={line.replace(/^\s*\d+[.)]\s+/, '')} /></li>)}</ol>
        return (
          <p key={blockIndex}>
            {lines.map((line, index) => (
              <span key={index}><Inline value={line} />{index < lines.length - 1 && <br />}</span>
            ))}
          </p>
        )
      })}
    </>
  )
}

export function MessageRenderer({ value }: { value: string }) {
  const normalized = value.replace(/\r/g, '')
  const parts: ReactNode[] = []
  const fence = /```([^\n`]*)\n?([\s\S]*?)```/g
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = fence.exec(normalized))) {
    if (match.index > cursor) parts.push(<TextBlocks value={normalized.slice(cursor, match.index)} key={`text-${cursor}`} />)
    parts.push(<CodeBlock language={match[1].trim()} code={match[2].replace(/\n$/, '')} key={`code-${match.index}`} />)
    cursor = match.index + match[0].length
  }
  if (cursor < normalized.length) parts.push(<TextBlocks value={normalized.slice(cursor)} key={`text-${cursor}`} />)
  return <div className="portable-chat-rich-text">{parts}</div>
}
