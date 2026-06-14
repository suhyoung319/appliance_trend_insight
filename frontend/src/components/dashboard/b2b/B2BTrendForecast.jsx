import styles from '../../../styles/dashboard/b2b/B2BTrendForecast.module.css'

export default function B2BTrendForecast() {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span>B2B MARKET INSIGHT</span>
        <h1>트렌드 예측</h1>
        <p>검색량·뉴스·리뷰 데이터를 기반으로 향후 시장 흐름을 분석합니다.</p>
      </div>

      <div className={styles.cardGrid}>
        <div className={styles.card}>
          <h4>예상 성장률</h4>
          <h2>+32.4%</h2>
          <p>6개월 기준</p>
        </div>

        <div className={styles.card}>
          <h4>예상 수요</h4>
          <h2>상승</h2>
          <p>AI 가전 수요 증가</p>
        </div>

        <div className={styles.card}>
          <h4>시장 규모</h4>
          <h2>1.8조원</h2>
          <p>국내 시장 추정</p>
        </div>

        <div className={styles.card}>
          <h4>신제품 영향</h4>
          <h2>높음</h2>
          <p>프리미엄 시장 확대</p>
        </div>
      </div>

      <div className={styles.chartBox}>
        <div className={styles.chartHeader}>
          <h3>6개월 성장 예측</h3>
          <span>Forecast</span>
        </div>

        <div className={styles.chart}>
          <div className={styles.line}></div>

          <div className={styles.point1}></div>
          <div className={styles.point2}></div>
          <div className={styles.point3}></div>
          <div className={styles.point4}></div>
          <div className={styles.point5}></div>
          <div className={styles.point6}></div>

          <div className={styles.months}>
            <span>6월</span>
            <span>7월</span>
            <span>8월</span>
            <span>9월</span>
            <span>10월</span>
            <span>11월</span>
          </div>
        </div>
      </div>

      <div className={styles.aiBox}>
        <h2>AI 시장 전망</h2>

        <div className={styles.analysis}>
          <h3>AI 냉장고 시장은 지속적인 성장 가능성이 높습니다.</h3>

          <p>
            검색량 증가와 프리미엄 가전 수요 확대가 동시에 나타나고 있으며,
            에너지 효율 및 AI 기능에 대한 관심이 꾸준히 증가하고 있습니다.
          </p>

          <div className={styles.strategy}>
            추천 전략 : AI 기능 중심 마케팅 · 프리미엄 제품 확대
          </div>
        </div>
      </div>
    </div>
  )
}