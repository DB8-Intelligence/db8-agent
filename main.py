from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"status": "DB8 Agent Online"}