from fastapi import FastAPI
from api import users

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}