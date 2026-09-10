# main.py
import os
import uuid
import shutil
import zipfile
import bcrypt
import jwt
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Request, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
SECRET_KEY = "nexus-super-secret-jwt-key" # Change in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

SQLALCHEMY_DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

app = FastAPI(title="Nexus Cloud SaaS Platform")

os.makedirs("sites", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==========================================
# 2. DATABASE MODELS
# ==========================================
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 3. AUTHENTICATION HELPERS (FIXED)
# ==========================================
def get_password_hash(password: str) -> str:
    """Hashes a password directly using bcrypt."""
    # Bcrypt has a 72 byte limit, truncating safely
    pwd_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a password against a hash."""
    pwd_bytes = plain_password[:72].encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hash_bytes)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ==========================================
# 4. API ROUTES
# ==========================================
@app.get("/")
async def serve_frontend(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/signup")
async def signup(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if len(password) < 6:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 6 characters"})
        
    if db.query(User).filter(User.username == username).first():
        return JSONResponse(status_code=400, content={"error": "Username already exists"})
    
    new_user = User(username=username, password_hash=get_password_hash(password))
    db.add(new_user)
    db.commit()
    return {"message": "Account created successfully. Please login."}

@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return JSONResponse(status_code=401, content={"error": "Invalid username or password"})
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "username": user.username}

@app.get("/api/projects")
async def get_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.user_id == current_user.id).order_by(Project.created_at.desc()).all()
    return [{"id": p.id, "created_at": p.created_at.strftime("%b %d, %Y"), "url": f"/site/{p.id}/"} for p in projects]

@app.post("/api/upload")
async def upload_project(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename.endswith('.zip'):
        return JSONResponse(status_code=400, content={"error": "Upload a .zip file."})

    project_id = str(uuid.uuid4())[:8]
    project_dir = Path(f"sites/{project_id}")
    zip_path = Path(f"sites/{project_id}.zip")

    try:
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        os.makedirs(project_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(project_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(project_dir)
            os.remove(zip_path)
            return JSONResponse(status_code=400, content={"error": "Corrupted ZIP file."})

        extracted_files = list(project_dir.rglob("index.html"))
        if not extracted_files:
            shutil.rmtree(project_dir)
            os.remove(zip_path)
            return JSONResponse(status_code=400, content={"error": "No index.html found."})

        index_file = extracted_files[0]
        if index_file.parent != project_dir:
            temp_dir = Path(f"sites/{project_id}_temp")
            shutil.move(str(index_file.parent), str(temp_dir))
            shutil.rmtree(project_dir)
            shutil.move(str(temp_dir), str(project_dir))

        os.remove(zip_path)

        new_project = Project(id=project_id, user_id=current_user.id)
        db.add(new_project)
        db.commit()

        return {"project_id": project_id, "url": f"/site/{project_id}/", "status": "live"}

    except Exception as e:
        if zip_path.exists(): os.remove(zip_path)
        if project_dir.exists(): shutil.rmtree(project_dir)
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
    
    db.delete(project)
    db.commit()

    project_dir = Path(f"sites/{project_id}")
    if project_dir.exists():
        shutil.rmtree(project_dir)
        
    return {"message": "Deleted"}

@app.get("/site/{project_id}/{file_path:path}")
async def serve_site(project_id: str, file_path: str):
    base_path = Path(f"sites/{project_id}")
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    if file_path == "": file_path = "index.html"
    target_file = base_path / file_path

    try:
        target_file.resolve().relative_to(base_path.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(target_file)