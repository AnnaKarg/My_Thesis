from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)

    current_lesson_id = Column(Integer, default=1) # Σε ποιο μάθημα είναι (1-6)

class ChatHistory(Base):
    __tablename__ = "chat_histories"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String) 
    content = Column(Text) 
    
    user = relationship("User", back_populates="messages")

User.messages = relationship("ChatHistory", order_by=ChatHistory.id, back_populates="user")