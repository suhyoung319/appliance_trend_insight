import styles from '../../../styles/dashboard/b2b/B2BDashboardMain.module.css'

const categoryTrends = [
  { name: '로봇청소기', growth: '+42.8%', score: 92, height: '82%' },
  { name: 'AI 냉장고', growth: '+31.4%', score: 86, height: '68%' },
  { name: '에어컨', growth: '+28.9%', score: 81, height: '61%' },
  { name: '건조기', growth: '+18.6%', score: 74, height: '49%' },
  { name: '식기세척기', growth: '+15.2%', score: 69, height: '42%' },
]

const competitors = [
  { brand: '삼성전자', mention: 38, sentiment: 82, issue: 'AI 기능 강조' },
  { brand: 'LG전자', mention: 34, sentiment: 79, issue: '프리미엄 라인 강화' },
  { brand: '로보락', mention: 21, sentiment: 84, issue: '로봇청소기 급상승' },
  { brand: '샤오미', mention: 15, sentiment: 71, issue: '가성비 수요 증가' },
]

const issues = [
  'AI 가전',
  '에너지 효율',
  '로봇청소기',
  '신제품 출시',
  '프리미엄 가전',
  '가격 인상',
]

export default function B2BDashboardMain() {
  return (
    <>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>B2B MARKET INSIGHT</p>
          <h1>가전 시장 트렌드 분석 대시보드</h1>
          <p>검색량, 리뷰, 뉴스, 커뮤니티 데이터를 기반으로 시장 흐름을 예측합니다.</p>
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
              검색량과 긍정 리뷰가 동시에 증가하고 있으며, 뉴스에서는 AI 주행·자동 먼지 비움 기능이
              반복적으로 언급되고 있습니다.
            </p>
            <span>추천 전략: AI 기능 중심 마케팅 강화 · 30~40대 맞벌이 가구 타깃</span>
          </div>
        </div>
      </section>

      <section className={styles.bottomGrid}>
        <div className={styles.tablePanel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>브랜드 경쟁 분석</h3>
              <p>브랜드 언급량·감성·주요 이슈 비교</p>
            </div>
          </div>

          <table>
            <thead>
              <tr>
                <th>브랜드</th>
                <th>언급 비중</th>
                <th>긍정 반응</th>
                <th>주요 이슈</th>
              </tr>
            </thead>
            <tbody>
              {competitors.map(item => (
                <tr key={item.brand}>
                  <td>{item.brand}</td>
                  <td>{item.mention}%</td>
                  <td>{item.sentiment}%</td>
                  <td>{item.issue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>뉴스·소비자 이슈</h3>
              <p>최근 자주 등장한 키워드</p>
            </div>
          </div>

          <div className={styles.keywordBox}>
            {issues.map(issue => (
              <span key={issue}>{issue}</span>
            ))}
          </div>

          <div className={styles.riskBox}>
            <strong>주의 이슈</strong>
            <p>가격 인상과 AS 만족도 관련 부정 반응이 일부 증가하고 있습니다.</p>
          </div>
        </div>
      </section>
    </>
  )
}