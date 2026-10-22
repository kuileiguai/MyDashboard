/** 复制文本；localhost/HTTPS 用 Clipboard API，HTTP 局域网访问回退到 execCommand。 */
export async function copyText(value) {
  const text = String(value ?? '')
  if (!text) return false

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch (_) {
      // 继续走 fallback
    }
  }

  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', 'readonly')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, ta.value.length)
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch (_) {
    return false
  }
}
