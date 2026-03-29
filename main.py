import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
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

# --- МЕНЕДЖЕР ПОДКЛЮЧЕНИЙ ---
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

@app.post("/register")
async def register(user: UserAuth):
    db = SessionLocal()
    try:
        exists = db.query(DBUser).filter(DBUser.username == user.username).first()
        if exists: return JSONResponse(status_code=400, content={"detail": "User exists"})
        new_user = DBUser(username=user.username, hashed_password=user.password, is_admin=0)
        db.add(new_user)
        db.commit()
        return {"status": "ok"}
    except Exception as e: return JSONResponse(status_code=500, content={"detail": str(e)})
    finally: db.close()

@app.post("/login")
async def login(user: UserAuth):
    db = SessionLocal()
    try:
        db_user = db.query(DBUser).filter(DBUser.username == user.username).first()
        if not db_user or db_user.hashed_password != user.password:
            return JSONResponse(status_code=400, content={"detail": "Wrong pass"})
        return {"status": "ok"}
    finally: db.close()

@app.get("/users")
async def get_users():
    db = SessionLocal()
    try:
        users = db.query(DBUser).all()
        return [{"username": u.username} for u in users]
    finally: db.close()

@app.get("/history")
async def get_history():
    db = SessionLocal()
    try:
        msgs = db.query(DBMessage).order_by(DBMessage.timestamp.asc()).all()
        return [{"sender": m.sender, "text": m.text} for m in msgs]
    finally: db.close()

@app.get("/")
async def get_index(): return FileResponse("index.html")

@app.get("/manifest.json")
async def get_manifest(): return FileResponse("manifest.json")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg_json = json.loads(data)
            db = SessionLocal()
            db.add(DBMessage(sender=msg_json['sender'], text=msg_json['text']))
            db.commit()
            db.close()
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except:
        pass
