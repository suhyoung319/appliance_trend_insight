import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from '../styles/B2BDashboard.module.css';

import B2BDashboardMain from '../components/dashboard/b2b/B2BDashboardMain';
import B2BMarketForecast from '../components/dashboard/b2b/B2BMarketForecast';
import B2BMarketInsight from '../components/dashboard/b2b/B2BMarketInsight';
import B2BAIStrategyReport from '../components/dashboard/b2b/B2BAIStrategyReport';

export default function B2BDashboard() {
    const navigate = useNavigate();
    const [activeMenu, setActiveMenu] = useState('dashboard');

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
                        시장 전망
                    </button>

                    <button
                        className={activeMenu === 'insight' ? styles.active : ''}
                        onClick={() => setActiveMenu('insight')}
                    >
                        시장 인사이트
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
                {activeMenu === 'forecast' && <B2BMarketForecast />}
                {activeMenu === 'insight' && <B2BMarketInsight />}
                {activeMenu === 'report' && <B2BAIStrategyReport />}
            </main>
        </div>
    );
}
