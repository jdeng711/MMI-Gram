from app import app 
import uvicorn
import os

port = int(os.environ.get("PORT", 8000))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)