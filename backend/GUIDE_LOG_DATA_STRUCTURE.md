# A:Eye 가이드 로그 데이터 구조 문서

## 📋 개요

본 문서는 **A:Eye (시각장애인 보조 시스템)**에서 생성되는 가이드 로그 데이터의 구조와 활용 방안을 정리합니다. 현재 시스템은 `dashboard_logs` 테이블을 통해 사용자의 모든 활동을 추적하고 있으며, 이 데이터는 시각장애인의 이동 패턴, 위험 상황, 학습 진도 등을 파악하는 핵심 정보원입니다.

## 🗃️ 데이터베이스 구조

### 핵심 테이블: `dashboard_logs`

```sql
CREATE TABLE dashboard_logs (
    dashboard_log_id  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          UUID REFERENCES users(user_id) ON DELETE CASCADE,
    timestamp        TIMESTAMP DEFAULT NOW(),
    log_type         VARCHAR(32),
    log_data         TEXT,
    using_time       TIMESTAMP
);
```

### 테이블 구조 설명

| 필드명 | 타입 | 설명 |
|--------|------|------|
| `dashboard_log_id` | INTEGER | 로그 고유 식별자 (자동 증가) |
| `user_id` | UUID | 사용자 식별자 (FK) |
| `timestamp` | TIMESTAMP | 로그 기록 시각 |
| `log_type` | VARCHAR(32) | 로그 유형 분류 |
| `log_data` | TEXT | 상세 로그 데이터 (JSON 형태) |
| `using_time` | TIMESTAMP | 앱 사용 시간 (특정 로그에서 사용) |

## 📊 현재 구현된 로그 타입별 데이터 구조

### 1. 위험 탐지 로그 (`threat_detected`)

**생성 위치**: `/api/objects.py:244-261`

**데이터 구조**:
```json
{
  "object_type": "person|car|bicycle|motorcycle|truck|bus|cat|dog|...",
  "confidence": 0.85,
  "distance_mm": 1500,
  "risk_level": 3,
  "box_coordinates": [x1, y1, x2, y2],
  "frame_width": 640,
  "frame_height": 480,
  "detection_source": "yolo_midas"
}
```

**활용 목적**:
- 사용자 주변 위험 상황 모니터링
- 위험 객체별 빈도 분석
- 특정 시간대/장소별 위험도 패턴 분석
- 보호자 알림 트리거 데이터

### 2. 보폭 측정 결과 (`measurement_result`)

**생성 위치**: `/api/measurement.py:815-823`

**데이터 구조** (문자열 형태):
```
"step_length: 72cm, duration: 15s, frames: 450, type: walking_measurement"
```

**파싱된 정보**:
- `step_length`: 측정된 보폭 길이 (cm)
- `duration`: 측정 세션 지속 시간 (초)
- `frames`: 처리된 프레임 수
- `type`: 측정 타입 (walking_measurement 등)

**활용 목적**:
- 사용자별 보폭 변화 추이 분석
- 측정 정확도 향상을 위한 데이터 수집
- 개인화된 보폭 모델 구축
- 걸음 패턴 학습 및 개선

### 3. 길찾기 요청 (`directions_request`)

**생성 위치**: `/api/maps.py:596-615`

**데이터 구조**:
```json
{
  "origin": {
    "lat": 37.5665,
    "lng": 126.9780,
    "address": "서울특별시 중구 세종대로 110"
  },
  "destination": {
    "lat": 37.5640,
    "lng": 126.9754,
    "address": "서울특별시 중구 명동길 26"
  },
  "mode": "walking",
  "api_provider": "mapbox",
  "distance_m": 850,
  "duration_seconds": 600,
  "status": "success"
}
```

### 4. 긴급 알림 (`EMERGENCY_ALERT`)

**생성 위치**: `/api/caregiver.py:221-226`

**데이터 구조** (문자열 형태):
```
"Emergency alert sent to 김보호자 (010-1234-5678): [긴급상황] A:Eye 사용자에게 도움이 필요합니다."
```

**파싱된 정보**:
- 보호자 이름
- 보호자 연락처
- 전송된 메시지 내용
- 전송 성공/실패 여부

**활용 목적**:
- 긴급 상황 대응 이력 관리
- 보호자 알림 시스템 효율성 분석
- 안전망 가동 빈도 모니터링

## 🎯 가이드 로그로 활용 가능한 핵심 데이터

### 1. 이동 및 내비게이션 가이드 로그

**현재 수집 데이터**:
- 출발지/목적지 좌표
- 이동 모드 (도보/차량)
- 경로 거리 및 소요 시간
- API 제공자 (Mapbox/NAVER)

**확장 가능한 로그 타입**:
```
- "route_started": 경로 안내 시작
- "route_completed": 목적지 도착
- "route_deviated": 경로 이탈 감지
- "waypoint_reached": 중간 지점 도착
- "route_recalculated": 경로 재계산
```

### 2. 안전 및 위험 감지 가이드 로그

**현재 수집 데이터**:
- 감지된 객체 타입 및 신뢰도
- 거리 정보 (mm 단위)
- 위험도 레벨 (1-5)
- 객체 위치 좌표

**확장 가능한 로그 타입**:
```
- "danger_warning_issued": 위험 경고 발령
- "safe_path_suggested": 안전 경로 제안
- "obstacle_cleared": 장애물 해제
- "collision_avoided": 충돌 회피 성공
```

### 3. 학습 및 적응 가이드 로그

**현재 수집 데이터**:
- 보폭 측정 결과
- 측정 세션 정보
- 프레임 처리 통계

**확장 가능한 로그 타입**:
```
- "step_calibration_completed": 보폭 보정 완료
- "walking_pattern_learned": 걸음 패턴 학습 완료
- "personal_model_updated": 개인 모델 업데이트
- "accuracy_improved": 측정 정확도 개선
```

### 4. 음성 상호작용 가이드 로그

**현재 구현된 음성 시스템**:
- Google Text-to-Speech API 기반 음성 합성
- 사용자별 음성 설정 (성별, 속도, 피치)
- 음성 명령 분석 및 의도 인식 시스템
- 컨텍스트 기반 우선순위 처리

#### 4.1 음성 명령 호출 빈도 분석 로그 (`voice_command_usage`)

**생성 위치**: `/services/speech_analyzer.py:101-146`

**데이터 구조**:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "command_category": "FOOTSTEP_MEASUREMENT|CAMERA|NAVIGATION|EMERGENCY_CALL|SETTINGS|HELP",
  "specific_command": "FOOTSTEP_MEASUREMENT_START",
  "recognized_text": "보폭 측정 시작",
  "confidence": 0.95,
  "context": "default",
  "success": true,
  "execution_time_ms": 350
}
```

**현재 지원되는 주요 명령어 카테고리**:
- **보폭 측정** (8개 명령): `FOOTSTEP_MEASUREMENT_START`, `FOOTSTEP_MEASUREMENT_COMPLETE`, `FOOTSTEP_STATUS_CHECK` 등
- **카메라** (6개 명령): 카메라, 사진, 촬영, 찍어, 보여, 카메라모드
- **길찾기** (7개 명령): 길찾기, 길, 가는법, 방향, 찾아, 네비, 길찾기모드
- **긴급호출** (5개 명령): 보호자, 긴급, 도움, 전화, 연락
- **설정** (6개 명령): 설정, 환경설정, 옵션, 보폭설정, 음성설정, 보호자설정
- **도움말** (5개 명령): 도움말, 도움, 헬프, 사용법, 명령어

#### 4.2 음성 명령 인식 로그 (`voice_command_recognized`)

**생성 위치**: `/services/speech_analyzer.py:101-146`

**데이터 구조**:
```json
{
  "recognized_text": "보폭 측정 시작",
  "intent": "FOOTSTEP_MEASUREMENT_START",
  "confidence": 0.95,
  "context": "default",
  "entities": {
    "measurement_type": "kalman_filter",
    "category": "footstep_measurement",
    "action": "start_measurement",
    "precision_mode": "true"
  },
  "analysis_method": "keyword_matching",
  "processing_time_ms": 12
}
```

#### 4.3 미지원 명령어 및 개선 필요 로그 (`unsupported_command_analysis`)

**데이터 구조**:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "unrecognized_text": "화장실 어디야",
  "attempted_intent": "FIND_POI",
  "confidence": 0.3,
  "context": "default",
  "suggested_category": "LOCATION_INQUIRY",
  "frequency_count": 15,
  "similar_requests": ["화장실 찾아", "화장실 위치", "가까운 화장실"]
}
```

**추가 필요한 명령어 카테고리 (사용자 요청 빈도 기반)**:
- **실내 내비게이션**: "엘리베이터 어디", "화장실 어디", "출구 어디"
- **상황 확인**: "지금 어디야", "여기가 어디", "몇 층이야"  

#### 4.4 보폭 측정 음성 안내 로그 (`footstep_voice_guide`)

**현재 지원되는 보폭 관련 음성 명령들**:

**시작 안내**:
- "보폭 측정 시작", "보폭측정시작", "측정 시작"
- "정밀 측정 시작", "실시간 측정 시작", "칼만 측정"

**진행 안내**:
- "측정 완료", "측정완료", "완료", "끝"
- "측정 취소", "측정취소", "취소", "중단"

**상태 확인**:
- "보폭 상태", "현재 보폭", "측정 상태", "상태"

**데이터 구조**:
```json
{
  "measurement_phase": "start|progress|complete|cancel|status_check",
  "voice_command": "보폭 측정 시작",
  "recognized_intent": "FOOTSTEP_MEASUREMENT_START",
  "confidence": 0.95,
  "context_priority": "measurement_active",
  "kalman_filter_mode": true,
  "precision_mode_requested": true,
  "response_message": "보폭 측정을 시작합니다. 평소처럼 자연스럽게 걸어주세요."
}
```

## 🔍 분석 및 활용 방안

### 1. 위험도별 안전 상황 분석

```sql
SELECT 
    json_extract(log_data, '$.risk_level') as risk_level,
    json_extract(log_data, '$.object_type') as object_type,
    COUNT(*) as detection_count,
    AVG(json_extract(log_data, '$.distance_mm')) as avg_distance
FROM dashboard_logs 
WHERE log_type = 'threat_detected'
GROUP BY risk_level, object_type
ORDER BY risk_level DESC, detection_count DESC;
```

### 2. 보폭 측정 정확도 추이

```sql
SELECT 
    DATE(timestamp) as measurement_date,
    REGEXP_SUBSTR(log_data, 'step_length: (\d+)', 1, 1, '', 1) as step_length,
    REGEXP_SUBSTR(log_data, 'duration: (\d+)', 1, 1, '', 1) as duration
FROM dashboard_logs 
WHERE log_type = 'measurement_result'
ORDER BY timestamp;
```

### 3. 음성 명령 호출 빈도 및 개선 분석

#### 3.1 음성 명령 카테고리별 사용 빈도 분석
```sql
-- 가장 많이 사용되는 음성 명령 카테고리 Top 10
SELECT 
    json_extract(log_data, '$.command_category') as category,
    json_extract(log_data, '$.specific_command') as command,
    COUNT(*) as usage_count,
    AVG(json_extract(log_data, '$.confidence')) as avg_confidence,
    COUNT(CASE WHEN json_extract(log_data, '$.success') = 'true' THEN 1 END) as success_count,
    ROUND(COUNT(CASE WHEN json_extract(log_data, '$.success') = 'true' THEN 1 END) * 100.0 / COUNT(*), 2) as success_rate
FROM dashboard_logs 
WHERE log_type = 'voice_command_usage'
GROUP BY category, command
ORDER BY usage_count DESC
LIMIT 10;
```

#### 3.2 미지원 명령어 요청 빈도 분석
```sql
-- 사용자들이 자주 요청하지만 지원되지 않는 명령어들
SELECT 
    json_extract(log_data, '$.unrecognized_text') as requested_command,
    json_extract(log_data, '$.suggested_category') as suggested_category,
    SUM(json_extract(log_data, '$.frequency_count')) as total_requests,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(json_extract(log_data, '$.confidence')) as avg_confidence
FROM dashboard_logs 
WHERE log_type = 'unsupported_command_analysis'
    AND json_extract(log_data, '$.frequency_count') >= 5  -- 5회 이상 요청된 것들만
GROUP BY requested_command, suggested_category
ORDER BY total_requests DESC
LIMIT 20;
```

#### 3.3 사용자별 음성 명령 패턴 분석
```sql
-- 사용자별 주요 사용 명령어와 성공률
SELECT 
    user_id,
    json_extract(log_data, '$.command_category') as preferred_category,
    COUNT(*) as usage_frequency,
    ROUND(AVG(json_extract(log_data, '$.confidence')), 3) as avg_confidence,
    ROUND(AVG(json_extract(log_data, '$.execution_time_ms')), 0) as avg_execution_time_ms
FROM dashboard_logs 
WHERE log_type = 'voice_command_usage'
    AND json_extract(log_data, '$.success') = 'true'
GROUP BY user_id, preferred_category
HAVING usage_frequency >= 10  -- 10회 이상 사용한 명령어들만
ORDER BY user_id, usage_frequency DESC;
```

#### 3.4 시간대별 음성 명령 사용 패턴
```sql
-- 시간대별 음성 명령 사용 패턴으로 사용자 행동 분석
SELECT 
    EXTRACT(HOUR FROM timestamp) as hour_of_day,
    json_extract(log_data, '$.command_category') as category,
    COUNT(*) as command_count,
    ROUND(AVG(json_extract(log_data, '$.confidence')), 3) as avg_confidence
FROM dashboard_logs 
WHERE log_type = 'voice_command_usage'
GROUP BY EXTRACT(HOUR FROM timestamp), category
HAVING command_count >= 5
ORDER BY hour_of_day, command_count DESC;
```

#### 3.5 명령어 개선 우선순위 분석
```sql
-- 개선이 필요한 명령어들의 우선순위 (낮은 신뢰도 + 높은 사용빈도)
WITH command_stats AS (
    SELECT 
        json_extract(log_data, '$.specific_command') as command,
        COUNT(*) as usage_count,
        AVG(json_extract(log_data, '$.confidence')) as avg_confidence,
        COUNT(CASE WHEN json_extract(log_data, '$.success') = 'false' THEN 1 END) as failure_count
    FROM dashboard_logs 
    WHERE log_type = 'voice_command_usage'
    GROUP BY command
    HAVING usage_count >= 10
)
SELECT 
    command,
    usage_count,
    ROUND(avg_confidence, 3) as avg_confidence,
    failure_count,
    ROUND(failure_count * 100.0 / usage_count, 2) as failure_rate,
    -- 우선순위 점수: 사용빈도 높고 성공률 낮을수록 높은 점수
    ROUND(usage_count * (1 - avg_confidence) * 100, 0) as improvement_priority_score
FROM command_stats
WHERE avg_confidence < 0.8 OR failure_count > 0
ORDER BY improvement_priority_score DESC
LIMIT 15;
```

## 📈 대시보드 시각화 제안

### 1. 실시간 안전 모니터링 대시보드

- **위험도별 실시간 알림**: 레벨 3 이상 즉시 표시
- **시간대별 위험 분포**: 히트맵 형태로 표시
- **객체 타입별 감지 빈도**: 원형 차트
- **평균 거리별 위험도**: 산점도 차트

### 2. 개인화 학습 진도 대시보드

- **보폭 측정 정확도 추이**: 선형 차트
- **측정 세션 성공률**: 진행률 바
- **일일/주간 측정 횟수**: 막대 차트
- **개선 추천 사항**: 텍스트 위젯

### 3. 음성 명령 사용 현황 대시보드

- **명령어 사용 빈도 Top 10**: 막대 차트로 가장 많이 사용되는 명령어
- **카테고리별 성공률**: 도넛 차트로 명령어 카테고리별 성공/실패 비율
- **시간대별 사용 패턴**: 히트맵으로 시간대별 음성 명령 사용 분포
- **사용자별 선호 명령어**: 개인화 분석을 위한 사용자별 주요 명령어

### 4. 음성 인식 개선 우선순위 대시보드

- **개선 필요 명령어 리스트**: 낮은 신뢰도 + 높은 사용빈도 명령어들
- **미지원 요청 Top 20**: 사용자들이 자주 요청하지만 지원되지 않는 명령어들
- **명령어 추가 제안**: 빈도 기반 신규 명령어 카테고리 제안
- **인식률 개선 트렌드**: 월별/주별 음성 인식 정확도 추이

## 🚀 확장 계획

### Phase 1: 기존 로그 구조 최적화
- JSON 스키마 검증 추가
- 인덱스 최적화
- 로그 압축 및 아카이빙

### Phase 2: 새로운 로그 타입 추가
- 음성 상호작용 로그
- 학습 진도 로그
- 사용자 피드백 로그
- 시스템 성능 로그

### Phase 3: 실시간 분석 시스템
- 스트리밍 데이터 처리
- 실시간 알림 시스템
- 예측 분석 모델
- 자동화된 인사이트 생성

## 🔧 기술적 고려사항

### 데이터 저장 최적화
- JSON 컬럼 타입 활용 (PostgreSQL)
- 압축된 로그 저장 방식
- 파티셔닝을 통한 성능 개선

### 개인정보 보호
- 민감 정보 익명화
- 데이터 암호화
- 접근 권한 관리
- GDPR 준수 방안

### 성능 최적화
- 배치 처리를 통한 로그 저장
- 비동기 로그 처리
- 캐시를 활용한 조회 성능 개선
- 로그 레벨별 저장 전략

---

이 문서는 A:Eye 시스템의 현재 상태를 기반으로 작성되었으며, 시스템 발전에 따라 지속적으로 업데이트될 예정입니다.

**마지막 업데이트**: 2025-09-07  
**문서 버전**: v1.0  