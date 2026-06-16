import styles from '../../../styles/dashboard/b2b/B2BMarketForecast.module.css'

export default function B2BMarketForecast() {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span>B2B MARKET FORECAST</span>
        <h1>시장 전망</h1>
        <p>검색량·뉴스·리뷰 데이터를 기반으로 향후 시장 흐름과 주요 이슈를 분석합니다.</p>
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
          <h4>뉴스 언급량</h4>
          <h2>318건</h2>
          <p>최근 30일 기준</p>
        </div>

        <div className={styles.card}>
          <h4>시장 리스크</h4>
          <h2>가격 경쟁</h2>
          <p>중국 브랜드 확산</p>
        </div>
      </div>

      <section className={styles.forecastGrid}>
        <div className={styles.chartBox}>
          <div className={styles.sectionHeader}>
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

        <div className={styles.impactBox}>
          <div className={styles.sectionHeader}>
            <h3>시장 영향도</h3>
            <span>Impact Score</span>
          </div>

          <div className={styles.score}>
            <h2>92</h2>
            <p>High Impact</p>
          </div>

          <div className={styles.impactList}>
            <div>
              <span>AI 기능 경쟁</span>
              <strong>매우 높음</strong>
            </div>
            <div>
              <span>가격 경쟁</span>
              <strong>높음</strong>
            </div>
            <div>
              <span>규제 영향</span>
              <strong>중간</strong>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.issueBox}>
        <div className={styles.sectionHeader}>
          <h3>주요 시장 이슈</h3>
          <span>News Topic</span>
        </div>

        <div className={styles.issueList}>
          <div className={styles.issueItem}>
            <strong>01</strong>
            <div>
              <h4>삼성 AI 가전 신제품 출시 확대</h4>
              <p>AI 기능 중심의 프리미엄 가전 경쟁이 강화되고 있습니다.</p>
            </div>
            <span>영향도 높음</span>
          </div>

          <div className={styles.issueItem}>
            <strong>02</strong>
            <div>
              <h4>LG 씽큐 플랫폼 연동 기능 강화</h4>
              <p>스마트홈 플랫폼 중심의 생태계 경쟁이 확대되고 있습니다.</p>
            </div>
            <span>영향도 높음</span>
          </div>

          <div className={styles.issueItem}>
            <strong>03</strong>
            <div>
              <h4>로봇청소기 가격 경쟁 심화</h4>
              <p>중국 브랜드의 저가 공세로 가격 경쟁 압력이 증가하고 있습니다.</p>
            </div>
            <span>영향도 중간</span>
          </div>

          <div className={styles.issueItem}>
            <strong>04</strong>
            <div>
              <h4>에너지 효율 규제 강화</h4>
              <p>고효율 제품 개발과 친환경 마케팅의 중요성이 커지고 있습니다.</p>
            </div>
            <span>영향도 중간</span>
          </div>
        </div>
      </section>

      <section className={styles.aiBox}>
        <h2>AI 시장 전망</h2>

        <div className={styles.analysis}>
          <h3>AI 가전 시장은 지속적인 성장 가능성이 높습니다.</h3>

          <p>
            검색량 증가와 뉴스 언급량 상승이 동시에 나타나고 있으며,
            AI 기능·스마트홈 연동·에너지 효율 관련 키워드가 반복적으로 언급되고 있습니다.
            다만 중국 브랜드 확산으로 가격 경쟁 압력이 커지고 있어 프리미엄 기능 차별화가 필요합니다.
          </p>

          <div className={styles.strategy}>
            추천 전략 : AI 기능 메시지 강화 · 스마트홈 연동 강조 · 가격 경쟁 대응
          </div>
        </div>
      </section>
    </div>
  )
}