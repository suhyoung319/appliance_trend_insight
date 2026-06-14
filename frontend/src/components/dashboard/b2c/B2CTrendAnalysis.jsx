import styles from '../../../styles/dashboard/b2c/B2CTrendAnalysis.module.css'

const trendCards = [
  {
    category: '에어컨',
    growth: '+38.5%',
    status: '급상승',
    reason: '여름철 수요 증가와 전기요금 절감형 제품 관심 증가',
  },
  {
    category: '로봇청소기',
    growth: '+31.2%',
    status: '상승',
    reason: 'AI 장애물 인식, 자동 먼지 비움 기능 관련 언급 증가',
  },
  {
    category: '냉장고',
    growth: '+18.7%',
    status: '보합',
    reason: '비스포크·오브제 등 인테리어형 대형가전 검색 유지',
  },
]

const monthlyData = [
  { month: '1월', aircon: 32, robot: 42, fridge: 58 },
  { month: '2월', aircon: 38, robot: 46, fridge: 55 },
  { month: '3월', aircon: 52, robot: 55, fridge: 60 },
  { month: '4월', aircon: 67, robot: 64, fridge: 61 },
  { month: '5월', aircon: 82, robot: 72, fridge: 63 },
  { month: '6월', aircon: 94, robot: 80, fridge: 66 },
]

const keywords = ['무풍 에어컨', 'AI 로봇청소기', '비스포크 냉장고', '전기요금 절감', '자동 먼지 비움', '1등급 가전']

export default function B2CTrendAnalysis() {
  return (
    <>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>TREND ANALYSIS</p>
          <h1>가전 트렌드 분석</h1>
          <p>검색량, 쇼핑 순위, 리뷰 언급량을 기반으로 현재 관심도가 높은 가전 카테고리를 분석합니다.</p>
        </div>

        <div className={styles.filterBox}>
          <button className={styles.active}>월간</button>
          <button>주간</button>
          <button>일간</button>
        </div>
      </header>

      <section className={styles.summaryGrid}>
        {trendCards.map(item => (
          <div className={styles.summaryCard} key={item.category}>
            <div>
              <p>{item.status}</p>
              <h2>{item.category}</h2>
            </div>
            <strong>{item.growth}</strong>
            <span>{item.reason}</span>
          </div>
        ))}
      </section>

      <section className={styles.contentGrid}>
        <div className={styles.panelLarge}>
          <div className={styles.panelHeader}>
            <div>
              <h3>카테고리별 검색 관심도 추이</h3>
              <p>최근 6개월 기준 · 0~100 지수</p>
            </div>
            <span>Search Trend</span>
          </div>

          <div className={styles.lineChart}>
            {monthlyData.map(item => (
              <div className={styles.monthGroup} key={item.month}>
                <div className={styles.bars}>
                  <span className={styles.aircon} style={{ height: `${item.aircon}%` }} />
                  <span className={styles.robot} style={{ height: `${item.robot}%` }} />
                  <span className={styles.fridge} style={{ height: `${item.fridge}%` }} />
                </div>
                <p>{item.month}</p>
              </div>
            ))}
          </div>

          <div className={styles.legend}>
            <span><i className={styles.airconDot} />에어컨</span>
            <span><i className={styles.robotDot} />로봇청소기</span>
            <span><i className={styles.fridgeDot} />냉장고</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>AI 분석 요약</h3>
              <p>현재 트렌드 상승 원인</p>
            </div>
          </div>

          <div className={styles.aiInsight}>
            <b>에어컨과 로봇청소기의 관심도가 동시에 상승하고 있습니다.</b>
            <p>
              에어컨은 계절 수요와 전기요금 이슈의 영향을 받고 있으며,
              로봇청소기는 AI 기능과 자동화 편의성에 대한 소비자 관심이 증가하고 있습니다.
            </p>
            <strong>추천 확인 포인트: 가격 변동, 신제품 출시, 리뷰 내 불만 키워드</strong>
          </div>
        </div>
      </section>

      <section className={styles.bottomGrid}>
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>급상승 키워드</h3>
              <p>검색·리뷰·뉴스에서 반복 등장</p>
            </div>
          </div>

          <div className={styles.keywordBox}>
            {keywords.map(keyword => (
              <span key={keyword}>{keyword}</span>
            ))}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <h3>소비자 반응 변화</h3>
              <p>커뮤니티·리뷰 요약</p>
            </div>
          </div>

          <div className={styles.reactionList}>
            <div>
              <b>긍정 증가</b>
              <p>저소음, 자동화, 에너지 효율 관련 만족도가 높게 나타납니다.</p>
            </div>
            <div>
              <b>부정 증가</b>
              <p>설치비, 필터 교체 비용, 배송 지연에 대한 불만이 일부 증가했습니다.</p>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}