from fastapi import FastAPI
from api import users, update_name

app = FastAPI()

# 라우터 등록
app.include_router(users.router)
app.include_router(update_name.router)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}