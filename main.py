import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext

# Настройки Базы Данных (Railway автоматически дает DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Настройка безопасности (хэширование паролей)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- МОДЕЛИ БАЗЫ ДАННЫХ ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Integer, default=0) # 1 для тебя, 0 для остальных

class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

app = FastAPI()

# Менеджер подключений
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- ЭНДПОИНТЫ ---

@app.get("/")
async def get_index():
    return FileResponse("index.html")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("manifest.json")

# Простая регистрация (логика Algo 2.0)
@app.post("/register")
async def register(data: dict):
    db = SessionLocal()
    user = db.query(User).filter(User.username == data['username']).first()
    if user:
        db.close()
        raise HTTPException(status_code=400, detail="User exists")
    
    new_user = User(
        username=data['username'], 
        hashed_password=pwd_context.hash(data['password']),
        is_admin=1 if data['username'] == "notevil" else 0 # Делаем тебя админом автоматически
    )
    db.add(new_user)
    db.commit()
    db.close()
    return {"status": "ok"}

@app.post("/login")
async def login(data: dict):
    db = SessionLocal()
    user = db.query(User).filter(User.username == data['username']).first()
    if not user or not pwd_context.verify(data['password'], user.hashed_password):
        db.close()
        raise HTTPException(status_code=400, detail="Wrong login/pass")
    db.close()
    return {"status": "ok"}

# Получение истории сообщений
@app.get("/history")
async def get_history():
    db = SessionLocal()
    msgs = db.query(DBMessage).order_by(DBMessage.timestamp.asc()).all()
    history = [{"sender": m.sender, "text": m.text} for m in msgs]
    db.close()
    return history

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg_json = json.loads(data)
            
            # Сохраняем в базу каждое сообщение!
            db = SessionLocal()
            new_msg = DBMessage(sender=msg_json['sender'], text=msg_json['text'])
            db.add(new_msg)
            db.commit()
            db.close()
            
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
