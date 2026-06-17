import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/common/Navbar'
import { useAuth } from '../context/AuthContext'
import s from '../styles/B2BHome.module.css'

const FEATURES = [
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
    title: '시장 트렌드 분석',
    desc: '카테고리별 검색량·브랜드 점유율·연령대 관심도를 한 화면에서 파악',
    path: '/b2b/dashboard',
    cta: '대시보드 열기',
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
        <line x1="11" y1="8" x2="11" y2="14" />
        <line x1="8" y1="11" x2="14" y2="11" />
      </svg>
    ),
    title: '제품 심층 리포트',
    desc: '뉴스·리뷰·DataLab·유튜브를 통합해 개별 제품의 시장 포지션을 진단',
    path: '/products/냉장고',
    cta: '리포트 보기',
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="8" height="18" rx="2" />
        <rect x="14" y="3" width="8" height="18" rx="2" />
        <line x1="10" y1="8" x2="14" y2="8" />
        <line x1="10" y1="12" x2="14" y2="12" />
        <line x1="10" y1="16" x2="14" y2="16" />
      </svg>
    ),
    title: '경쟁 제품 비교',
    desc: '두 제품의 트렌드·리뷰·뉴스를 AI가 나란히 분석해 경쟁 우위를 파악',
    path: '/compare',
    cta: '비교 시작',
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
    title: '구매 타이밍 분석',
    desc: '90일 검색 관심도 추이로 시장 수요가 고점/저점인 시점을 사전에 포착',
    path: '/timing',
    cta: '타이밍 확인',
  },
]

const STATS = [
  { value: '4개', label: '데이터 소스' },
  { value: '10개', label: '가전 카테고리' },
  { value: '실시간', label: '데이터 업데이트' },
  { value: 'AI', label: 'Groq 분석 엔진' },
]

function AccessGate({ user, navigate }) {
  if (!user) {
    return (
      <div className={s.gate}>
        <div className={s.gateIcon}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>
        <p className={s.gateTitle}>B2B 전용 서비스입니다</p>
        <p className={s.gateDesc}>B2B 계정으로 로그인하면 모든 기능을 이용할 수 있어요</p>
        <div className={s.gateBtns}>
          <button className={s.gateBtnPrimary} onClick={() => navigate('/login')}>로그인</button>
          <button className={s.gateBtnSecondary} onClick={() => navigate('/signup')}>B2B 가입 신청</button>
        </div>
      </div>
    )
  }
  if (user.user_type !== 'b2b' && user.role !== 'admin') {
    return (
      <div className={s.gate}>
        <div className={s.gateIcon}>🏢</div>
        <p className={s.gateTitle}>B2B 계정이 필요합니다</p>
        <p className={s.gateDesc}>현재 계정은 B2C 계정입니다. B2B 서비스를 이용하려면 별도 가입이 필요해요</p>
        <button className={s.gateBtnPrimary} onClick={() => navigate('/signup')}>B2B 가입 신청</button>
      </div>
    )
  }
  if (user.status === 'pending') {
    return (
      <div className={s.gate}>
        <div className={s.gateIcon}>⏳</div>
        <p className={s.gateTitle}>승인 대기 중</p>
        <p className={s.gateDesc}>관리자 승인 후 모든 B2B 기능을 이용할 수 있어요. 보통 1~2 영업일이 소요됩니다</p>
      </div>
    )
  }
  return null
}

export default function B2BHome() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const isB2BActive = (user?.user_type === 'b2b' && user?.status === 'active') || user?.role === 'admin'

  return (
    <div className={s.page}>
      <Navbar />

      <div className={s.hero}>
        <div className={s.heroContent}>
          <span className={s.badge}>B2B PLATFORM</span>
          <h1 className={s.headline}>
            가전 시장 데이터로<br />
            <span className={s.headlineAccent}>비즈니스 인사이트</span>를 얻으세요
          </h1>
          <p className={s.heroDesc}>
            네이버 쇼핑·DataLab·리뷰·뉴스 4가지 소스를 통합 분석해<br />
            카테고리 트렌드, 경쟁 현황, 소비자 반응을 한눈에 파악합니다
          </p>
          {isB2BActive && (
            <div className={s.heroBtns}>
              <button className={s.btnPrimary} onClick={() => navigate('/b2b/dashboard')}>
                시장 분석 대시보드 →
              </button>
              <button className={s.btnSecondary} onClick={() => navigate('/trend')}>
                트렌드 현황 보기
              </button>
            </div>
          )}
        </div>
        <div className={s.heroBlob} />
      </div>

      <div className={s.container}>

        <div className={s.statsRow}>
          {STATS.map(st => (
            <div key={st.label} className={s.statItem}>
              <span className={s.statValue}>{st.value}</span>
              <span className={s.statLabel}>{st.label}</span>
            </div>
          ))}
        </div>

        {!isB2BActive && <AccessGate user={user} navigate={navigate} />}

        <div className={s.featureGrid}>
          {FEATURES.map(f => (
            <div
              key={f.title}
              className={`${s.featureCard} ${!isB2BActive ? s.featureCardLocked : ''}`}
              onClick={() => isB2BActive && navigate(f.path)}
            >
              <div className={s.featureIcon}>{f.icon}</div>
              <h3 className={s.featureTitle}>{f.title}</h3>
              <p className={s.featureDesc}>{f.desc}</p>
              {isB2BActive && (
                <span className={s.featureCta}>{f.cta} →</span>
              )}
              {!isB2BActive && <span className={s.featureLock}>🔒</span>}
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
