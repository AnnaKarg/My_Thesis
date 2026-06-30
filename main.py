from fastapi import FastAPI # Κύρια εφαρμογή FastAPI
from api.routes import router as chat_router # Εισαγωγή των routes για το chat από το αρχείο api/routes.py
from database.session import init_db # Συνάρτηση για την αρχικοποίηση της βάσης δεδομένων
import uvicorn # Εισαγωγή του uvicorn για την εκτέλεση του server
from fastapi.middleware.cors import CORSMiddleware # Εισαγωγή του CORS middleware

app = FastAPI(title="AI Python Tutor API") # Δημιουργία της εφαρμογής FastAPI με τίτλο "AI Python Tutor API"

app.add_middleware( # Προσθήκη του CORS middleware — πρέπει να προστεθεί ΠΡΙΝ τον router
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router) # Ενσωμάτωση των routes του chat στην κύρια εφαρμογή

@app.on_event("startup") # Εκτέλεση της συνάρτησης on_startup κατά την εκκίνηση του server
async def on_startup(): # Αρχικοποίηση της βάσης δεδομένων κατά την εκκίνηση του server
    import database.models 
    await init_db()
    print("--- Η Βάση Δεδομένων είναι έτοιμη! ---")

@app.get("/") # Ορισμός του root endpoint που επιστρέφει ένα καλωσόρισμα
async def root(): 
    return {"message": "Welcome to AI Python Tutor API"}

if __name__ == "__main__": 
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)