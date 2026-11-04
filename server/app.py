from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import userUpload
from routes import analyzeMedia
#  FastAPI instance
# ────────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def server_start():
    return {"server RUNNING.."}

app.include_router(userUpload.router_upload)
app.include_router(analyzeMedia.router_analyze)