from fastapi import APIRouter, UploadFile, File, status, HTTPException
from pydantic import BaseModel
from services.crag import MultimodalEarthquakeCRAG
import uuid, datetime as dt

router_analyze = APIRouter()
quake_crag = MultimodalEarthquakeCRAG()

class userAnalysisRequest(BaseModel):
    blob_name: str
    signed_url: str
    mime_type: str

@router_analyze.post("/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_media_and_traverse(data : userAnalysisRequest):
    try:
        result = quake_crag.analyze_media_and_traverse_states(
            blob_name=data.blob_name,
            signed_url=data.signed_url,
            mime_type=data.mime_type,
        )

        return result["final_analysis"]
    except Exception as e:
        raise HTTPException(status_code=500)