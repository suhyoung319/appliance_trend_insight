# Appliance Trend Insight DB 명세

이 문서는 현재 프로젝트가 사용하는 MySQL 데이터베이스
`appliance_trend_insight`의 실제 스키마와 코드 사용처를 정리한 문서다.

전체 DB와 테이블을 새로 생성하는 SQL은
[`backend/study/mysql_setup.sql`](backend/study/mysql_setup.sql)에 있다.

MySQL 명령줄에서 프로젝트 루트를 기준으로 실행한다.

```powershell
mysql -u root -p < backend/study/mysql_setup.sql
```

PowerShell에서 `<` 입력 리디렉션이 동작하지 않으면 다음 명령을 사용한다.

```powershell
Get-Content backend/study/mysql_setup.sql -Raw |
  mysql -u root -p
```

실행 후 `backend/.env`의 DB 설정을 확인한다.

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인의_MYSQL_비밀번호
DB_NAME=appliance_trend_insight
```

## 1. 테이블 요약

| 테이블 | 역할 | 주요 담당 기능 |
|---|---|---|
| `users` | 로그인 계정과 권한 관리 | 인증, 관리자 |
| `user_b2c_profiles` | 일반 사용자 프로필 | 회원가입, 마이페이지 |
| `user_b2b_profiles` | 사업자 프로필 | B2B 가입, 관리자 승인 |
| `price_alert` | 사용자별 목표 가격 알림 | 상품 리포트, 마이페이지 |
| `integrated_market_data` | 시장 분석 데이터 저장 | 트렌드 분석 |
| `ai_reports` | 시장 데이터 기반 AI 리포트 저장 | AI 분석 |
| `price_history` | 카테고리별 일간 가격 이력 | B2B 가격 분석 |
| `product_price_history` | 개별 상품별 일간 가격 이력 | 상품 가격 추적 |

## 2. 테이블 관계

```text
users
 ├─ user_b2c_profiles       1:1
 ├─ user_b2b_profiles       1:1
 └─ price_alert             1:N

integrated_market_data
 └─ ai_reports              1:N

price_history               독립적인 카테고리 가격 스냅샷
product_price_history       독립적인 상품 가격 스냅샷
```

실제 DB에는 다음 외래 키가 설정되어 있다.

| 자식 테이블 | 컬럼 | 부모 테이블 |
|---|---|---|
| `user_b2c_profiles` | `user_id` | `users.user_id` |
| `user_b2b_profiles` | `user_id` | `users.user_id` |
| `price_alert` | `user_id` | `users.user_id` |
| `ai_reports` | `data_id` | `integrated_market_data.data_id` |

## 3. 계정 및 사용자

### `users`

로그인 계정, 회원 유형, 승인 상태와 권한을 저장한다.

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
|---|---|---:|---|---|
| `user_id` | BIGINT | 불가 | 자동 증가 | PK |
| `email` | VARCHAR(255) | 불가 | 없음 | 로그인 이메일, UNIQUE |
| `password_hash` | VARCHAR(255) | 불가 | 없음 | bcrypt 비밀번호 해시 |
| `user_type` | ENUM(`b2c`, `b2b`) | 불가 | `b2c` | 회원 유형 |
| `status` | ENUM(`pending`, `active`, `rejected`) | 불가 | `active` | B2B 가입 승인 상태 |
| `is_active` | TINYINT(1) | 가능 | `1` | 계정 활성 여부 |
| `created_at` | TIMESTAMP | 가능 | 현재 시각 | 가입 일시 |
| `role` | VARCHAR(20) | 불가 | `user` | `user` 또는 `admin` |

사용 API:

- `POST /api/auth/signup/b2c`
- `POST /api/auth/signup/b2b`
- `POST /api/auth/login`
- `GET /api/admin/b2b-users`
- `POST /api/admin/users/{user_id}/approve`
- `POST /api/admin/users/{user_id}/reject`
- `GET /api/user/me`

### `user_b2c_profiles`

일반 소비자의 추가 정보를 저장한다.

| 컬럼 | 타입 | NULL | 키 | 설명 |
|---|---|---:|---|---|
| `profile_id` | BIGINT | 불가 | PK, 자동 증가 | 프로필 번호 |
| `user_id` | BIGINT | 불가 | FK, UNIQUE | `users.user_id` |
| `nickname` | VARCHAR(100) | 가능 |  | 닉네임 |

### `user_b2b_profiles`

사업자 계정의 회사 정보를 저장한다.

| 컬럼 | 타입 | NULL | 키 | 설명 |
|---|---|---:|---|---|
| `profile_id` | BIGINT | 불가 | PK, 자동 증가 | 프로필 번호 |
| `user_id` | BIGINT | 불가 | FK, UNIQUE | `users.user_id` |
| `company_name` | VARCHAR(255) | 불가 |  | 회사명 |
| `business_type` | VARCHAR(100) | 가능 |  | 업종 |
| `contact_phone` | VARCHAR(50) | 가능 |  | 담당자 연락처 |

## 4. 가격 알림

### `price_alert`

사용자가 상품별 목표 가격을 설정한 정보를 저장한다.

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
|---|---|---:|---|---|
| `alert_id` | BIGINT | 불가 | 자동 증가 | PK |
| `user_id` | BIGINT | 불가 | 없음 | `users.user_id` FK |
| `product_name` | VARCHAR(255) | 불가 | 없음 | 감시 대상 상품명 |
| `target_price` | DECIMAL(12,2) | 불가 | 없음 | 목표 가격 |
| `current_price` | DECIMAL(12,2) | 가능 | `0.00` | 등록 당시 현재가 |
| `product_url` | TEXT | 가능 | NULL | 상품 링크 |
| `alert_type` | ENUM(`below`, `above`) | 불가 | `below` | 목표가 이하 또는 이상 조건 |
| `is_active` | TINYINT(1) | 가능 | `1` | 알림 활성 여부 |
| `triggered_at` | TIMESTAMP | 가능 | NULL | 알림 발생 시각 |
| `created_at` | TIMESTAMP | 가능 | 현재 시각 | 등록 시각 |

사용 API:

- `GET /api/user/alerts`
- `POST /api/user/alerts`
- `DELETE /api/user/alerts/{alert_id}`

삭제 API는 행을 실제 삭제하지 않고 `is_active = 0`으로 변경한다.

## 5. 시장 및 AI 분석

### `integrated_market_data`

날짜, 카테고리, 브랜드, 상품을 기준으로 시장 분석 결과를 저장한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `data_id` | BIGINT, PK, AUTO_INCREMENT | 데이터 번호 |
| `analysis_date` | DATE | 분석 기준일 |
| `category_name` | VARCHAR(100) | 제품 카테고리 |
| `brand_name` | VARCHAR(100) | 브랜드명 |
| `product_name` | VARCHAR(255) | 상품명 |
| `trend_type` | ENUM(`current`, `future`, `potential`) | 트렌드 유형 |
| `data_sources` | JSON | 데이터 출처 |
| `current_price` | DECIMAL(12,2) | 현재가 또는 평균가 |
| `market_rank` | INT | 시장 순위 |
| `product_url` | TEXT | 상품 링크 |
| `search_volume_ratio` | DECIMAL(5,2) | 검색량 지수 |
| `search_growth_rate` | DECIMAL(6,2) | 검색량 증감률 |
| `demographics_json` | JSON | 성별·연령별 관심도 |
| `related_keywords` | JSON | 연관 검색어 |
| `total_review_count` | INT | 리뷰 수 |
| `average_rating` | DECIMAL(3,2) | 평균 평점 |
| `sentiment_positive_ratio` | DECIMAL(5,2) | 긍정 비율 |
| `sentiment_neutral_ratio` | DECIMAL(5,2) | 중립 비율 |
| `sentiment_negative_ratio` | DECIMAL(5,2) | 부정 비율 |
| `consumer_feedback_json` | JSON | 소비자 피드백 요약 |
| `news_mention_count` | INT | 뉴스 언급 수 |
| `industry_issues_json` | JSON | 산업 이슈 |
| `created_at` | TIMESTAMP | 최초 저장 시각 |
| `updated_at` | TIMESTAMP | 마지막 갱신 시각 |

주요 제약 및 인덱스:

```text
UNIQUE (analysis_date, category_name, brand_name, product_name)
INDEX (category_name, analysis_date)
INDEX (brand_name, analysis_date)
INDEX (trend_type)
```

### `ai_reports`

`integrated_market_data`를 기반으로 생성한 AI 리포트를 저장한다.

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---:|---|
| `report_id` | BIGINT | 불가 | PK, 자동 증가 |
| `data_id` | BIGINT | 불가 | `integrated_market_data.data_id` FK |
| `report_type` | ENUM(`b2c`, `b2b`) | 불가 | 리포트 대상 |
| `content` | TEXT | 불가 | 생성된 리포트 내용 |
| `model_used` | VARCHAR(100) | 가능 | 사용한 AI 모델 |
| `created_at` | TIMESTAMP | 가능 | 생성 시각 |

현재 `save_ai_report()` 저장 함수는 존재하지만 주요 API에서는 아직 적극적으로
사용하지 않는다.

## 6. 가격 이력

### `price_history`

카테고리 단위의 날짜별 가격 통계를 저장한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | INT, PK, AUTO_INCREMENT | 행 번호 |
| `category` | VARCHAR(50) | 카테고리 |
| `snapshot_date` | DATE | 수집 날짜 |
| `avg_price` | INT | 평균 가격 |
| `min_price` | INT | 최저 가격 |
| `max_price` | INT | 최고 가격 |
| `median_price` | INT | 중앙값 |
| `total_products` | INT | 수집 상품 수 |
| `brand_data` | JSON | 브랜드별 가격 통계 |
| `created_at` | TIMESTAMP | 저장 시각 |

`category + snapshot_date` 조합은 UNIQUE다.

주요 사용 API:

- `GET /api/price-position`
- `GET /api/b2b/price`

### `product_price_history`

개별 상품의 날짜·시간 슬롯별 가격과 판매처 정보를 저장한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | INT, PK, AUTO_INCREMENT | 행 번호 |
| `product_key` | VARCHAR(200) | 상품 식별 키 (네이버 `productId` 또는 카테고리 소문자) |
| `product_name` | VARCHAR(500) | 상품명 |
| `model_number` | VARCHAR(100) | 추출한 모델 번호 |
| `min_price` | INT | 최저 가격 |
| `max_price` | INT | 최고 가격 |
| `avg_price` | INT | 평균 가격 |
| `snapshot_date` | DATE | 수집 날짜 |
| `snapshot_hour` | TINYINT | 수집 시간 슬롯 (0 / 6 / 12 / 18) |
| `mall_data` | JSON | 판매처별 가격 정보 |
| `created_at` | TIMESTAMP | 저장 시각 |

`product_key + snapshot_date + snapshot_hour` 조합은 UNIQUE다.

**수집 주기**: 백엔드 크론잡이 6시간마다(0시·6시·12시·18시 UTC) 실행되어
카테고리 15개 및 최근 7일 내 사용자가 조회한 특정 제품(productId 기반)의 가격을 갱신한다.
같은 날 같은 슬롯에 재실행되면 기존 행을 최신 가격으로 덮어쓴다(`ON DUPLICATE KEY UPDATE`).

차트 조회 시에는 `snapshot_date`별 `MIN(min_price)`로 집계해 일별 최저가를 표시한다.

주요 사용 API:

- `GET /api/timing` — 구매 타이밍 분석 (90일 가격 이력 조회 및 오늘 스냅샷 저장)
- `GET /api/b2b/product-price`
- `GET /api/b2b/product-analysis`

## 7. 생성 및 변경 주의사항

- 백엔드 시작 시 `price_history`, `product_price_history` 테이블은 자동 생성된다.
- 백엔드 시작 시 `users.status`가 없으면 자동 추가된다.
- 백엔드 시작 시 `product_price_history.snapshot_hour`가 없으면 자동 추가되고 UNIQUE KEY가 `(product_key, snapshot_date)` → `(product_key, snapshot_date, snapshot_hour)`로 교체된다.
- 나머지 기본 테이블은 DB에 미리 생성되어 있어야 한다.
- 테이블 구조를 변경하면 `backend/app/database.py`의 SQL과 관련 API도 함께 확인한다.
- 팀 작업에서는 스키마 변경 SQL을 별도 파일로 남기고 모든 팀원이 같은 순서로 적용한다.
- `.env`의 DB 접속 정보와 비밀번호는 Git에 공유하지 않는다.

## 8. 기능별 DB 담당 범위 예시

| 기능 담당 | 관련 테이블 |
|---|---|
| 제품 및 가격 분석 | `price_history`, `product_price_history` |
| 사용자 맞춤 서비스 | `users`, `user_b2c_profiles`, `price_alert` |
| 트렌드 및 B2B | `integrated_market_data`, `ai_reports`, `user_b2b_profiles` |
