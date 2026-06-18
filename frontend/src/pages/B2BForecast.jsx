import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/common/Navbar';
import { useAuth } from '../context/AuthContext';
import s from '../styles/B2BForecast.module.css';
import { API_BASE } from '../config';

const CATEGORIES = ['에어컨', '냉장고', '세탁기', '건조기', '공기청정기', '로봇청소기', '식기세척기', 'TV'];
const PERIODS = [
    { label: '1개월', value: '1m' },
    { label: '3개월', value: '3m' },
    { label: '6개월', value: '6m' },
    { label: '1년', value: '1y' },
];

const TREND_CONFIG = {
    상승: { color: '#10b981', bg: 'rgba(16,185,129,0.1)', icon: '↑' },
    하락: { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', icon: '↓' },
    안정: { color: '#6366f1', bg: 'rgba(99,102,241,0.1)', icon: '→' },
};

function ForecastChart({ history, forecast }) {
    if (!history || history.length < 2) return <div className={s.noData}>데이터 없음</div>;

    const W = 560,
        H = 140,
        padX = 10,
        padY = 16;
    const allRatios = [...history.map((d) => d.ratio), ...forecast.flatMap((d) => [d.predicted, d.ci_high])];
    const maxV = Math.max(...allRatios, 1);
    const positives = allRatios.filter((v) => v > 0);
    const dataMin = positives.length ? Math.min(...positives) : 0;
    const minV = Math.max(0, dataMin * 0.85); // 하단 여백 15%, 0 이하 방지
    const range = maxV - minV || 1;

    const totalPts = history.length + forecast.length;
    const toX = (i) => padX + (i / (totalPts - 1)) * (W - padX * 2);
    const toY = (v) => padY + (H - padY * 2) * (1 - (v - minV) / range);

    const histPts = history.map((d, i) => ({ x: toX(i), y: toY(d.ratio) }));
    const fcastPts = forecast.map((d, i) => ({
        x: toX(history.length + i),
        y: toY(d.predicted),
        yLow: toY(d.ci_high), // ci_high maps to lower y (higher on chart)
        yHigh: toY(d.ci_low), // ci_low  maps to higher y (lower on chart)
    }));

    const histLine = histPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const fcastLine = fcastPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

    // CI band polygon: top edge (ci_high) left-to-right, then bottom edge (ci_low) right-to-left
    const ciTop = fcastPts.map((p) => `${p.x.toFixed(1)},${p.yLow.toFixed(1)}`).join(' ');
    const ciBot = [...fcastPts]
        .reverse()
        .map((p) => `${p.x.toFixed(1)},${p.yHigh.toFixed(1)}`)
        .join(' ');

    // Divider x position
    const divX = toX(history.length - 1);

    // X-axis labels
    const histLabelIdx = [0, Math.floor(history.length * 0.5), history.length - 1];
    const fcastLabelIdx = [0, forecast.length - 1];

    const yMid = Math.round((maxV + minV) / 2);
    const yMin = Math.round(minV);

    return (
        <div>
            <p className={s.yAxisTitle}>검색 관심도</p>
            <div className={s.chartOuter}>
                <div className={s.yAxisWrap} style={{ height: 140 }}>
                    <span className={s.yLabel}>{Math.round(maxV)}</span>
                    <span className={s.yLabel}>{yMid}</span>
                    <span className={s.yLabel}>{yMin}</span>
                </div>
                <div className={s.chartBody}>
                    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 140 }}>
                        <defs>
                            <linearGradient id="histGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#6366f1" stopOpacity="0.18" />
                                <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
                            </linearGradient>
                        </defs>

                        {/* CI band */}
                        <polygon points={`${ciTop} ${ciBot}`} fill="rgba(16,185,129,0.08)" />

                        {/* Divider */}
                        <line
                            x1={divX}
                            y1={padY - 6}
                            x2={divX}
                            y2={H - padY + 4}
                            stroke="rgba(99,102,241,0.3)"
                            strokeWidth="1.5"
                            strokeDasharray="4 3"
                            vectorEffect="non-scaling-stroke"
                        />

                        {/* History area fill */}
                        <polygon points={`${padX},${H - padY} ${histLine} ${divX},${H - padY}`} fill="url(#histGrad)" />

                        {/* History line */}
                        <polyline
                            points={histLine}
                            fill="none"
                            stroke="#818cf8"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            vectorEffect="non-scaling-stroke"
                        />

                        {/* Forecast line (dashed) */}
                        {fcastPts.length > 0 && (
                            <polyline
                                points={`${histPts[histPts.length - 1].x.toFixed(1)},${histPts[histPts.length - 1].y.toFixed(1)} ${fcastLine}`}
                                fill="none"
                                stroke="#10b981"
                                strokeWidth="2"
                                strokeDasharray="6 4"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                vectorEffect="non-scaling-stroke"
                            />
                        )}

                        {/* Last actual point */}
                        <circle
                            cx={histPts[histPts.length - 1].x}
                            cy={histPts[histPts.length - 1].y}
                            r="4"
                            fill="#6366f1"
                            vectorEffect="non-scaling-stroke"
                        />

                        {/* Last forecast point */}
                        {fcastPts.length > 0 && (
                            <circle
                                cx={fcastPts[fcastPts.length - 1].x}
                                cy={fcastPts[fcastPts.length - 1].y}
                                r="4"
                                fill="#10b981"
                                vectorEffect="non-scaling-stroke"
                            />
                        )}
                    </svg>

                    <div className={s.xAxis}>
                        <div className={s.xAxisHist}>
                            {histLabelIdx.map((i) => (
                                <span
                                    key={i}
                                    style={{
                                        textAlign: i === 0 ? 'left' : i === history.length - 1 ? 'right' : 'center',
                                    }}
                                >
                                    {history[i]?.period?.slice(5, 10) ?? ''}
                                </span>
                            ))}
                        </div>
                        <div className={s.xAxisFcast}>
                            {fcastLabelIdx.map((i) => (
                                <span key={i} style={{ textAlign: i === 0 ? 'left' : 'right', color: '#10b981' }}>
                                    {forecast[i]?.period?.slice(5, 10) ?? ''}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            <div className={s.chartLegend}>
                <span className={s.legendItem}>
                    <span className={s.legendLine} style={{ background: '#818cf8' }} />
                    실제 데이터
                </span>
                <span className={s.legendItem}>
                    <span className={s.legendDash} />
                    예측
                </span>
                <span className={s.legendItem}>
                    <span className={s.legendBand} />
                    신뢰 구간
                </span>
            </div>
        </div>
    );
}

function ForecastTable({ forecast }) {
    if (!forecast || forecast.length === 0) return null;
    return (
        <table className={s.fcastTable}>
            <thead>
                <tr>
                    <th>예측 기간</th>
                    <th>예측 관심도</th>
                    <th>하한</th>
                    <th>상한</th>
                </tr>
            </thead>
            <tbody>
                {forecast.map((f, i) => (
                    <tr key={i}>
                        <td className={s.periodCell}>{f.period}</td>
                        <td className={s.predCell}>
                            <span className={s.predBadge}>{f.predicted}</span>
                        </td>
                        <td className={s.ciCell}>{f.ci_low}</td>
                        <td className={s.ciCell}>{f.ci_high}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

function AccessDenied({ user, navigate }) {
    return (
        <div className={s.page}>
            <Navbar />
            <div className={s.denied}>
                <p className={s.deniedTitle}>
                    {!user
                        ? '로그인이 필요합니다'
                        : user.user_type !== 'b2b'
                          ? 'B2B 계정 전용입니다'
                          : '승인 대기 중입니다'}
                </p>
                <p className={s.deniedDesc}>
                    {!user
                        ? 'B2B 계정으로 로그인해주세요'
                        : user.user_type !== 'b2b'
                          ? 'B2B 가입 후 이용할 수 있어요'
                          : '관리자 승인 후 사용 가능합니다'}
                </p>
                <button className={s.deniedBtn} onClick={() => navigate(!user ? '/login' : '/b2b')}>
                    {!user ? '로그인' : 'B2B 홈으로'}
                </button>
            </div>
        </div>
    );
}

export default function B2BForecast() {
    const navigate = useNavigate();
    const { user, token } = useAuth();
    const [category, setCategory] = useState('에어컨');
    const [period, setPeriod] = useState('3m');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const isB2BActive = (user?.user_type === 'b2b' && user?.status === 'active') || user?.role === 'admin';

    useEffect(() => {
        if (!isB2BActive) return;
        setLoading(true);
        setError(null);
        setData(null);
        fetch(`${API_BASE}/api/b2b/demand-forecast?category=${encodeURIComponent(category)}&period=${period}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
            .then((r) => r.json())
            .then((d) => {
                setData(d);
                setLoading(false);
            })
            .catch(() => {
                setError('서버에 연결할 수 없습니다');
                setLoading(false);
            });
    }, [category, period, isB2BActive]);

    if (!isB2BActive) return <AccessDenied user={user} navigate={navigate} />;

    const tcfg = TREND_CONFIG[data?.trend_direction ?? '안정'] ?? TREND_CONFIG['안정'];
    const periodLabel = PERIODS.find((p) => p.value === period)?.label ?? period;

    return (
        <div className={s.page}>
            <Navbar />
            <div className={s.layout}>
                {/* ── Main ── */}
                <div className={s.main}>
                    <div className={s.header}>
                        <span className={s.badge}>수요 예측</span>
                        <h1 className={s.title}>{category} 수요 예측 대시보드</h1>
                        <p className={s.subtitle}>선형 회귀 모델 + RAG 강화 · {periodLabel} 기반 예측</p>
                    </div>

                    {loading && (
                        <div className={s.loadingWrap}>
                            <div className={s.spinner} />
                            <p>"{category}" 수요 예측 모델 실행 중...</p>
                        </div>
                    )}
                    {error && <div className={s.error}>{error}</div>}

                    {!loading && data && !data.error && (
                        <>
                            {/* ── Metrics ── */}
                            <div className={s.metricsRow}>
                                <div className={s.metricCard} style={{ '--mc': tcfg.color, '--mb': tcfg.bg }}>
                                    <p className={s.metricLabel}>트렌드 방향</p>
                                    <div className={s.trendMain}>
                                        <span className={s.trendIcon} style={{ color: tcfg.color }}>
                                            {tcfg.icon}
                                        </span>
                                        <span className={s.trendText} style={{ color: tcfg.color }}>
                                            {data.trend_direction}
                                        </span>
                                    </div>
                                    <p className={s.metricSub}>
                                        slope {data.slope > 0 ? '+' : ''}
                                        {data.slope}
                                    </p>
                                </div>
                                <div className={s.metricCard}>
                                    <p className={s.metricLabel}>예측 피크 기간</p>
                                    <p className={s.metricVal} style={{ color: '#a855f7' }}>
                                        {data.peak_period?.slice(0, 7) ?? '-'}
                                    </p>
                                    <p className={s.metricSub}>수요 최고점 예측</p>
                                </div>
                                <div className={s.metricCard}>
                                    <p className={s.metricLabel}>예측 신뢰도</p>
                                    <p className={s.metricVal} style={{ color: '#06b6d4' }}>
                                        {data.confidence}%
                                    </p>
                                    <p className={s.metricSub}>모델 정확도 추정</p>
                                </div>
                            </div>

                            {/* ── Forecast Chart ── */}
                            <div className={s.chartCard}>
                                <div className={s.chartHeader}>
                                    <div>
                                        <p className={s.cardTitle}>수요 예측 차트</p>
                                        <p className={s.cardSub}>실선: 실제 데이터 · 점선: 예측 · 밴드: 신뢰 구간</p>
                                    </div>
                                    <span className={s.ragBadge}>RAG 강화</span>
                                </div>
                                <ForecastChart history={data.history} forecast={data.forecast} />
                            </div>

                            {/* ── RAG Insight ── */}
                            {data.rag_insight && (
                                <div className={s.ragCard}>
                                    <div className={s.ragHeader}>
                                        <span className={s.ragIcon}>◈</span>
                                        <p className={s.ragTitle}>RAG 기반 재고 전략 제언</p>
                                    </div>
                                    <p className={s.ragText}>{data.rag_insight}</p>
                                </div>
                            )}

                            {/* ── Recommendation ── */}
                            <div className={s.recCard}>
                                <p className={s.recLabel}>기본 수요 전망</p>
                                <p className={s.recText}>{data.recommendation}</p>
                            </div>

                            {/* ── Forecast Table ── */}
                            <div className={s.tableCard}>
                                <p className={s.cardTitle}>
                                    {{ date: '일별', week: '주별', month: '월별' }[data.time_unit] ?? '기간별'} 예측값
                                </p>
                                <p className={s.cardSub}>예측 관심도 및 신뢰 구간</p>
                                <ForecastTable forecast={data.forecast} />
                            </div>
                        </>
                    )}

                    {!loading && data?.error && <div className={s.error}>{data.error}</div>}
                </div>

                {/* ── Sidebar ── */}
                <div className={s.sidebar}>
                    <div className={s.sideSection}>
                        <p className={s.sideLabel}>카테고리</p>
                        <div className={s.sideCats}>
                            {CATEGORIES.map((cat) => (
                                <button
                                    key={cat}
                                    className={`${s.sideCatBtn} ${category === cat ? s.sideCatActive : ''}`}
                                    onClick={() => setCategory(cat)}
                                >
                                    {cat}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className={s.sideSection}>
                        <p className={s.sideLabel}>예측 기간</p>
                        <div className={s.sidePeriods}>
                            {PERIODS.map((p) => (
                                <button
                                    key={p.value}
                                    className={`${s.sidePeriodBtn} ${period === p.value ? s.sidePeriodActive : ''}`}
                                    onClick={() => setPeriod(p.value)}
                                >
                                    {p.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className={s.sideInfo}>
                        <p className={s.sideInfoTitle}>데이터 소스</p>
                        <div className={s.sourceList}>
                            <span className={s.source}>네이버 DataLab</span>
                            <span className={s.source}>선형 회귀 모델</span>
                            <span className={s.source}>RAG (구매 패턴)</span>
                            <span className={s.source}>Groq LLM</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
