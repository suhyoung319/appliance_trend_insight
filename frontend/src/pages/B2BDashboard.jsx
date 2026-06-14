import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from '../styles/B2BDashboard.module.css'

import B2BDashboardMain from '../components/dashboard/b2b/B2BDashboardMain'
import B2BTrendForecast from '../components/dashboard/b2b/B2BTrendForecast'
import B2BCompetitorAnalysis from '../components/dashboard/b2b/B2BCompetitorAnalysis'
import B2BConsumerNeeds from '../components/dashboard/b2b/B2BConsumerNeeds'
import B2BNewsIssue from '../components/dashboard/b2b/B2BNewsIssue'
import B2BAIStrategyReport from '../components/dashboard/b2b/B2BAIStrategyReport'

export default function B2BDashboard() {
  const navigate = useNavigate()
  const [activeMenu, setActiveMenu] = useState('dashboard')

  return (
    <div className={styles.page}>
      <aside className={styles.sidebar}>
        <div className={styles.logo} onClick={() => navigate('/')}>
          <span className={styles.logoIcon}>A</span>
          <span>APPLENS</span>
        </div>

        <nav className={styles.menu}>
          <button
            className={activeMenu === 'dashboard' ? styles.active : ''}
            onClick={() => setActiveMenu('dashboard')}
          >
            시장 대시보드
          </button>

          <button
            className={activeMenu === 'forecast' ? styles.active : ''}
            onClick={() => setActiveMenu('forecast')}
          >
            트렌드 예측
          </button>

          <button
            className={activeMenu === 'competitor' ? styles.active : ''}
            onClick={() => setActiveMenu('competitor')}
          >
            경쟁사 분석
          </button>

          <button
            className={activeMenu === 'consumer' ? styles.active : ''}
            onClick={() => setActiveMenu('consumer')}
          >
            소비자 니즈
          </button>

          <button
            className={activeMenu === 'news' ? styles.active : ''}
            onClick={() => setActiveMenu('news')}
          >
            뉴스 이슈
          </button>

          <button
            className={activeMenu === 'report' ? styles.active : ''}
            onClick={() => setActiveMenu('report')}
          >
            AI 전략 리포트
          </button>
        </nav>
      </aside>

      <main className={styles.main}>
        {activeMenu === 'dashboard' && <B2BDashboardMain />}
        {activeMenu === 'forecast' && <B2BTrendForecast />}
        {activeMenu === 'competitor' && <B2BCompetitorAnalysis />}
        {activeMenu === 'consumer' && <B2BConsumerNeeds />}
        {activeMenu === 'news' && <B2BNewsIssue />}
        {activeMenu === 'report' && <B2BAIStrategyReport />}
      </main>
    </div>
  )
}