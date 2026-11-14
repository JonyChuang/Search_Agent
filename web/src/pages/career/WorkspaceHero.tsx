import type { ReactNode } from 'react'
import styles from './workspace.module.css'

export default function WorkspaceHero({ section, title, description, actions }: {
  section: ReactNode; title: string; description: string; actions: ReactNode
}) {
  return (
    <header className={styles.hero}>
      <div className={styles.heroMain}>
        <small>{section}</small>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className={styles.heroPanel}>{actions}</div>
    </header>
  )
}
