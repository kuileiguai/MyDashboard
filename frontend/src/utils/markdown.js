import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import yaml from 'highlight.js/lib/languages/yaml'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import nginx from 'highlight.js/lib/languages/nginx'
import sql from 'highlight.js/lib/languages/sql'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import ini from 'highlight.js/lib/languages/ini'
import diff from 'highlight.js/lib/languages/diff'
import markdown from 'highlight.js/lib/languages/markdown'

for (const [name, lang] of Object.entries({
  javascript, typescript, bash, json, python, yaml,
  dockerfile, nginx, sql, xml, css, ini, diff, markdown,
})) {
  hljs.registerLanguage(name, lang)
}
hljs.registerAliases(['js', 'jsx'], { languageName: 'javascript' })
hljs.registerAliases(['ts', 'tsx'], { languageName: 'typescript' })
hljs.registerAliases(['sh', 'shell', 'zsh'], { languageName: 'bash' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerAliases(['html'], { languageName: 'xml' })

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function highlightCode(str, lang) {
  if (lang && hljs.getLanguage(lang)) {
    try {
      return hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
    } catch (_) {}
  }
  return escapeHtml(str)
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

// 每个 fenced code block 带一个复制按钮；AiMessage 用事件委托处理点击。
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const info = token.info ? md.utils.unescapeAll(token.info).trim() : ''
  const lang = info.split(/\s+/g)[0] || ''
  const code = token.content || ''
  const highlighted = highlightCode(code, lang)
  const langLabel = lang
    ? `<span class="ai-code-lang">${escapeHtml(lang)}</span>`
    : ''
  const codeClass = lang ? `language-${escapeHtml(lang)}` : ''
  return (
    '<div class="ai-code-block">' +
    langLabel +
    '<button type="button" class="ai-code-copy" aria-label="复制代码" title="复制代码">复制</button>' +
    `<pre class="hljs"><code class="${codeClass}">${highlighted}</code></pre>` +
    '</div>'
  )
}

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, idx, options)
}

export function renderMarkdown(text) {
  const raw = md.render(text || '')
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    ADD_TAGS: ['button'],
    ADD_ATTR: ['type', 'aria-label'],
  })
}
