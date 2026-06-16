import styles from '../../../styles/dashboard/b2b/B2BDashboardMain.module.css'

const categoryTrends = [
  { name: '로봇청소기', growth: '+42.8%', height: '82%' },
  { name: 'AI 냉장고', growth: '+31.4%', height: '68%' },
  { name: '에어컨', growth: '+28.9%', height: '61%' },
  { name: '건조기', growth: '+18.6%', height: '49%' },
  { name: '식기세척기', growth: '+15.2%', height: '42%' },
]

const summaries = [
  '로봇청소기 검색량이 전월 대비 42.8% 증가했습니다.',
  'AI 기능·자동 먼지 비움 키워드가 반복적으로 언급되고 있습니다.',
  '프리미엄 수요는 증가했지만 가격 부담 반응도 함께 나타납니다.',
]

export default function B2BDashboardMain() {
  return (
    <>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>B2B MARKET INSIGHT</p>
          <h1>가전 시장 트렌드 분석 대시보드</h1>
          <p>시장 전망, 소비자 반응, 경쟁 흐름을 한눈에 요약합니다.</p>
        </div>

        <div className={styles.searchBox}>
          <input placeholder="카테고리 또는 브랜드 검색" />
          <button>분석</button>
        </div>
      </header>

      <section className={styles.statsGrid}>
        <div className={styles.statCard}>
          <p>급상승 카테고리</p>
          <h2>로봇청소기</h2>
          <span>전월 대비 +42.8%</span>
        </div>

        <div className={styles.statCard}>
          <p>시장 관심도 지수</p>
          <h2>87점</h2>
          <span>검색·뉴스·리뷰 통합</span>
        </div>

        <div className={styles.statCard}>
          <p>뉴스 언급량</p>
          <h2>318건</h2>
          <span>최근 30일 기준</span>
        </div>

        <div className={styles.statCard}>
          <p>AI 예측</p>
          <h2>상승</h2>
          <span>3개월 수요 증가 예상</span>
        </div>
      </section>

      <section className={styles.contentGrid}>
        <div className={styles.panelLarge}>
          <div className={styles.panelHeader}>
            <div>
              <h3>카테고리별 성장률 예측</h3>
              <p>검색량 증가율과 뉴스 언급량 기반</p>
            </div>
            <span>Next 3 Months</span>
          </div>

          <div className={styles.chartBox}>
            {categoryTrends.map(item => (
              <div key={item.name} className={styles.barItem}>
                <span className={styles.barValue}>{item.growth}</span>
                <div className={styles.barWrap}>
                  <div className={styles.bar} style={{ height: item.height }} />
                </div>
                <strong>{item.name}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>AI 시장 판단</h3>
              <p>기업 전략용 요약 리포트</p>
            </div>
          </div>

          <div className={styles.aiBox}>
            <b>프리미엄 로봇청소기 시장 확대 가능성이 높습니다.</b>
            <p>
              검색량과 긍정 리뷰가 동시에 증가하고 있으며, AI 주행·자동 먼지 비움 기능이
              반복적으로 언급되고 있습니다.
            </p>
            <span>추천 전략: AI 기능 중심 마케팅 강화 · 30~40대 맞벌이 가구 타깃</span>
          </div>
        </div>
      </section>

      <section className={styles.summaryPanel}>
        <div className={styles.panelHeader}>
          <div>
            <h3>오늘의 핵심 요약</h3>
            <p>시장 전망·뉴스·소비자 반응 통합 요약</p>
          </div>
        </div>

        <div className={styles.summaryList}>
          {summaries.map((summary, index) => (
            <div key={summary} className={styles.summaryItem}>
              <strong>{String(index + 1).padStart(2, '0')}</strong>
              <span>{summary}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}