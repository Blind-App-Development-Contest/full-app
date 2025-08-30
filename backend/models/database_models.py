"""
SQLAlchemy ORM models based on appdb.sql schema
AI 시각장애인 보조 시스템 데이터베이스 모델
"""

from sqlalchemy import Column, Integer, String, TIMESTAMP, Text, ForeignKey, CHAR
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

Base = declarative_base()


class User(Base):
    """사용자 기기 단위 식별 및 관리"""
    __tablename__ = 'users'
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    user_name = Column(String(32))
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    
    # Relationships
    voice = relationship("Voice", back_populates="user", uselist=False)
    caregiver = relationship("Caregiver", back_populates="user", uselist=False)
    footstep = relationship("Footstep", back_populates="user", uselist=False)
    user_setting = relationship("UserSetting", back_populates="user", uselist=False)
    dashboard_logs = relationship("DashboardLog", back_populates="user")


class Voice(Base):
    """음성 설정 (1:1 with users)"""
    __tablename__ = 'voice'
    
    voice_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), unique=True)
    gender = Column(CHAR(1))  # M/F
    speed = Column(Integer)
    voice_created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    voice_updated_at = Column(TIMESTAMP, nullable=False, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="voice")
    user_setting = relationship("UserSetting", back_populates="voice", uselist=False)


class Caregiver(Base):
    """보호자 정보 (1:1 with users)"""
    __tablename__ = 'caregivers'
    
    caregiver_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, unique=True)
    caregivers_name = Column(String(32))
    phone_number = Column(String(32))
    caregiver_created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    caregiver_updated_at = Column(TIMESTAMP, nullable=False, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="caregiver")
    user_setting = relationship("UserSetting", back_populates="caregiver", uselist=False)


class Footstep(Base):
    """보폭 정보 (1:1 with users)"""
    __tablename__ = 'footstep'
    
    step_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), unique=True)
    step_length = Column(Integer, nullable=False)
    step_created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    step_updated_at = Column(TIMESTAMP, nullable=False, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="footstep")
    user_setting = relationship("UserSetting", back_populates="footstep", uselist=False)


class UserSetting(Base):
    """사용자 설정 통합 관리 (1:1 with users; references others)"""
    __tablename__ = 'user_settings'
    
    setting_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, unique=True)
    caregiver_id = Column(Integer, ForeignKey('caregivers.caregiver_id', ondelete='SET NULL'), unique=True)
    step_id = Column(Integer, ForeignKey('footstep.step_id', ondelete='SET NULL'), unique=True)
    voice_id = Column(Integer, ForeignKey('voice.voice_id', ondelete='SET NULL'), unique=True)
    setting_created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    setting_updated_at = Column(TIMESTAMP, nullable=False, default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="user_setting")
    caregiver = relationship("Caregiver", back_populates="user_setting")
    footstep = relationship("Footstep", back_populates="user_setting")
    voice = relationship("Voice", back_populates="user_setting")


class DashboardLog(Base):
    """시스템 모니터링 및 운영 대시보드용 데이터 (N:1 with users)"""
    __tablename__ = 'dashboard_logs'
    
    dashboard_log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, default=func.now())
    log_type = Column(String(32))
    log_data = Column(Text)
    using_time = Column(TIMESTAMP)
    
    # Relationships
    user = relationship("User", back_populates="dashboard_logs")