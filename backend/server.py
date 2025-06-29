from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime
import json
import cv2
import numpy as np
import asyncio
import base64
import tempfile
import yaml

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from video_processor import VideoProcessor
from person_tracker import Person

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="Idle Person Detection System", version="1.0.0")

# Create API router
api_router = APIRouter(prefix="/api")

# Global video processor instance
video_processor = VideoProcessor()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# Pydantic Models
class VideoSourceConfig(BaseModel):
    source_type: str  # "webcam", "rtsp", "file"
    source_path: str
    name: str = "Default Source"

class ROIConfig(BaseModel):
    coordinates: List[List[int]]  # List of [x, y] coordinates
    enabled: bool = True

class DetectionConfig(BaseModel):
    confidence_threshold: float = 0.5
    movement_threshold: int = 20
    idle_alert_threshold: int = 30

class SystemStats(BaseModel):
    active_persons: int
    idle_persons: int
    total_detections: int
    processing_fps: float
    last_update: datetime

class PersonData(BaseModel):
    id: str
    center: List[int]
    bbox: List[int]
    first_seen: datetime
    last_seen: datetime
    last_movement: datetime
    is_idle: bool
    idle_duration: float
    confidence: float

# API Endpoints
@api_router.get("/")
async def root():
    return {"message": "Idle Person Detection System API", "version": "1.0.0"}

@api_router.post("/video/start")
async def start_video_processing(config: VideoSourceConfig):
    """Start video processing from specified source"""
    try:
        success = video_processor.start_processing(config.source_path)
        if success:
            # Store video source config in database
            video_config = {
                "id": str(uuid.uuid4()),
                "source_type": config.source_type,
                "source_path": config.source_path,
                "name": config.name,
                "started_at": datetime.utcnow(),
                "status": "active"
            }
            result = await db.video_sources.insert_one(video_config)
            video_config["_id"] = str(result.inserted_id)
            
            return {"message": "Video processing started successfully", "config": video_config}
        else:
            raise HTTPException(status_code=500, detail="Failed to start video processing")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting video processing: {str(e)}")

@api_router.post("/video/stop")
async def stop_video_processing():
    """Stop video processing"""
    try:
        video_processor.stop_processing()
        
        # Update database
        await db.video_sources.update_many(
            {"status": "active"},
            {"$set": {"status": "stopped", "stopped_at": datetime.utcnow()}}
        )
        
        return {"message": "Video processing stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping video processing: {str(e)}")

@api_router.post("/roi/set")
async def set_roi(roi_config: ROIConfig):
    """Set Region of Interest"""
    try:
        if roi_config.enabled and roi_config.coordinates:
            video_processor.set_roi([(point[0], point[1]) for point in roi_config.coordinates])
        else:
            video_processor.set_roi([])
        
        # Store ROI config in database
        roi_data = {
            "id": str(uuid.uuid4()),
            "coordinates": roi_config.coordinates,
            "enabled": roi_config.enabled,
            "created_at": datetime.utcnow()
        }
        result = await db.roi_configs.insert_one(roi_data)
        roi_data["_id"] = str(result.inserted_id)
        
        return {"message": "ROI updated successfully", "config": roi_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error setting ROI: {str(e)}")

@api_router.get("/roi/current")
async def get_current_roi():
    """Get current ROI configuration"""
    try:
        roi_config = await db.roi_configs.find_one(sort=[("created_at", -1)])
        if roi_config:
            roi_config["_id"] = str(roi_config["_id"])
            return roi_config
        return {"enabled": False, "coordinates": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting ROI: {str(e)}")

@api_router.post("/config/detection")
async def update_detection_config(config: DetectionConfig):
    """Update detection configuration"""
    try:
        # Update video processor config
        video_processor.config['detection']['confidence_threshold'] = config.confidence_threshold
        video_processor.config['idle_detection']['movement_threshold'] = config.movement_threshold
        video_processor.config['idle_detection']['idle_alert_threshold'] = config.idle_alert_threshold
        
        # Save to database
        config_data = {
            "id": str(uuid.uuid4()),
            "confidence_threshold": config.confidence_threshold,
            "movement_threshold": config.movement_threshold,
            "idle_alert_threshold": config.idle_alert_threshold,
            "updated_at": datetime.utcnow()
        }
        result = await db.detection_configs.insert_one(config_data)
        config_data["_id"] = str(result.inserted_id)
        
        return {"message": "Detection configuration updated", "config": config_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating config: {str(e)}")

@api_router.get("/config/detection")
async def get_detection_config():
    """Get current detection configuration"""
    try:
        config = await db.detection_configs.find_one(sort=[("updated_at", -1)])
        if config:
            config["_id"] = str(config["_id"])
            return config
        
        # Return default config
        return {
            "confidence_threshold": 0.5,
            "movement_threshold": 20,
            "idle_alert_threshold": 30
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting config: {str(e)}")

@api_router.get("/stats")
async def get_system_stats():
    """Get current system statistics"""
    try:
        stats = video_processor.get_stats()
        persons = video_processor.get_detection_results()
        
        return {
            "active_persons": len([p for p in persons if p.disappeared_frames == 0]),
            "idle_persons": len([p for p in persons if p.is_idle]),
            "total_detections": stats.get('total_detections', 0),
            "processing_fps": stats.get('processing_fps', 0),
            "last_update": stats.get('last_update', datetime.utcnow())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")

@api_router.get("/persons")
async def get_detected_persons():
    """Get current detected persons"""
    try:
        persons = video_processor.get_detection_results()
        return [person.to_dict() for person in persons if person.disappeared_frames == 0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting persons: {str(e)}")

@api_router.get("/persons/idle")
async def get_idle_persons():
    """Get currently idle persons"""
    try:
        persons = video_processor.get_detection_results()
        return [person.to_dict() for person in persons if person.is_idle and person.disappeared_frames == 0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting idle persons: {str(e)}")

@api_router.get("/video/frame")
async def get_current_frame():
    """Get current processed frame as base64 image"""
    try:
        frame = video_processor.get_current_frame()
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            return {"frame": frame_base64, "timestamp": datetime.utcnow()}
        else:
            return {"frame": None, "message": "No frame available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting frame: {str(e)}")

@api_router.post("/video/upload")
async def upload_video_file(file: UploadFile = File(...)):
    """Upload video file for processing"""
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        # Start processing the uploaded file
        success = video_processor.start_processing(tmp_file_path)
        
        if success:
            return {"message": "Video file uploaded and processing started", "filename": file.filename}
        else:
            raise HTTPException(status_code=500, detail="Failed to process uploaded video")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading video: {str(e)}")

@api_router.get("/alerts/history")
async def get_alerts_history(limit: int = 100):
    """Get idle person alerts history"""
    try:
        alerts = await db.idle_alerts.find().sort("timestamp", -1).limit(limit).to_list(limit)
        for alert in alerts:
            alert["_id"] = str(alert["_id"])
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting alerts: {str(e)}")

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Send real-time data every second
            stats = video_processor.get_stats()
            persons = video_processor.get_detection_results()
            frame = video_processor.get_current_frame()
            
            # Encode frame for transmission
            frame_data = ""
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                frame_data = base64.b64encode(buffer).decode('utf-8')
            
            data = {
                "type": "realtime_update",
                "stats": {
                    "active_persons": len([p for p in persons if p.disappeared_frames == 0]),
                    "idle_persons": len([p for p in persons if p.is_idle]),
                    "processing_fps": stats.get('processing_fps', 0),
                    "timestamp": datetime.utcnow().isoformat()
                },
                "persons": [person.to_dict() for person in persons if person.disappeared_frames == 0],
                "frame": frame_data
            }
            
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(1)  # Send updates every second
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Include the router in the main app
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    """Initialize system on startup"""
    logger.info("Idle Person Detection System starting up...")
    
    # Create database indexes
    await db.video_sources.create_index("started_at")
    await db.roi_configs.create_index("created_at")
    await db.detection_configs.create_index("updated_at")
    await db.idle_alerts.create_index("timestamp")
    
    logger.info("System initialized successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Idle Person Detection System...")
    video_processor.stop_processing()
    client.close()
    logger.info("System shutdown complete")