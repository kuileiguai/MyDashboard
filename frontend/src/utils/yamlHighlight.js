/**
 * 轻量 YAML 语法高亮（零依赖），面向 docker compose 文件的常见写法。
 * highlightYaml(text) 返回可直接 v-html 的 HTML 字符串（内容已转义）。
 *
 * 生成的 class：y-key / y-string / y-number / y-keyword / y-variable
 *              y-anchor / y-comment / y-punct / y-value
 */

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c])
const wrap = (cls, text) => (text ? `<span class="y-${cls}">${esc(text)}</span>` : '')

const VAR_RE = /(\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*)/g
const VAR_ONE_RE = /^\$\{[^}]*\}$|^\$[A-Za-z_][A-Za-z0-9_]*$/
const NUM_RE = /^[-+]?(\d+(\.\d*)?|\.\d+)$/
const BOOL_RE = /^(true|false|null|yes|no|on|off|~)$/i
const BLOCK_RE = /^[|>][-+]?\d*$/

/** 把行内文本按 ${VAR} / $VAR 拆开着色 */
function inline(text) {
  if (!text) return ''
  return text.split(VAR_RE).map(part => {
    if (!part) return ''
    return VAR_ONE_RE.test(part) ? wrap('variable', part) : wrap('value', part)
  }).join('')
}

/** 值部分：引号字符串 / 数字 / 布尔 / 块标识 / 锚点 / 含变量的普通标量 */
function scalar(text) {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text || '')
  if (!m) return esc(text)
  const [, lead, core, trail] = m
  if (!core) return esc(text)
  if (/^["']/.test(core)) return esc(lead) + wrap('string', core) + esc(trail)
  if (NUM_RE.test(core)) return esc(lead) + wrap('number', core) + esc(trail)
  if (BOOL_RE.test(core)) return esc(lead) + wrap('keyword', core) + esc(trail)
  if (BLOCK_RE.test(core)) return esc(lead) + wrap('punct', core) + esc(trail)
  if (/^[&*!]/.test(core)) return esc(lead) + wrap('anchor', core) + esc(trail)
  return esc(lead) + inline(core) + esc(trail)
}

/** 拆出行尾注释（忽略引号内的 #） */
function splitComment(line) {
  let quote = null
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (quote) {
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; continue }
    if (ch === '#' && (i === 0 || /\s/.test(line[i - 1]))) return [line.slice(0, i), line.slice(i)]
  }
  return [line, '']
}

function highlightLine(line) {
  const [code, comment] = splitComment(line)
  let rest = code
  let html = ''

  const indent = /^[ \t]*/.exec(rest)[0]
  if (indent) { html += esc(indent); rest = rest.slice(indent.length) }
  if (!rest) return html + wrap('comment', comment)

  if (/^(---|\.\.\.)$/.test(rest)) return html + wrap('punct', rest) + wrap('comment', comment)

  const dash = /^-(?=\s|$)/.exec(rest)
  if (dash) {
    html += wrap('punct', '-')
    rest = rest.slice(1)
    if (rest[0] === ' ') { html += ' '; rest = rest.slice(1) }
  }

  const key = /^("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s:#]+)(\s*:)(?=\s|$)/.exec(rest)
  if (key) {
    html += wrap('key', key[1]) + wrap('punct', key[2]) + scalar(rest.slice(key[0].length))
  } else {
    // 列表项里的 KEY=VALUE（compose 的 environment 常见写法）
    const eq = /^([A-Za-z_][A-Za-z0-9_.-]*)(=)(.*)$/.exec(rest)
    if (eq) html += wrap('key', eq[1]) + wrap('punct', '=') + scalar(eq[3])
    else html += scalar(rest)
  }
  return html + wrap('comment', comment)
}

export function highlightYaml(text) {
  return String(text ?? '').split('\n').map(highlightLine).join('\n')
}
