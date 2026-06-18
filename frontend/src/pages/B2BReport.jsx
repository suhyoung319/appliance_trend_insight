import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/common/Navbar'
import { useAuth } from '../context/AuthContext'
import s from '../styles/B2BReport.module.css'
import { API_BASE } from '../config'

const CATEGORIES = ['에어컨', '냉장고', '세탁기', '건조기', '공기청정기', '로봇청소기', '식기세척기', 'TV']
const PERIODS = [
  { label: '1개월', value: '1m' },
  { label: '3개월', value: '3m' },
  { label: '6개월', value: '6m' },
  { label: '1년',   value: '1y' },
]
const BRAND_COLORS = ['#6366f1', '#a855f7', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b']

const ACTION_CONFIG = {
  '매입 확대':  { color: '#10b981', bg: 'rgba(16,185,129,0.1)',  border: 'rgba(16,185,129,0.3)',  icon: '↑' },
  '매입 유지':  { color: '#6366f1', bg: 'rgba(99,102,241,0.1)',  border: 'rgba(99,102,241,0.3)',  icon: '→' },
  '재고 축소':  { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)',  border: 'rgba(245,158,11,0.3)',  icon: '↓' },
  '관망':       { color: '#94a3b8', bg: 'rgba(148,163,184,0.08)', border: 'rgba(148,163,184,0.2)', icon: '◎' },
}

function AccessDenied({ user, navigate }) {
  return (
    <div className={s.page}>
      <Navbar />
      <div className={s.denied}>
        <p className={s.deniedTitle}>
          {!user ? '로그인이 필요합니다' : user.user_type !== 'b2b' ? 'B2B 계정 전용입니다' : '승인 대기 중입니다'}
        </p>
        <p className={s.deniedDesc}>
          {!user ? 'B2B 계정으로 로그인해주세요' : user.user_type !== 'b2b' ? 'B2B 가입 후 이용할 수 있어요' : '관리자 승인 후 사용 가능합니다'}
        </p>
        <button className={s.deniedBtn} onClick={() => navigate(!user ? '/login' : '/b2b')}>
          {!user ? '로그인' : 'B2B 홈으로'}
        </button>
      </div>
    </div>
  )
}

function DonutMini({ brands }) {
  if (!brands || brands.length === 0) return null
  const R = 40, cx = 48, cy = 48, stroke = 14
  let cum = 0
  const slices = brands.map((b, i) => {
    const start = cum; cum += b.pct
    return { ...b, start, color: BRAND_COLORS[i % BRAND_COLORS.length] }
  })
  function arc(sp, pct) {
    const a1 = (sp / 100) * 2 * Math.PI - Math.PI / 2
    const a2 = ((sp + pct) / 100) * 2 * Math.PI - Math.PI / 2
    const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1)
    const x2 = cx + R * Math.cos(a2), y2 = cy + R * Math.sin(a2)
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${pct > 50 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
  }
  return (
    <div className={s.donutRow}>
      <svg width={96} height={96}>
        {slices.map((sl, i) => (
          <path key={i} d={arc(sl.start, sl.pct)}
            fill="none" stroke={sl.color} strokeWidth={stroke} strokeLinecap="butt" />
        ))}
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize="10" fontWeight="700" fill="var(--text)">
          {slices[0]?.brand?.slice(0, 4) ?? ''}
        </text>
      </svg>
      <div className={s.donutLegend}>
        {slices.map((sl, i) => (
          <div key={i} className={s.donutLegendItem}>
            <span className={s.donutDot} style={{ background: sl.color }} />
            <span className={s.donutBrand}>{sl.brand}</span>
            <span className={s.donutPct}>{sl.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function B2BReport() {
  const navigate = useNavigate()
  const { user, token } = useAuth()
  const [category, setCategory] = useState('에어컨')
  const [period, setPeriod]     = useState('3m')
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const isB2BActive = (user?.user_type === 'b2b' && user?.status === 'active') || user?.role === 'admin'

  useEffect(() => {
    if (!isB2BActive) return
    setLoading(true)
    setError(null)
    setData(null)
    fetch(`${API_BASE}/api/b2b/ai-report?category=${encodeURIComponent(category)}&period=${period}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setError('서버에 연결할 수 없습니다'); setLoading(false) })
  }, [category, period, isB2BActive])

  if (!isB2BActive) return <AccessDenied user={user} navigate={navigate} />

  const report   = data?.report
  const metrics  = data?.metrics
  const brands   = data?.brands ?? []
  const action   = report?.action ?? '관망'
  const acfg     = ACTION_CONFIG[action] ?? ACTION_CONFIG['관망']
  const periodLabel = PERIODS.find(p => p.value === period)?.label ?? period

  return (
    <div className={s.page}>
      <Navbar />
      <div className={s.layout}>

        {/* ── Main ── */}
        <div className={s.main}>
          <div className={s.header}>
            <span className={s.badge}>AI 시장 리포트</span>
            <h1 className={s.title}>{category} 의사결정 인사이트</h1>
            <p className={s.subtitle}>RAG 강화 AI가 도출한 B2B 전략 추천 · {periodLabel} 기준</p>
          </div>

          {loading && (
            <div className={s.loadingWrap}>
              <div className={s.spinner} />
              <p>"{category}" 시장 AI 분석 중...</p>
            </div>
          )}
          {error && <div className={s.error}>{error}</div>}

          {!loading && data && report && (
            <>
              {/* ── Action Banner ── */}
              <div className={s.actionBanner} style={{ '--ac': acfg.color, '--ab': acfg.bg, '--abr': acfg.border }}>
                <div className={s.actionLeft}>
                  <p className={s.actionLabel}>AI 의사결정 추천</p>
                  <div className={s.actionMain}>
                    <span className={s.actionIcon}>{acfg.icon}</span>
                    <span className={s.actionText}>{action}</span>
                  </div>
                  <p className={s.actionReason}>{report.action_reason}</p>
                </div>
                <div className={s.actionRight}>
                  <div className={s.actionMeta}>
                    <span className={s.actionMetaLabel}>판매 최적 시점</span>
                    <span className={s.actionMetaValue}>{report.timing}</span>
                  </div>
                  <div className={s.actionDivider} />
                  <div className={s.actionMeta}>
                    <span className={s.actionMetaLabel}>재고 전략</span>
                    <span className={s.actionMetaValue}>{report.inventory_advice}</span>
                  </div>
                  <div className={s.actionDivider} />
                  <div className={s.actionMeta}>
                    <span className={s.actionMetaLabel}>시장 위험도</span>
                    <span className={s.actionMetaValue} style={{
                      color: metrics?.risk === '낮음' ? '#10b981' : metrics?.risk === '중간' ? '#f59e0b' : '#ef4444'
                    }}>
                      {metrics?.risk ?? '-'}
                    </span>
                  </div>
                </div>
              </div>

              {/* ── Metrics row ── */}
              <div className={s.metricsRow}>
                <div className={s.metricCard} style={{ '--mc': '#818cf8' }}>
                  <p className={s.metricLabel}>트렌드 지수</p>
                  <p className={s.metricVal} style={{ color: '#818cf8' }}>{metrics?.trend_score ?? '-'}</p>
                  <p className={s.metricSub}>DataLab 관심도</p>
                </div>
                <div className={s.metricCard} style={{ '--mc': (metrics?.growth_rate ?? 0) >= 0 ? '#10b981' : '#ef4444' }}>
                  <p className={s.metricLabel}>성장률</p>
                  <p className={s.metricVal} style={{ color: (metrics?.growth_rate ?? 0) >= 0 ? '#10b981' : '#ef4444' }}>
                    {metrics?.growth_rate != null ? `${metrics.growth_rate >= 0 ? '+' : ''}${metrics.growth_rate}%` : '-'}
                  </p>
                  <p className={s.metricSub}>전기 대비</p>
                </div>
                <div className={s.metricCard} style={{ '--mc': '#a855f7' }}>
                  <p className={s.metricLabel}>집중 브랜드</p>
                  <p className={s.metricVal} style={{ color: '#a855f7' }}>{report.brand_focus}</p>
                  <p className={s.metricSub}>AI 추천 포커스</p>
                </div>
              </div>

              {/* ── Opportunity / Risk ── */}
              <div className={s.insightRow}>
                <div className={s.insightCard} style={{ '--ic': '#10b981' }}>
                  <p className={s.insightLabel}>기회 요인</p>
                  <p className={s.insightText}>{report.opportunity}</p>
                </div>
                <div className={s.insightCard} style={{ '--ic': '#f59e0b' }}>
                  <p className={s.insightLabel}>위험 요인</p>
                  <p className={s.insightText}>{report.risk_summary}</p>
                </div>
              </div>

              {/* ── Brand + Summary ── */}
              <div className={s.bottomRow}>
                <div className={s.card}>
                  <p className={s.cardTitle}>브랜드 점유율</p>
                  <p className={s.cardSub}>판매 제품 수 기준</p>
                  <DonutMini brands={brands} />
                </div>
                <div className={s.summaryCard}>
                  <div className={s.summaryHeader}>
                    <p className={s.cardTitle}>AI 종합 분석</p>
                    <span className={s.ragBadge}>RAG 강화</span>
                  </div>
                  <p className={s.cardSub}>{category} · {periodLabel}</p>
                  <p className={s.summaryText}>{report.summary}</p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* ── Sidebar ── */}
        <div className={s.sidebar}>
          <div className={s.sideSection}>
            <p className={s.sideLabel}>카테고리</p>
            <div className={s.sideCats}>
              {CATEGORIES.map(cat => (
                <button key={cat}
                  className={`${s.sideCatBtn} ${category === cat ? s.sideCatActive : ''}`}
                  onClick={() => setCategory(cat)}>
                  {cat}
                </button>
              ))}
            </div>
          </div>
          <div className={s.sideSection}>
            <p className={s.sideLabel}>분석 기간</p>
            <div className={s.sidePeriods}>
              {PERIODS.map(p => (
                <button key={p.value}
                  className={`${s.sidePeriodBtn} ${period === p.value ? s.sidePeriodActive : ''}`}
                  onClick={() => setPeriod(p.value)}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className={s.sideInfo}>
            <p className={s.sideInfoTitle}>데이터 소스</p>
            <div className={s.sourceList}>
              <span className={s.source}>네이버 DataLab</span>
              <span className={s.source}>네이버 쇼핑</span>
              <span className={s.source}>Groq LLM</span>
              <span className={s.source}>RAG (소비자 데이터)</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
