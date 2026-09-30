import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

from models.schemas import HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput
from services.gemini_utils import (
    get_home_recommendations,
    get_party_recommendations,
    get_jewelry_recommendations,
)

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

app = FastAPI(title="PocketSmart: AI Budget Planner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

users_db = {}
active_sessions = {}
user_recommendations = {}
blacklisted_tokens = set()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_token(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if token and token not in blacklisted_tokens:
        return token
    return None


async def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme)):
    if not token:
        token = request.cookies.get("access_token")
    if not token or token in blacklisted_tokens:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username and username in users_db:
            return {"username": username, **users_db[username]}
    except JWTError:
        return None
    return None


# ---------- LANDING ----------
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# ---------- REGISTER ----------
@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
):
    if username in users_db:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Username already exists"},
            status_code=400,
        )
    users_db[username] = {
        "email": email,
        "full_name": full_name,
        "hashed_password": hash_password(password),
    }
    return RedirectResponse(url="/login", status_code=302)


# ---------- LOGIN ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
async def login_form(request: Request, username: str = Form(...), password: str = Form(...)):
    user = users_db.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=401,
        )
    token = create_access_token({"sub": username})
    active_sessions[username] = {"login_time": datetime.utcnow()}
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token", value=token, httponly=True, max_age=3600, samesite="lax"
    )
    return response


# ---------- LOGOUT ----------
@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("access_token")
    if token:
        blacklisted_tokens.add(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ---------- DASHBOARD ----------
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"user": current_user}
    )


# ---------- HOME PLANNER ----------
@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner_page(request: Request):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="home_planner.html", context={"user": current_user}
    )


@app.post("/home-budget")
async def plan_home_budget(request: Request, budget_input: HomeBudgetInput):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        raise HTTPException(status_code=401, detail="Not logged in")
    result = get_home_recommendations(budget_input)
    user_recommendations.setdefault(current_user["username"], []).append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "type": "home",
        "input": budget_input.dict(),
        "result": result,
    })
    return result


# ---------- PARTY PLANNER ----------
@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner_page(request: Request):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="party_planner.html", context={"user": current_user}
    )


@app.post("/party-budget")
async def plan_party_budget(request: Request, budget_input: PartyBudgetInput):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        raise HTTPException(status_code=401, detail="Not logged in")
    result = get_party_recommendations(budget_input)
    user_recommendations.setdefault(current_user["username"], []).append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "type": "party",
        "input": budget_input.dict(),
        "result": result,
    })
    return result


# ---------- JEWELRY PLANNER ----------
@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner_page(request: Request):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="jewelry_planner.html", context={"user": current_user}
    )


@app.post("/jewelry-budget")
async def plan_jewelry_budget(
    request: Request,
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: str = Form(""),
    outfit_image: Optional[UploadFile] = File(None),
):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        raise HTTPException(status_code=401, detail="Not logged in")

    budget_input = JewelryBudgetInput(
        total_budget=total_budget, occasion=occasion, preferences=preferences
    )

    image_path = None
    if outfit_image and outfit_image.filename:
        image_path = f"static/uploads/{uuid.uuid4()}_{outfit_image.filename}"
        with open(image_path, "wb") as f:
            shutil.copyfileobj(outfit_image.file, f)

    result = get_jewelry_recommendations(budget_input, image_path)
    user_recommendations.setdefault(current_user["username"], []).append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "type": "jewelry",
        "input": budget_input.dict(),
        "result": result,
    })
    return result


# ---------- HISTORY ----------
@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    current_user = await get_current_user(request, await get_token(request))
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    history = user_recommendations.get(current_user["username"], [])
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"user": current_user, "history": history[::-1]},
    )


# ---------- RUN ----------
if __name__ == "__main__":
    import uvicorn
    print("Starting PocketSmart AI...")
    uvicorn.run(app, host="0.0.0.0", port=8000)