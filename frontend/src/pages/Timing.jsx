import { useState } from 'react'
import Navbar from '../components/common/Navbar'
import styles from '../styles/Timing.module.css'
import { API_BASE } from '../config'

const QUICK_EXAMPLES = [
  '삼성 비스포크 냉장고',
  'LG 스타일러',
  '다이슨 에어랩',
  '삼성 갤럭시 버즈',
  '로보락 로봇청소기',
  'LG 휘센 에어컨',
  '삼성 드럼세탁기',
  '브레빌 에스프레소',
]

const COLOR_MAP = {
  green:  { bg: 'rgba(34,197,94,0.1)', border: 'rgba(34,197,94,0.3)', text: '#22c55e' },
  blue:   { bg: 'rgba(59,130,246,0.1)', border: 'rgba(59,130,246,0.3)', text: '#3b82f6' },
  yellow: { bg: 'rgba(234,179,8,0.1)', border: 'rgba(234,179,8,0.3)', text: '#eab308' },
  red:    { bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.3)', text: '#ef4444' },
}

function TrendChart({ data }) {
  if (!data || data.length < 2) return null

  const W = 600, H = 140, padX = 8, padY = 14
  const ratios = data.map(d => d.ratio)
  const maxR = Math.max(...ratios, 1)
  const pts = data.map((d, i) => {
    const x = padX + (i / (data.length - 1)) * (W - padX * 2)
    const y = padY + (H - padY * 2) * (1 - d.ratio / maxR)
    return [x, y]
  })
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${padX},${H - padY} ${line} ${W - padX},${H - padY}`
  const labelIdx = [0, Math.floor(data.length / 3), Math.floor(data.length * 2 / 3), data.length - 1]

  return (
    <div className={styles.chartWrap}>
      <div className={styles.chartYAxis}>
        <span>{Math.round(maxR)}</span>
        <span>{Math.round(maxR / 2)}</span>
        <span>0</span>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
          style={{ width: '100%', height: '140px', display: 'block' }}>
          <defs>
            <linearGradient id="timingGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <polygon points={area} fill="url(#timingGrad)" />
          <polyline points={line} fill="none" stroke="#818cf8" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="4"
            fill="#6366f1" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className={styles.chartXAxis}>
          {labelIdx.map(i => (
            <span key={i}>{data[i]?.period?.slice(5, 10)}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function Timing() {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function search(q) {
    const term = q.trim()
    if (!term) return
    setQuery(term)
    setInput(term)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await fetch(
        `${API_BASE}/api/timing?category=${encodeURIComponent(term)}`
      ).then(r => r.json())
      if (!data.analysis) {
        setError(data.error ?? `"${term}"에 대한 트렌드 데이터를 찾지 못했습니다.`)
      } else {
        setResult(data)
      }
    } catch {
      setError('서버에 연결할 수 없습니다')
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    search(input)
  }

  const analysis = result?.analysis
  const col = analysis ? COLOR_MAP[analysis.color] ?? COLOR_MAP.blue : null

  return (
    <div className={styles.page}>
      <Navbar />
      <div className={styles.container}>

        <div className={styles.header}>
          <span className={styles.badge}>구매 타이밍</span>
          <h1 className={styles.title}>지금 사야 할까요?</h1>
          <p className={styles.subtitle}>
            제품명을 입력하면 네이버 DataLab 90일 검색 관심도로<br />
            지금이 구매 적기인지 분석해드려요.
          </p>
        </div>

        {/* 검색창 */}
        <form className={styles.searchForm} onSubmit={handleSubmit}>
          <input
            className={styles.searchInput}
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="예: 삼성 비스포크 냉장고, LG 휘센 에어컨, 다이슨 에어랩..."
          />
          <button className={styles.searchBtn} type="submit" disabled={!input.trim() || loading}>
            {loading ? '분석 중...' : '분석하기'}
          </button>
        </form>

        {/* 예시 태그 */}
        {!result && !loading && (
          <div className={styles.examples}>
            {QUICK_EXAMPLES.map(ex => (
              <button key={ex} className={styles.exTag} onClick={() => search(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}

        {/* 로딩 */}
        {loading && (
          <div className={styles.loadingWrap}>
            <div className={styles.spinner} />
            <p>"{query}" 트렌드 데이터 분석 중...</p>
          </div>
        )}

        {/* 에러 */}
        {error && (
          <div className={styles.errorWrap}>
            <p className={styles.errorText}>{error}</p>
            <button className={styles.retryBtn} onClick={() => { setError(null); setResult(null) }}>
              다시 검색
            </button>
          </div>
        )}

        {/* 분석 결과 */}
        {!loading && analysis && (
          <div className={styles.resultWrap}>

            <p className={styles.queryLabel}>
              <span className={styles.queryChip}>"{query}"</span> 구매 타이밍 분석
            </p>

            {/* 점수 카드 */}
            <div className={styles.scoreCard}
              style={{ background: col.bg, borderColor: col.border }}>
              <div className={styles.scoreLeft}>
                <p className={styles.scoreLabel}>구매 타이밍</p>
                <p className={styles.scoreBig} style={{ color: col.text }}>
                  {analysis.score}
                </p>
                <p className={styles.scoreMsg}>{analysis.message}</p>
              </div>
              <div className={styles.scoreRight}>
                <div className={styles.statItem}>
                  <span className={styles.statLabel}>현재 관심도</span>
                  <span className={styles.statNum}>{analysis.current}</span>
                </div>
                <div className={styles.statItem}>
                  <span className={styles.statLabel}>90일 평균</span>
                  <span className={styles.statNum}>{analysis.avg90}</span>
                </div>
                <div className={styles.statItem}>
                  <span className={styles.statLabel}>평균 대비</span>
                  <span className={styles.statNum} style={{ color: col.text }}>
                    {analysis.diff_pct > 0 ? '+' : ''}{analysis.diff_pct}%
                  </span>
                </div>
                <div className={styles.statItem}>
                  <span className={styles.statLabel}>추세</span>
                  <span className={styles.statNum}>{analysis.trend_dir}</span>
                </div>
              </div>
            </div>

            {/* 트렌드 차트 */}
            <div className={styles.chartCard}>
              <p className={styles.chartTitle}>최근 90일 검색 관심도 추이</p>
              <TrendChart data={result.data} />
              <p className={styles.chartNote}>
                최고점 기록일: {analysis.peak_day} &nbsp;·&nbsp; 최고점 = 100 기준
              </p>
            </div>

            {/* 다시 검색 */}
            <button className={styles.resetBtn} onClick={() => { setResult(null); setError(null); setInput('') }}>
              ← 다른 제품 분석
            </button>

          </div>
        )}

      </div>
    </div>
  )
}
