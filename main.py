from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="DB8 Intelligence Agent")

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/agent")
async def agent(payload: dict):
    return JSONResponse({
        "message": "DB8 Agent recebeu os dados",
        "data": payload
    })
