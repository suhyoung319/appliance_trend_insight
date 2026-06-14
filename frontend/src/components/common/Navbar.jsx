import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from '../../styles/Navbar.module.css'

export default function Navbar({ mode, setMode }) {
  const navigate = useNavigate()
  const [isLogin, setIsLogin] = useState(localStorage.getItem('isLogin') === 'true')
  const userType = localStorage.getItem('userType')

  const handleLogout = () => {
    localStorage.removeItem('isLogin')
    localStorage.removeItem('userType')
    localStorage.removeItem('userId')
    setIsLogin(false)
    navigate('/')
  }

  const handleMyDashboard = () => {
    if (userType === 'b2b') {
      navigate('/b2b')
    } else {
      navigate('/b2c')
    }
  }

  return (
    <nav className={styles.navbar}>
      <div className={styles.logo} onClick={() => navigate('/')}>
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

      {isLogin ? (
        <div className={styles.userBtns}>
          <button
            className={styles.dashboardBtn}
            onClick={handleMyDashboard}
          >
            대시보드
          </button>

          <button
            className={styles.myPageBtn}
            onClick={() => navigate('/mypage')}
          >
            마이페이지
          </button>

          <button
            className={styles.logoutBtn}
            onClick={handleLogout}
          >
            로그아웃
          </button>
        </div>
      ) : (
        <button
          className={styles.ctaBtn}
          onClick={() => navigate('/login')}
        >
          로그인
        </button>
      )}
    </nav>
  )
}