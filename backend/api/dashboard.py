"""
대시보드 로그 분석 및 모니터링 API
dashboard_logs 테이블과의 완전한 연동
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, and_, desc
import logging

from models.database_models import DashboardLog, User
from core.database import get_async_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard & Analytics"])

# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────

class DashboardLogResponse(BaseModel):
    """대시보드 로그 응답"""
    dashboard_log_id: int
    user_id: UUID
    timestamp: datetime
    log_type: Optional[str] = None
    log_data: Optional[str] = None
    using_time: Optional[datetime] = None

class DashboardLogCreate(BaseModel):
    """대시보드 로그 생성 요청"""
    user_id: UUID
    log_type: str = Field(..., max_length=32, description="로그 유형")
    log_data: Optional[str] = Field(None, description="로그 상세 데이터")
    using_time: Optional[datetime] = Field(None, description="앱 사용 시간")

class UserAnalytics(BaseModel):
    """사용자 분석 데이터"""
    user_id: UUID
    total_logs: int
    log_types: Dict[str, int]
    first_activity: Optional[datetime]
    last_activity: Optional[datetime]
    most_active_day: Optional[str]
    activity_summary: Dict[str, Any]

class SystemAnalytics(BaseModel):
    """시스템 전체 분석 데이터"""
    total_users: int
    total_logs: int
    active_users_today: int
    top_activities: List[Dict[str, Any]]
    error_rate: float
    system_health: str

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/logs", response_model=DashboardLogResponse)
async def create_dashboard_log(
    log_data: DashboardLogCreate,
    session: AsyncSession = Depends(get_async_db)
):
    """
    대시보드 로그 생성 - 시스템 활동 기록
    """
    try:
        # 사용자 존재 확인
        user_check = await session.execute(
            select(User.user_id).where(User.user_id == log_data.user_id)
        )
        if not user_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")
        
        # 로그 생성
        dashboard_log = DashboardLog(
            user_id=log_data.user_id,
            log_type=log_data.log_type,
            log_data=log_data.log_data,
            using_time=log_data.using_time
        )
        
        session.add(dashboard_log)
        await session.commit()
        await session.refresh(dashboard_log)
        
        return DashboardLogResponse.model_validate(dashboard_log, from_attributes=True)
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to create dashboard log: {e}")
        raise HTTPException(status_code=500, detail="Failed to create log")

@router.get("/logs/{user_id}", response_model=List[DashboardLogResponse])
async def get_user_logs(
    user_id: UUID,
    log_type: Optional[str] = Query(None, description="필터할 로그 유형"),
    limit: int = Query(50, ge=1, le=1000, description="조회할 로그 수"),
    offset: int = Query(0, ge=0, description="스킵할 로그 수"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자별 대시보드 로그 조회
    """
    try:
        query = select(DashboardLog).where(DashboardLog.user_id == user_id)
        
        if log_type:
            query = query.where(DashboardLog.log_type == log_type)
        
        query = query.order_by(desc(DashboardLog.timestamp)).limit(limit).offset(offset)
        
        result = await session.execute(query)
        logs = result.scalars().all()
        
        return [DashboardLogResponse.model_validate(log, from_attributes=True) for log in logs]
        
    except Exception as e:
        logger.error(f"Failed to get user logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")

@router.get("/analytics/user/{user_id}", response_model=UserAnalytics)
async def get_user_analytics(
    user_id: UUID,
    days: int = Query(30, ge=1, le=365, description="분석할 일수"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자별 활동 분석
    """
    try:
        start_date = datetime.now() - timedelta(days=days)
        
        # 기본 통계
        total_logs_result = await session.execute(
            select(func.count(DashboardLog.dashboard_log_id))
            .where(and_(
                DashboardLog.user_id == user_id,
                DashboardLog.timestamp >= start_date
            ))
        )
        total_logs = total_logs_result.scalar() or 0
        
        # 로그 타입별 통계
        log_types_query = text("""
            SELECT log_type, COUNT(*) as count
            FROM dashboard_logs
            WHERE user_id = :user_id AND timestamp >= :start_date
            GROUP BY log_type
            ORDER BY count DESC
        """)
        log_types_result = await session.execute(log_types_query, {
            "user_id": str(user_id),
            "start_date": start_date
        })
        log_types = {str(row[0]): int(row[1]) for row in log_types_result.fetchall()}
        
        # 첫 번째/마지막 활동
        first_activity_result = await session.execute(
            select(func.min(DashboardLog.timestamp))
            .where(DashboardLog.user_id == user_id)
        )
        first_activity = first_activity_result.scalar()
        
        last_activity_result = await session.execute(
            select(func.max(DashboardLog.timestamp))
            .where(DashboardLog.user_id == user_id)
        )
        last_activity = last_activity_result.scalar()
        
        # 가장 활발한 요일
        most_active_day_query = text("""
            SELECT EXTRACT(DOW FROM timestamp) as dow, COUNT(*) as count
            FROM dashboard_logs
            WHERE user_id = :user_id AND timestamp >= :start_date
            GROUP BY dow
            ORDER BY count DESC
            LIMIT 1
        """)
        most_active_day_result = await session.execute(most_active_day_query, {
            "user_id": str(user_id),
            "start_date": start_date
        })
        dow_row = most_active_day_result.fetchone()
        
        dow_names = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일']
        most_active_day = dow_names[int(dow_row.dow)] if dow_row else None
        
        # 활동 요약
        activity_summary = {
            "daily_average": total_logs / days if days > 0 else 0,
            "peak_activity_day": most_active_day,
            "primary_activity": max(log_types.keys(), key=lambda k: log_types[k]) if log_types else None,
            "activity_diversity": len(log_types)
        }
        
        return UserAnalytics(
            user_id=user_id,
            total_logs=total_logs,
            log_types=log_types,
            first_activity=first_activity,
            last_activity=last_activity,
            most_active_day=most_active_day,
            activity_summary=activity_summary
        )
        
    except Exception as e:
        logger.error(f"Failed to get user analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate analytics")

@router.get("/analytics/system", response_model=SystemAnalytics)
async def get_system_analytics(
    session: AsyncSession = Depends(get_async_db)
):
    """
    시스템 전체 분석 데이터
    """
    try:
        # 전체 사용자 수
        total_users_result = await session.execute(select(func.count(User.user_id)))
        total_users = total_users_result.scalar() or 0
        
        # 전체 로그 수
        total_logs_result = await session.execute(select(func.count(DashboardLog.dashboard_log_id)))
        total_logs = total_logs_result.scalar() or 0
        
        # 오늘 활성 사용자
        today = datetime.now().date()
        active_today_result = await session.execute(
            select(func.count(func.distinct(DashboardLog.user_id)))
            .where(func.date(DashboardLog.timestamp) == today)
        )
        active_users_today = active_today_result.scalar() or 0
        
        # 상위 활동들
        top_activities_query = text("""
            SELECT log_type, COUNT(*) as count, COUNT(DISTINCT user_id) as unique_users
            FROM dashboard_logs
            WHERE timestamp >= NOW() - INTERVAL '7 days'
            GROUP BY log_type
            ORDER BY count DESC
            LIMIT 10
        """)
        top_activities_result = await session.execute(top_activities_query)
        top_activities = [
            {
                "activity": row.log_type,
                "count": row.count,
                "unique_users": row.unique_users
            }
            for row in top_activities_result.fetchall()
        ]
        
        # 에러율 계산
        error_logs_result = await session.execute(
            select(func.count(DashboardLog.dashboard_log_id))
            .where(DashboardLog.log_type.like('%error%'))
        )
        error_logs = error_logs_result.scalar() or 0
        error_rate = (error_logs / total_logs * 100) if total_logs > 0 else 0
        
        # 시스템 건강도
        if error_rate < 1:
            system_health = "EXCELLENT"
        elif error_rate < 5:
            system_health = "GOOD"
        elif error_rate < 10:
            system_health = "WARNING"
        else:
            system_health = "CRITICAL"
        
        return SystemAnalytics(
            total_users=total_users,
            total_logs=total_logs,
            active_users_today=active_users_today,
            top_activities=top_activities,
            error_rate=round(error_rate, 2),
            system_health=system_health
        )
        
    except Exception as e:
        logger.error(f"Failed to get system analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate system analytics")

@router.delete("/logs/{user_id}")
async def cleanup_user_logs(
    user_id: UUID,
    days_to_keep: int = Query(90, ge=1, le=3650, description="보관할 일수"),
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자 로그 정리 - 오래된 로그 삭제
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        # 삭제할 로그 수 확인
        count_result = await session.execute(
            select(func.count(DashboardLog.dashboard_log_id))
            .where(and_(
                DashboardLog.user_id == user_id,
                DashboardLog.timestamp < cutoff_date
            ))
        )
        logs_to_delete = count_result.scalar() or 0
        
        if logs_to_delete == 0:
            return {
                "success": True,
                "message": "No logs to cleanup",
                "deleted_count": 0
            }
        
        # 로그 삭제
        delete_query = text("""
            DELETE FROM dashboard_logs 
            WHERE user_id = :user_id AND timestamp < :cutoff_date
        """)
        
        await session.execute(delete_query, {
            "user_id": str(user_id),
            "cutoff_date": cutoff_date
        })
        
        await session.commit()
        
        return {
            "success": True,
            "message": f"Successfully cleaned up old logs",
            "deleted_count": logs_to_delete,
            "cutoff_date": cutoff_date.isoformat()
        }
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to cleanup logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup logs")