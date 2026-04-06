from fastapi import FastAPI
from api.routes import router as chat_router
from database.session import init_db
import uvicorn

app = FastAPI(title="AI Python Tutor API")
app.include_router(chat_router)

@app.on_event("startup")
async def on_startup():
    await init_db()
    print("--- Η Βάση Δεδομένων είναι έτοιμη! ---")

@app.get("/")
async def root():
    return {"message": "Welcome to AI Python Tutor API"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)