import styles from '../../../styles/dashboard/b2b/B2BNewsIssue.module.css'

export default function B2BNewsIssue() {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span>B2B NEWS INSIGHT</span>
        <h1>뉴스 이슈</h1>
        <p>가전 시장 관련 뉴스 이슈와 기업 전략에 미치는 영향을 분석합니다.</p>
      </div>

      <div className={styles.cardGrid}>
        <div className={styles.card}>
          <h4>주요 이슈</h4>
          <h2>AI 가전</h2>
          <p>언급량 증가</p>
        </div>

        <div className={styles.card}>
          <h4>뉴스 언급량</h4>
          <h2>318건</h2>
          <p>최근 30일 기준</p>
        </div>

        <div className={styles.card}>
          <h4>시장 영향도</h4>
          <h2>높음</h2>
          <p>프리미엄 제품 중심</p>
        </div>

        <div className={styles.card}>
          <h4>리스크</h4>
          <h2>가격 경쟁</h2>
          <p>중국 브랜드 확산</p>
        </div>
      </div>

      <section className={styles.issueGrid}>
        <div className={styles.issueListBox}>
          <div className={styles.sectionHeader}>
            <h3>최근 주요 뉴스 이슈</h3>
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

      <section className={styles.aiBox}>
        <h2>AI 뉴스 요약</h2>

        <div className={styles.analysis}>
          <h3>올해 가전 시장의 핵심 이슈는 AI 기능 경쟁과 프리미엄 시장 확대입니다.</h3>
          <p>
            최근 뉴스에서는 AI 주행, 자동 먼지 비움, 스마트홈 연동 기능이 반복적으로 언급되고 있습니다.
            기업은 단순 제품 성능보다 AI 기반 사용 경험과 플랫폼 연동성을 중심으로 전략을 설계할 필요가 있습니다.
          </p>

          <div className={styles.strategy}>
            추천 전략 : AI 기능 메시지 강화 · 스마트홈 연동 강조 · 가격 경쟁 대응
          </div>
        </div>
      </section>
    </div>
  )
}