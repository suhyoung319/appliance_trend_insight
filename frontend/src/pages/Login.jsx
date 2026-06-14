import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import styles from '../styles/Login.module.css'

export default function Login() {
  const navigate = useNavigate()
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [userType, setUserType] = useState('b2c')
  const [error, setError] = useState('')

  const rule = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*()_+\-={}[\]|:;"'<>,.?/]).+$/

  const MOCK_USERS = [
    {
      id: 'user123!',
      password: 'user123!',
      type: 'b2c',
    },
    {
      id: 'biz123!',
      password: 'biz123!',
      type: 'b2b',
    },
  ]

  const handleLogin = (e) => {
    e.preventDefault()

    if (!userId || !password) {
      setError('아이디와 비밀번호를 모두 입력해주세요.')
      return
    }

    if (!rule.test(userId) || !rule.test(password)) {
      setError('아이디와 비밀번호는 영문, 숫자, 특수기호를 각각 1개 이상 포함해야 합니다.')
      return
    }

    const user = MOCK_USERS.find(
      u =>
        u.id === userId &&
        u.password === password &&
        u.type === userType
    )

    if (!user) {
      setError('아이디, 비밀번호 또는 회원 유형이 일치하지 않습니다.')
      return
    }

    localStorage.setItem('isLogin', 'true')
    localStorage.setItem('userType', user.type)
    localStorage.setItem('userId', user.id)

    if (user.type === 'b2c') {
      navigate('/b2c')
    } else {
      navigate('/b2b')
    }
  }

  return (
    <section className={styles.page}>
      <div className={styles.blobOne} />
      <div className={styles.blobTwo} />

      <div className={styles.card}>
        <Link to="/" className={styles.logo}>
          <span className={styles.logoIcon}>A</span>
          <span>APPLENS</span>
        </Link>

        <p className={styles.eyebrow}>Welcome Back</p>
        <h1 className={styles.title}>로그인</h1>
        <p className={styles.desc}>가전 트렌드 분석 서비스를 시작해보세요.</p>

        <form onSubmit={handleLogin} className={styles.form}>
          <div className={styles.typeBox}>
            <button
              type="button"
              className={`${styles.typeBtn} ${userType === 'b2c' ? styles.active : ''}`}
              onClick={() => setUserType('b2c')}
            >
              일반 회원
            </button>
            <button
              type="button"
              className={`${styles.typeBtn} ${userType === 'b2b' ? styles.active : ''}`}
              onClick={() => setUserType('b2b')}
            >
              기업 회원
            </button>
          </div>

          <input
            className={styles.input}
            placeholder="아이디"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          />

          <input
            className={styles.input}
            type="password"
            placeholder="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && <p className={styles.error}>{error}</p>}

          <button className={styles.submitBtn}>로그인</button>
        </form>

        <p className={styles.bottomText}>
          아직 계정이 없나요? <Link to="/signup">회원가입</Link>
        </p>
      </div>
    </section>
  )
}