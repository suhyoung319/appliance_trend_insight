import { useState } from 'react'
import styles from '../../styles/Navbar.module.css'

export default function Navbar() {
  const [mode, setMode] = useState('b2c')

  return (
    <nav className={styles.navbar}>
      <div className={styles.logo}>
        <div className={styles.logoIcon}>A</div>
        <span className={styles.logoText}>APPLENS</span>
      </div>

      <div className={styles.toggle}>
        {['b2c', 'b2b'].map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`${styles.toggleBtn} ${mode === m ? styles.toggleBtnActive : ''}`}
          >
            {m.toUpperCase()}
          </button>
        ))}
      </div>

      <button className={styles.ctaBtn}>시작하기 →</button>
    </nav>
  )
}
