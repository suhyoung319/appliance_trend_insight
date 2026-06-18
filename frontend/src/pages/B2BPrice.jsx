import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/common/Navbar'
import { useAuth } from '../context/AuthContext'
import s from '../styles/B2BPrice.module.css'
import { API_BASE } from '../config'

const CATEGORIES = ['에어컨', '냉장고', '세탁기', '건조기', '공기청정기', '로봇청소기', '식기세척기', 'TV']
const BRAND_COLORS = ['#6366f1', '#a855f7', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']

const METRIC_COLORS = {
  teal:   '#06b6d4',
  green:  '#10b981',
  blue:   '#6366f1',
  red:    '#ef4444',
  violet: '#818cf8',
  orange: '#f59e0b',
}

const SIGNAL_CONFIG = {
  '매입 적기':  { color: '#10b981', bg: 'rgba(16,185,129,0.1)',  border: 'rgba(16,185,129,0.28)',  icon: '↓' },
  '관망 권장':  { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)',  border: 'rgba(245,158,11,0.28)',  icon: '◎' },
  '적정가':     { color: '#818cf8', bg: 'rgba(99,102,241,0.08)', border: 'rgba(99,102,241,0.22)',  icon: '→' },
}

function fmtPrice(p) {
  if (!p && p !== 0) return '-'
  if (p >= 10000) return `${Math.round(p / 10000).toLocaleString()}만원`
  return `${p.toLocaleString()}원`
}

function fmtShort(p) {
  if (!p && p !== 0) return '-'
  if (p >= 10000) return `${Math.round(p / 10000)}만`
  return `${p}`
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

function PriceHistoryChart({ history }) {
  if (!history || history.length < 2) {
    return (
      <div className={s.firstSnap}>
        오늘 첫 스냅샷이 저장되었습니다.<br />
        <span>내일부터 가격 추이를 확인할 수 있어요</span>
      </div>
    )
  }
  const W = 500, H = 100, padX = 8, padY = 14
  const avgs = history.map(h => h.avg_price)
  const mins = history.map(h => h.min_price)
  const allVals = [...avgs, ...mins]
  const minV = Math.min(...allVals)
  const maxV = Math.max(...allVals, minV + 1)

  const toX = i => padX + (i / (history.length - 1)) * (W - padX * 2)
  const toY = v => padY + (H - padY * 2) * (1 - (v - minV) / (maxV - minV))

  const avgPts = history.map((h, i) => ({ x: toX(i), y: toY(h.avg_price) }))
  const minPts = history.map((h, i) => ({ x: toX(i), y: toY(h.min_price) }))

  const avgLine = avgPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const minLine = minPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')

  // band area between avg and min
  const bandPts = [
    ...avgPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`),
    ...minPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).reverse(),
  ].join(' ')

  const labelIdx = [0, Math.floor(history.length * 0.5), history.length - 1]

  const yMax = Math.round(maxV / 10000)
  const yMid = Math.round((maxV + minV) / 2 / 10000)
  const yMin = Math.round(minV / 10000)

  return (
    <div>
      <div className={s.chartLegend}>
        <span className={s.legendDotInline} style={{ background: '#818cf8' }} /> 평균가
        <span className={s.legendDotInline} style={{ background: '#22c55e', marginLeft: 12 }} /> 최저가
      </div>
      <p className={s.yAxisTitle}>만원</p>
      <div className={s.chartOuter}>
        <div className={s.yAxisWrap} style={{ height: 100 }}>
          <span className={s.yLabel}>{yMax}만</span>
          <span className={s.yLabel}>{yMid}만</span>
          <span className={s.yLabel}>{yMin}만</span>
        </div>
        <div className={s.chartBody}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 100 }}>
            <defs>
              <linearGradient id="bandGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity="0.12" />
                <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            <polygon points={bandPts} fill="url(#bandGrad)" />
            <polyline points={minLine} fill="none" stroke="#22c55e" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
              strokeDasharray="4,3" />
            <polyline points={avgLine} fill="none" stroke="#818cf8" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            <circle cx={avgPts[avgPts.length - 1].x} cy={avgPts[avgPts.length - 1].y} r="4"
              fill="#6366f1" vectorEffect="non-scaling-stroke" />
          </svg>
          <div className={s.xAxis}>
            {labelIdx.map(i => (
              <span key={i}>{history[i]?.date?.slice(5) ?? ''}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function BrandPriceChart({ brands }) {
  if (!brands || brands.length === 0) return <div className={s.noData}>데이터 없음</div>
  const maxAvg = Math.max(...brands.map(b => b.avg_price), 1)
  return (
    <div className={s.brandPriceList}>
      {brands.map((b, i) => (
        <div key={i} className={s.brandPriceRow}>
          <span className={s.brandName}>{b.brand}</span>
          <div className={s.brandBarTrack}>
            <div
              className={s.brandBarFill}
              style={{
                width: `${(b.avg_price / maxAvg) * 100}%`,
                background: BRAND_COLORS[i % BRAND_COLORS.length],
              }}
            />
          </div>
          <span className={s.brandAvgPrice}>{fmtShort(b.avg_price)}</span>
        </div>
      ))}
    </div>
  )
}

function DistributionChart({ distribution }) {
  if (!distribution || distribution.length === 0) return <div className={s.noData}>데이터 없음</div>
  const maxCount = Math.max(...distribution.map(d => d.count), 1)
  return (
    <div className={s.distChart}>
      {distribution.map((d, i) => (
        <div key={i} className={s.distCol}>
          <span className={s.distCount}>{d.count}</span>
          <div className={s.distBarWrap}>
            <div
              className={s.distBar}
              style={{
                height: `${Math.max((d.count / maxCount) * 100, 4)}%`,
                background: BRAND_COLORS[i % BRAND_COLORS.length],
              }}
            />
          </div>
          <span className={s.distLabel}>{d.range}</span>
        </div>
      ))}
    </div>
  )
}


export default function B2BPrice() {
  const navigate = useNavigate()
  const { user, token } = useAuth()
  const [category, setCategory] = useState('에어컨')
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const isB2BActive = (user?.user_type === 'b2b' && user?.status === 'active') || user?.role === 'admin'

  useEffect(() => {
    if (!isB2BActive) return
    setLoading(true)
    setError(null)
    setData(null)
    fetch(`${API_BASE}/api/b2b/price?category=${encodeURIComponent(category)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setError('서버에 연결할 수 없습니다'); setLoading(false) })
  }, [category, isB2BActive])

  if (!isB2BActive) {
    return (
      <div className={s.page}>
        <Navbar />
        <div className={s.accessDenied}>
          <p className={s.accessDeniedTitle}>
            {!user ? '로그인이 필요합니다' : 'B2B 계정 전용입니다'}
          </p>
          <button className={s.accessDeniedBtn} onClick={() => navigate(!user ? '/login' : '/b2b')}>
            {!user ? '로그인' : 'B2B 홈으로'}
          </button>
        </div>
      </div>
    )
  }

  const sum = data?.summary

  const changeColor = sum?.price_change_pct == null
    ? 'blue'
    : sum.price_change_pct <= 0 ? 'green' : 'red'

  const changeLabel = sum?.price_change_pct == null
    ? '첫 스냅샷'
    : `${sum.price_change_pct >= 0 ? '+' : ''}${sum.price_change_pct}%`

  const changeSub = sum?.price_change_pct == null
    ? '이전 데이터 없음'
    : sum.price_change_pct <= 0 ? '전일 대비 하락 (구매 유리)' : '전일 대비 상승 (관망 권장)'

  return (
    <div className={s.page}>
      <Navbar />
      <div className={s.layout}>

        {/* ── Main ── */}
        <div className={s.main}>
          <div className={s.header}>
            <span className={s.badge}>가격 인텔리전스</span>
            <h1 className={s.title}>{category} 가격 분석</h1>
            <p className={s.subtitle}>
              네이버 쇼핑 실시간 가격 데이터 · {sum ? `${sum.total_products}개 제품 분석` : '로딩 중...'}
              {data?.snapshot_date && <span className={s.snapDate}> · {data.snapshot_date} 기준</span>}
            </p>
          </div>

          {loading && (
            <div className={s.loadingWrap}>
              <div className={s.spinner} />
              <p>"{category}" 가격 데이터 수집 중...</p>
            </div>
          )}
          {error && <div className={s.error}>{error}</div>}

          {!loading && data && !data.error && (
            <>
              {/* Metric cards */}
              <div className={s.metricsGrid}>
                <MetricCard title="평균 가격" value={fmtPrice(sum?.avg_price)} sub="분석 제품 평균" colorKey="teal" />
                <MetricCard title="최저가" value={fmtPrice(sum?.min_price)} sub="현재 최저 판매가" colorKey="green" />
                <MetricCard title="중간가" value={fmtPrice(sum?.median_price)} sub="중앙값 기준" colorKey="blue" />
                <MetricCard title="전일 대비" value={changeLabel} sub={changeSub} colorKey={changeColor} />
              </div>

              {/* Charts row */}
              <div className={s.chartsRow}>
                <div className={s.chartCard}>
                  <h2 className={s.cardTitle}>가격 추이</h2>
                  <p className={s.cardSub}>일별 평균가·최저가 변화</p>
                  <PriceHistoryChart history={data.price_history} />
                </div>
                <div className={s.chartCard}>
                  <h2 className={s.cardTitle}>브랜드별 평균가</h2>
                  <p className={s.cardSub}>제품 수 기준 상위 브랜드</p>
                  <BrandPriceChart brands={data.by_brand} />
                </div>
              </div>

              {/* Bottom row */}
              <div className={s.bottomRow}>
                <div className={s.distCard}>
                  <h2 className={s.cardTitle}>가격대 분포</h2>
                  <p className={s.cardSub}>가격 구간별 제품 수</p>
                  <DistributionChart distribution={data.price_distribution} />
                </div>
              </div>

              {/* 최저가 제품 */}
              {data.top_deals && data.top_deals.length > 0 && (
                <div className={s.dealsCard}>
                  <h2 className={s.cardTitle}>최저가 제품 Top 10</h2>
                  <p className={s.cardSub}>현재 네이버 쇼핑 기준 최저가 순</p>
                  <table className={s.dealsTable}>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>브랜드</th>
                        <th>제품명</th>
                        <th>가격</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_deals.map((d, i) => (
                        <tr key={i}>
                          <td className={s.dealsRank}>{i + 1}</td>
                          <td className={s.dealsBrand}>{d.brand || '-'}</td>
                          <td className={s.dealsTitle}>
                            {d.link
                              ? <a href={d.link} target="_blank" rel="noreferrer">{d.title}</a>
                              : d.title}
                          </td>
                          <td className={s.dealsPrice}>{fmtPrice(d.price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* AI 가격 인사이트 */}
              {data.price_insight && (() => {
                const ins = data.price_insight
                const sig = SIGNAL_CONFIG[ins.signal] ?? SIGNAL_CONFIG['적정가']
                return (
                  <div className={s.insightBanner}
                    style={{ '--sc': sig.color, '--sb': sig.bg, '--sbr': sig.border }}>
                    <div className={s.insightBannerLeft}>
                      <p className={s.insightBannerLabel}>AI 가격 인사이트 · RAG 강화</p>
                      <div className={s.insightSignalRow}>
                        <span className={s.insightSignalIcon}>{sig.icon}</span>
                        <span className={s.insightSignalText}>{ins.signal}</span>
                      </div>
                      <p className={s.insightReason}>{ins.reason}</p>
                      <p className={s.insightStrategy}>{ins.strategy}</p>
                    </div>
                    <div className={s.insightBannerRight}>
                      <div className={s.insightMeta}>
                        <span className={s.insightMetaLabel}>납품 추천 브랜드</span>
                        <span className={s.insightMetaValue}>{ins.brand_pick}</span>
                      </div>
                      <div className={s.insightDivider} />
                      <div className={s.insightSummaryWrap}>
                        <span className={s.insightMetaLabel}>종합 분석</span>
                        <p className={s.insightSummaryText}>{ins.summary}</p>
                      </div>
                    </div>
                  </div>
                )
              })()}
            </>
          )}

          {!loading && data?.error && (
            <div className={s.error}>{data.error}</div>
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
          <div className={s.sideInfo}>
            <p className={s.sideInfoTitle}>업데이트 주기</p>
            <p className={s.sideInfoDesc}>매 조회 시 스냅샷 저장<br />일별 히스토리 자동 적립</p>
          </div>
          <div className={s.sideInfo}>
            <p className={s.sideInfoTitle}>데이터 소스</p>
            <div className={s.sourceList}>
              <span className={s.source}>네이버 쇼핑 API</span>
              <span className={s.source}>실시간 최저가</span>
              <span className={s.source}>자체 DB 이력</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
