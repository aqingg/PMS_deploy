import { useEffect } from 'react'
import { trackToolNavigation } from './analytics'

export default function ToolFrame({ toolPath, title, tool }) {
  const baseUrl = import.meta.env.BASE_URL || '/'
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
  const normalizedToolPath = (toolPath || '').replace(/^\//, '')
  const src = `${normalizedBase}${normalizedToolPath}/index.html`

  useEffect(() => {
    trackToolNavigation(tool, 'tool_route')
  }, [tool])

  return (
    <section className='tool-frame-container' aria-label={title}>
      <iframe
        title={title}
        src={src}
        className='tool-frame'
      />
    </section>
  )
}