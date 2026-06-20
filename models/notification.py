"""Notification model"""

from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid

class Notification(db.Model):
    """Notification model"""
    __tablename__ = 'notifications'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    
    type = db.Column(db.String(50), nullable=False)  # TRADE, ALERT, ERROR, INFO
    title = db.Column(db.String(255))
    message = db.Column(db.Text)
    
    is_read = db.Column(db.Boolean, default=False)
    
    channels = db.Column(db.JSON, default=[])  # ['email', 'telegram', 'discord']
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat(),
        }
