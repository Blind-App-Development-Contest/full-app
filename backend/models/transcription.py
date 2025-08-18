from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from core.database import Base

class Transcription(Base):
    __tablename__ = "transcriptions"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)