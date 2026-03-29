import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from pydantic import BaseModel

# --- НАСТРОЙКИ БД ---
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# bcrypt — стандарт, но мы добавим ограничение в 72 символа
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Integer, default=0)

class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

class UserAuth(BaseModel):
    username: str
    password: str

app = FastAPI()

# --- ЛОГИКА АВТОРИЗАЦИИ ---

@app.post("/register")
async def register(user: UserAuth):
    db = SessionLocal()
    try:
        # ПРОВЕРКА: Обрезаем пароль до безопасной длины для bcrypt
        safe_pass = user.password[:71] 
        
        exists = db.query(DBUser).filter(DBUser.username == user.username).first()
        if exists:
            return JSONResponse(status_code=400, content={"detail": "Пользователь уже существует"})
        
        new_user = DBUser(
            username=user.username,
            hashed_password=pwd_context.hash(safe_pass),
            is_admin=1 if user.username == "notevil" else 0
        )
        db.add(new_user)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Ошибка БД: {str(e)}"})
    finally:
        db.close()

@app.post("/login")
async def login(user: UserAuth):
    db = SessionLocal()
    try:
        safe_pass = user.password[:71]
        db_user = db.query(DBUser).filter(DBUser.username == user.username).first()
        
        if not db_user or not pwd_context.verify(safe_pass, db_user.hashed_password):
            return JSONResponse(status_code=400, content={"detail": "Неверный логин или пароль"})
        
        return {"status": "ok"}
    finally:
        db.close()

# --- ОСТАЛЬНОЙ КОД (История и WS) ---

@app.get("/history")
async def get_history():
    db = SessionLocal()
    try:
        msgs = db.query(DBMessage).order_by(DBMessage.timestamp.asc()).all()
        return [{"sender": m.sender, "text": m.text} for m in msgs]
    finally:
        db.close()

@app.get("/")
async def get_index(): return FileResponse("index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg_json = json.loads(data)
            db = SessionLocal()
            db.add(DBMessage(sender=msg_json['sender'], text=msg_json['text']))
            db.commit()
            db.close()
            # Рассылка всем (упрощенно для стабильности)
            await websocket.send_text(data) 
    except: pass
