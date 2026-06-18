import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/common/Navbar'
import { useAuth } from '../context/AuthContext'
import s from '../styles/B2BDashboard.module.css'
import { API_BASE } from '../config'

const CATEGORIES = ['에어컨', '냉장고', '세탁기', '건조기', '공기청정기', '로봇청소기', '식기세척기', 'TV']
const PERIODS = [
  { label: '1개월', value: '1m' },
  { label: '3개월', value: '3m' },
  { label: '6개월', value: '6m' },
  { label: '1년',   value: '1y' },
]
const BRAND_COLORS = ['#6366f1', '#a855f7', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']

const METRIC_COLORS = {
  teal:   '#06b6d4',
  purple: '#a855f7',
  green:  '#10b981',
  red:    '#ef4444',
  blue:   '#6366f1',
  violet: '#818cf8',
  orange: '#f59e0b',
  pink:   '#ec4899',
}

function MetricCard({ title, value, sub, colorKey }) {
  return (
    <div className={s.metricCard} style={{ '--metric-color': METRIC_COLORS[colorKey] ?? METRIC_COLORS.teal }}>
      <p className={s.metricTitle}>{title}</p>
      <p className={s.metricValue}>{value}</p>
      {sub && <p className={s.metricSub}>{sub}</p>}
    </div>
  )
}

function LineChart({ data }) {
  if (!data || data.length < 2) return <div className={s.noData}>데이터 없음</div>
  const W = 500, H = 96, padX = 8, padY = 10
  const vals = data.map(d => d.ratio)
  const maxV = Math.max(...vals, 1)
  const positives = vals.filter(v => v > 0)
  const minV = Math.max(0, (positives.length ? Math.min(...positives) : 0) * 0.85)
  const range = maxV - minV || 1
  const pts = data.map((d, i) => ({
    x: padX + (i / (data.length - 1)) * (W - padX * 2),
    y: padY + (H - padY * 2) * (1 - (d.ratio - minV) / range),
  }))
  const line = pts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const area = `${padX},${H - padY} ${line} ${W - padX},${H - padY}`
  const labelIdx = [0, Math.floor(data.length * 0.33), Math.floor(data.length * 0.66), data.length - 1]
  const yMid = Math.round((maxV + minV) / 2)
  return (
    <div>
      <p className={s.yAxisTitle}>검색 관심도</p>
      <div className={s.chartOuter}>
        <div className={s.yAxisWrap} style={{ height: 96 }}>
          <span className={s.yLabel}>{Math.round(maxV)}</span>
          <span className={s.yLabel}>{yMid}</span>
          <span className={s.yLabel}>{Math.round(minV)}</span>
        </div>
        <div className={s.chartBody}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 96 }}>
            <defs>
              <linearGradient id="lg1" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity="0.28" />
                <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            <polygon points={area} fill="url(#lg1)" />
            <polyline points={line} fill="none" stroke="#818cf8" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            <circle cx={pts[pts.length - 1].x} cy={pts[pts.length - 1].y} r="4"
              fill="#6366f1" vectorEffect="non-scaling-stroke" />
          </svg>
          <div className={s.xAxis}>
            {labelIdx.map(i => <span key={i}>{data[i]?.period?.slice(5, 10) ?? ''}</span>)}
          </div>
        </div>
      </div>
    </div>
  )
}

function DonutChart({ brands }) {
  if (!brands || brands.length === 0) return <div className={s.noData}>데이터 없음</div>
  const R = 50, cx = 64, cy = 64, stroke = 18
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
    <div className={s.donutWrap}>
      <svg width={128} height={128}>
        {slices.map((sl, i) => (
          <path key={i} d={arc(sl.start, sl.pct)}
            fill="none" stroke={sl.color} strokeWidth={stroke} strokeLinecap="butt" />
        ))}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize="9" fill="var(--text-muted)">1위</text>
        <text x={cx} y={cy + 10} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--text)">
          {slices[0]?.brand?.slice(0, 5) ?? ''}
        </text>
      </svg>
      <div className={s.legend}>
        {slices.slice(0, 6).map((sl, i) => (
          <div key={i} className={s.legendItem}>
            <span className={s.legendDot} style={{ background: sl.color }} />
            <span className={s.legendBrand}>{sl.brand}</span>
            <span className={s.legendPct}>{sl.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function BarChart({ data }) {
  if (!data || data.length === 0) return <div className={s.noData}>데이터 없음</div>
  const max = Math.max(...data.map(d => d.pct), 1)
  return (
    <div className={s.barList}>
      {data.map((d, i) => (
        <div key={i} className={s.barRow}>
          <span className={s.barLabel}>{d.label}</span>
          <div className={s.barTrack}>
            <div className={s.barFill} style={{ width: `${(d.pct / max) * 100}%` }} />
          </div>
          <span className={s.barPct}>{d.pct}%</span>
        </div>
      ))}
    </div>
  )
}

function BrandTable({ brands }) {
  if (!brands || brands.length === 0) return <div className={s.noData}>데이터 없음</div>
  return (
    <table className={s.brandTable}>
      <thead>
        <tr>
          <th>#</th>
          <th>브랜드</th>
          <th>점유율</th>
          <th>비율</th>
        </tr>
      </thead>
      <tbody>
        {brands.map((b, i) => (
          <tr key={i}>
            <td className={s.rankCell}>{i + 1}</td>
            <td className={s.brandCell}>{b.brand}</td>
            <td className={s.pctCell}>
              <span className={s.pctBadge}
                style={{
                  background: `${BRAND_COLORS[i % BRAND_COLORS.length]}22`,
                  color: BRAND_COLORS[i % BRAND_COLORS.length],
                }}>
                {b.pct}%
              </span>
            </td>
            <td className={s.barTd}>
              <div className={s.miniBarTrack}>
                <div className={s.miniBarFill}
                  style={{ width: `${b.pct}%`, background: BRAND_COLORS[i % BRAND_COLORS.length] }} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function KeywordCloud({ keywords }) {
  if (!keywords || keywords.length === 0) return <div className={s.noData}>데이터 없음</div>
  return (
    <div className={s.cloud}>
      {keywords.map((kw, i) => {
        const size = i < 3 ? 'lg' : i < 8 ? 'md' : 'sm'
        return <span key={kw} className={`${s.cloudTag} ${s[`cloudTag${size}`]}`}>{kw}</span>
      })}
    </div>
  )
}

export default function B2BDashboard() {
  const navigate = useNavigate()
  const { user, token } = useAuth()
  const [category, setCategory] = useState('에어컨')
  const [period, setPeriod] = useState('3m')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const isB2BActive = (user?.user_type === 'b2b' && user?.status === 'active') || user?.role === 'admin'

  useEffect(() => {
    if (!isB2BActive) return
    setLoading(true)
    setError(null)
    setData(null)
    fetch(`${API_BASE}/api/b2b/dashboard?category=${encodeURIComponent(category)}&period=${period}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setError('서버에 연결할 수 없습니다'); setLoading(false) })
  }, [category, period, isB2BActive])

  if (!isB2BActive) {
    return (
      <div className={s.page}>
        <Navbar />
        <div className={s.accessDenied}>
          <p className={s.accessDeniedTitle}>
            {!user ? '로그인이 필요합니다' : user.user_type !== 'b2b' ? 'B2B 계정 전용입니다' : '승인 대기 중입니다'}
          </p>
          <p className={s.accessDeniedDesc}>
            {!user ? 'B2B 계정으로 로그인해주세요' : user.user_type !== 'b2b' ? 'B2B 가입 후 이용할 수 있어요' : '관리자 승인 후 사용 가능합니다'}
          </p>
          <button className={s.accessDeniedBtn} onClick={() => navigate(!user ? '/login' : '/b2b')}>
            {!user ? '로그인' : 'B2B 홈으로'}
          </button>
        </div>
      </div>
    )
  }

  const report = data?.market_report
  const topBrand = data?.brands?.[0]
  const topAge = data?.age_distribution?.reduce(
    (a, b) => b.pct > a.pct ? b : a,
    { label: '-', pct: 0 }
  )

  return (
    <div className={s.page}>
      <Navbar />
      <div className={s.layout}>

        {/* ── Main ── */}
        <div className={s.main}>
          <div className={s.header}>
            <span className={s.badge}>B2B 시장 분석</span>
            <h1 className={s.title}>{category} 카테고리 트렌드</h1>
            <p className={s.subtitle}>검색량·브랜드·연령 데이터 통합 분석</p>
          </div>

          {loading && (
            <div className={s.loadingWrap}>
              <div className={s.spinner} />
              <p>"{category}" 시장 데이터 분석 중...</p>
            </div>
          )}
          {error && <div className={s.error}>{error}</div>}

          {!loading && data && (
            <>
              {/* Metric cards */}
              <div className={s.metricsGrid}>
                <MetricCard title="검색 트렌드 지수" value={report?.trend_score ?? '-'} sub="DataLab 관심도" colorKey="teal" />
                <MetricCard
                  title="성장률"
                  value={report?.growth_rate != null ? `${report.growth_rate >= 0 ? '+' : ''}${report.growth_rate}%` : '-'}
                  sub="전기 대비 변화"
                  colorKey={report?.growth_rate >= 0 ? 'green' : 'red'}
                />
                <MetricCard
                  title="시장 위험도"
                  value={report?.risk ?? '-'}
                  sub="변동성 분석"
                  colorKey={report?.risk === '낮음' ? 'teal' : report?.risk === '중간' ? 'orange' : 'red'}
                />
                <MetricCard title="1위 브랜드" value={topBrand?.brand ?? '-'} sub={topBrand ? `점유율 ${topBrand.pct}%` : '—'} colorKey="purple" />
                <MetricCard title="주요 소비층" value={topAge?.label ?? '-'} sub={topAge?.pct ? `관심도 ${topAge.pct}%` : '—'} colorKey="blue" />
              </div>

              {/* Charts row */}
              <div className={s.chartsRow}>
                <div className={s.chartCard}>
                  <h2 className={s.cardTitle}>검색량 트렌드</h2>
                  <p className={s.cardSub}>{period === '1y' ? '월별' : period === '1m' ? '일별' : '주별'} 검색 관심도 추이</p>
                  <LineChart data={data.trend} />
                </div>
                <div className={s.chartCard}>
                  <h2 className={s.cardTitle}>브랜드 점유율</h2>
                  <p className={s.cardSub}>판매 제품 수 기준</p>
                  <DonutChart brands={data.brands} />
                </div>
                <div className={s.chartCard}>
                  <h2 className={s.cardTitle}>연령별 관심도</h2>
                  <p className={s.cardSub}>연령대별 검색 비중</p>
                  <BarChart data={data.age_distribution} />
                </div>
              </div>

              {/* Bottom row */}
              <div className={s.bottomRow}>
                <div className={s.tableCard}>
                  <h2 className={s.cardTitle}>브랜드별 상세</h2>
                  <p className={s.cardSub}>판매 점유율 순위</p>
                  <BrandTable brands={data.brands} />
                </div>
                <div className={s.kwCard}>
                  <h2 className={s.cardTitle}>주요 키워드</h2>
                  <p className={s.cardSub}>트렌드 연관 키워드</p>
                  <KeywordCloud keywords={data.keywords} />
                </div>
              </div>

              {/* AI Report */}
              {report && (
                <div className={s.reportCard}>
                  <div className={s.reportHeader}>
                    <div>
                      <h2 className={s.reportTitle}>AI 시장 리포트</h2>
                      <p className={s.reportSubtitle}>{category} · {PERIODS.find(p => p.value === period)?.label} · RAG 강화 분석</p>
                    </div>
                    <div className={s.reportPills}>
                      <span className={s.reportPill} style={{
                        color: report.growth_rate >= 0 ? '#22c55e' : '#f87171',
                        background: report.growth_rate >= 0 ? 'rgba(34,197,94,0.1)' : 'rgba(248,113,113,0.1)',
                        borderColor: report.growth_rate >= 0 ? 'rgba(34,197,94,0.25)' : 'rgba(248,113,113,0.25)',
                      }}>
                        {report.growth_rate >= 0 ? '▲' : '▼'} {Math.abs(report.growth_rate)}%
                      </span>
                      <span className={s.reportPill} style={{
                        color: report.risk === '낮음' ? '#22c55e' : report.risk === '중간' ? '#f59e0b' : '#f87171',
                        background: report.risk === '낮음' ? 'rgba(34,197,94,0.1)' : report.risk === '중간' ? 'rgba(245,158,11,0.1)' : 'rgba(248,113,113,0.1)',
                        borderColor: report.risk === '낮음' ? 'rgba(34,197,94,0.25)' : report.risk === '중간' ? 'rgba(245,158,11,0.25)' : 'rgba(248,113,113,0.25)',
                      }}>
                        위험도 {report.risk}
                      </span>
                    </div>
                  </div>
                  <p className={s.reportSummary}>{report.summary}</p>
                </div>
              )}
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
              <span className={s.source}>Groq AI</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
