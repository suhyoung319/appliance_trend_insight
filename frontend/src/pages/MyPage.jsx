import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from '../styles/MyPage.module.css'

export default function MyPage() {
  const navigate = useNavigate()
  const userType = localStorage.getItem('userType')
  const userId = localStorage.getItem('userId') || 'user123!'

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState('')

  const isBusiness = userType === 'b2b'

  const handlePasswordChange = (e) => {
    e.preventDefault()

    if (!currentPassword || !newPassword || !confirmPassword) {
      setMessage('비밀번호 정보를 모두 입력해주세요.')
      return
    }

    if (newPassword !== confirmPassword) {
      setMessage('새 비밀번호가 일치하지 않습니다.')
      return
    }

    setMessage('비밀번호가 변경되었습니다.')
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
  }

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div className={styles.logo} onClick={() => navigate('/')}>
          <span className={styles.logoIcon}>A</span>
          <span>APPLENS</span>
        </div>

        <button className={styles.homeBtn} onClick={() => navigate('/')}>
          홈으로
        </button>
      </div>

      <main className={styles.container}>
        <div className={styles.titleBox}>
          <span>MY PAGE</span>
          <h1>마이페이지</h1>
          <p>회원 정보와 서비스 이용 상태를 확인할 수 있습니다.</p>
        </div>

        <div className={styles.grid}>
          <section className={styles.card}>
            <h2>내 정보</h2>

            <div className={styles.infoList}>
              <div>
                <span>아이디</span>
                <strong>{userId}</strong>
              </div>

              <div>
                <span>회원 유형</span>
                <strong>{isBusiness ? '기업 회원' : '일반 회원'}</strong>
              </div>

              <div>
                <span>이용 서비스</span>
                <strong>{isBusiness ? 'B2B 시장 분석 대시보드' : 'B2C 소비자 대시보드'}</strong>
              </div>
            </div>
          </section>

          <section className={styles.card}>
            <h2>비밀번호 변경</h2>

            <form className={styles.form} onSubmit={handlePasswordChange}>
              <input
                type="password"
                placeholder="현재 비밀번호"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />

              <input
                type="password"
                placeholder="새 비밀번호"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />

              <input
                type="password"
                placeholder="새 비밀번호 확인"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />

              {message && <p className={styles.message}>{message}</p>}

              <button>비밀번호 수정</button>
            </form>
          </section>
        </div>

        {isBusiness && (
          <section className={styles.subscription}>
            <div className={styles.subscriptionTop}>
              <div>
                <span>SUBSCRIPTION</span>
                <h2>기업 구독 정보</h2>
                <p>기업 회원은 월 구독료 결제를 통해 B2B 분석 리포트를 이용할 수 있습니다.</p>
              </div>

              <div className={styles.planBadge}>
                Business Plan
              </div>
            </div>

            <div className={styles.subscriptionGrid}>
              <div>
                <span>현재 플랜</span>
                <strong>Business Insight Plan</strong>
              </div>

              <div>
                <span>월 구독료</span>
                <strong>49,000원</strong>
              </div>

              <div>
                <span>결제 수단</span>
                <strong>등록된 카드 없음</strong>
              </div>

              <div>
                <span>다음 결제일</span>
                <strong>2026.07.14</strong>
              </div>
            </div>

            <div className={styles.paymentBox}>
              <div>
                <h3>결제 카드 등록</h3>
                <p>실제 결제 기능은 추후 PG사 연동 시 연결할 수 있습니다.</p>
              </div>

              <button>카드 등록/변경</button>
            </div>
          </section>
        )}
      </main>
    </section>
  )
}