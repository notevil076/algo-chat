import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, or_, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    recipient = Column(String)
    text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

class UserAuth(BaseModel):
    username: str
    password: str

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]

async def send_personal_message(self, message: dict, username: str):
    if username in self.active_connections:
        websocket = self.active_connections[username]
        await websocket.send_json(message)
    else:
        print(f"User {username} is not online")

manager = ConnectionManager()

@app.post("/register")
async def register(user: UserAuth):
    db = SessionLocal()
    try:
        if db.query(DBUser).filter(DBUser.username == user.username).first():
            return JSONResponse(status_code=400, content={"detail": "Exists"})
        db.add(DBUser(username=user.username, hashed_password=user.password))
        db.commit()
        return {"status": "ok"}
    finally: db.close()

@app.post("/login")
async def login(user: UserAuth):
    db = SessionLocal()
    try:
        u = db.query(DBUser).filter(DBUser.username == user.username, DBUser.hashed_password == user.password).first()
        return {"status": "ok"} if u else JSONResponse(status_code=400, content={"detail": "Error"})
    finally: db.close()

@app.get("/search_user")
async def search_user(q: str):
    db = SessionLocal()
    u = db.query(DBUser).filter(DBUser.username == q).first()
    db.close()
    return {"exists": True if u else False}

@app.get("/history")
async def get_history(me: str, other: str):
    db = SessionLocal()
    msgs = db.query(DBMessage).filter(
        or_(
            and_(DBMessage.sender == me, DBMessage.recipient == other),
            and_(DBMessage.sender == other, DBMessage.recipient == me)
        )
    ).order_by(DBMessage.timestamp.asc()).all()
    db.close()
    return [{"sender": m.sender, "text": m.text} for m in msgs]

@app.get("/")
async def get_index(): return FileResponse("index.html")

@app.get("/manifest.json")
async def get_manifest(): return FileResponse("manifest.json")

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg_json = json.loads(data)
            
            # ВАЖНО: Принудительно ставим отправителя из URL сокета, 
            # чтобы никто не мог подделать имя в JSON
            msg_json['sender'] = username 
            
            db = SessionLocal()
            db.add(DBMessage(sender=msg_json['sender'], recipient=msg_json['recipient'], text=msg_json['text']))
            db.commit()
            db.close()
            
# Отправляем получателю
await manager.send_personal_message(msg_json, msg_json['recipient'])
# Отправляем копию СЕБЕ, чтобы сообщение появилось в твоем окне на всех устройствах
await manager.send_personal_message(msg_json, username)  

    except WebSocketDisconnect:
        manager.disconnect(username)
    except Exception as e:
        print(f"Error: {e}")
        manager.disconnect(username)
