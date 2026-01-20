import os
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/helius-webhook")
async def helius_webhook(req: Request):
    data = await req.json()
    print(data)
    return {"received": True}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
