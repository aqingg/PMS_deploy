import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from 'primereact/card'
import { Chip } from 'primereact/chip'
import { trackToolNavigation } from './analytics'
import { portalTools } from './tools'

export default function HomePage() {
  const navigate = useNavigate()
  const handleNavigate = (tool) => {
    trackToolNavigation(tool, 'home_card')
    navigate(tool.path)
  }

  return (
    <div className='home-page'>
      <section className='home-hero'>
        <Chip label='OnePager' icon='pi pi-bolt' className='home-hero-chip' />
        <h1>工具入口</h1>
        <p>
          请选择需要进入的工具项目。首页仅提供入口，不影响各工具内部路由。
        </p>
      </section>

      <section className='home-grid'>
        {portalTools.map((tool) => (
          <Card
            key={tool.key}
            className='tool-card'
            role='button'
            tabIndex={0}
            onClick={() => handleNavigate(tool)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleNavigate(tool)
              }
            }}
            title={
              <span className='tool-card-title'>
                <i className={tool.icon} />
                {tool.title}
              </span>
            }
            subTitle={tool.desc}
          />
        ))}
      </section>
    </div>
  )
}