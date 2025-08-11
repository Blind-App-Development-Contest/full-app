
-- AI 시각장애인 보조 시스템 데이터베이스 (PostgreSQL)
-- Generated: 2025-08-11
-- Note: Table/column names normalized to snake_case for PostgreSQL friendliness.

-- =========================
-- Drop tables if exist (dev only)
-- =========================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_logs') THEN
        DROP TABLE dashboard_logs CASCADE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_settings') THEN
        DROP TABLE user_settings CASCADE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'footstep') THEN
        DROP TABLE footstep CASCADE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'caregivers') THEN
        DROP TABLE caregivers CASCADE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'voice') THEN
        DROP TABLE voice CASCADE;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        DROP TABLE users CASCADE;
    END IF;
END$$;

-- =========================
-- Users
-- =========================
CREATE TABLE users (
    user_id      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_name    VARCHAR(32),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE users IS '사용자 기기 단위 식별 및 관리';
COMMENT ON COLUMN users.user_id IS 'APP UUID';

-- =========================
-- Voice (1:1 with users)
-- =========================
CREATE TABLE voice (
    voice_id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id            INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    gender             CHAR(1), -- M/F
    voice_created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    voice_updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================
-- Caregivers (1:1 with users)
-- =========================
CREATE TABLE caregivers (
    caregiver_id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    caregivers_name        VARCHAR(32),
    phone_number           VARCHAR(32),
    caregiver_created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    caregiver_updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================
-- Footstep (1:1 with users)
-- =========================
CREATE TABLE footstep (
    step_id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    step_length      INTEGER NOT NULL,
    step_created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    step_updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================
-- User Settings (1:1 with users; references others)
-- =========================
CREATE TABLE user_settings (
    setting_id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    caregiver_id         INTEGER UNIQUE REFERENCES caregivers(caregiver_id) ON DELETE SET NULL,
    step_id              INTEGER UNIQUE REFERENCES footstep(step_id) ON DELETE SET NULL,
    voice_id             INTEGER UNIQUE REFERENCES voice(voice_id) ON DELETE SET NULL,
    setting_created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    setting_updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================
-- Dashboard Logs (N:1 with users)
-- =========================
CREATE TABLE dashboard_logs (
    dashboard_log_id  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    timestamp         TIMESTAMP NOT NULL DEFAULT NOW(),
    log_type          VARCHAR(32),
    log_data          TEXT,
    using_time        TIMESTAMP
);
COMMENT ON TABLE dashboard_logs IS '시스템 모니터링 및 운영 대시보드용 데이터';
COMMENT ON COLUMN dashboard_logs.dashboard_log_id IS '대시보드 로그 고유 번호';
COMMENT ON COLUMN dashboard_logs.user_id IS '로그 대상 사용자';
COMMENT ON COLUMN dashboard_logs.timestamp IS '로그 기록 시각';
COMMENT ON COLUMN dashboard_logs.log_type IS '로그 유형 분류';
COMMENT ON COLUMN dashboard_logs.log_data IS '상세 로그 데이터 내용';
COMMENT ON COLUMN dashboard_logs.using_time IS '앱 사용 시간';

-- Helpful index for logs by user/time
CREATE INDEX idx_dashboard_logs_user_time ON dashboard_logs(user_id, timestamp);

-- =========================
-- Updated-at triggers (optional but useful)
-- =========================
CREATE OR REPLACE FUNCTION set_voice_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.voice_updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_voice_updated_at
BEFORE UPDATE ON voice
FOR EACH ROW EXECUTE PROCEDURE set_voice_updated_at();

CREATE OR REPLACE FUNCTION set_caregiver_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.caregiver_updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_caregiver_updated_at
BEFORE UPDATE ON caregivers
FOR EACH ROW EXECUTE PROCEDURE set_caregiver_updated_at();

CREATE OR REPLACE FUNCTION set_step_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.step_updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_step_updated_at
BEFORE UPDATE ON footstep
FOR EACH ROW EXECUTE PROCEDURE set_step_updated_at();

CREATE OR REPLACE FUNCTION set_setting_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.setting_updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_setting_updated_at
BEFORE UPDATE ON user_settings
FOR EACH ROW EXECUTE PROCEDURE set_setting_updated_at();
