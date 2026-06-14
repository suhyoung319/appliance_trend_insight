import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import styles from '../styles/Signup.module.css'

export default function SignUp() {
  const navigate = useNavigate()
  const [userType, setUserType] = useState('b2c')
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [passwordCheck, setPasswordCheck] = useState('')
  const [error, setError] = useState('')

  const rule = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*()_+\-={}[\]|:;"'<>,.?/]).+$/

  const handleSignup = (e) => {
    e.preventDefault()

    if (!userId || !password || !passwordCheck) {
      setError('모든 항목을 입력해주세요.')
      return
    }

    if (!rule.test(userId) || !rule.test(password)) {
      setError('아이디와 비밀번호는 영문, 숫자, 특수기호를 각각 1개 이상 포함해야 합니다.')
      return
    }

    if (password !== passwordCheck) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }

    localStorage.setItem('userType', userType)
    navigate('/login')
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

        <p className={styles.eyebrow}>Create Account</p>
        <h1 className={styles.title}>회원가입</h1>
        <p className={styles.desc}>회원 유형에 맞는 분석 화면을 제공합니다.</p>

        <form onSubmit={handleSignup} className={styles.form}>
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

          <input
            className={styles.input}
            type="password"
            placeholder="비밀번호 확인"
            value={passwordCheck}
            onChange={(e) => setPasswordCheck(e.target.value)}
          />

          {error && <p className={styles.error}>{error}</p>}

          <button className={styles.submitBtn}>회원가입</button>
        </form>

        <p className={styles.bottomText}>
          이미 계정이 있나요? <Link to="/login">로그인</Link>
        </p>
      </div>
    </section>
  )
}