import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Tuple, Optional, Dict, Any
import threading
import time
import logging
from datetime import datetime
import yaml
import base64
import os
from person_tracker import PersonTracker, Person
import asyncio
import websockets
import json

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.model = YOLO(self.config['detection']['model_path'])
        self.tracker = PersonTracker(
            max_disappeared=self.config['tracking']['max_disappeared_frames'],
            max_distance=self.config['tracking']['max_distance_threshold']
        )
        
        self.roi_polygon = None
        self.is_processing = False
        self.current_frame = None
        self.detection_results = []
        self.video_capture = None
        self.processing_thread = None
        self.websocket_server = None
        self.connected_clients = set()
        self.dummy_mode = False
        self.dummy_frame_count = 0
        
        # Statistics
        self.stats = {
            'total_detections': 0,
            'idle_alerts': 0,
            'processing_fps': 0,
            'last_update': datetime.now()
        }

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            # Try different possible paths
            possible_paths = [
                config_path,
                os.path.join(os.path.dirname(__file__), config_path),
                os.path.join('/app/backend', config_path)
            ]
            
            config_file = None
            for path in possible_paths:
                if os.path.exists(path):
                    config_file = path
                    break
            
            if config_file:
                with open(config_file, 'r') as file:
                    logger.info(f"Loading config from: {config_file}")
                    return yaml.safe_load(file)
            else:
                logger.warning(f"Config file not found in any of these paths: {possible_paths}")
                
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            
        # Return default config
        logger.info("Using default configuration")
        return {
            'detection': {'model_path': 'yolov8n.pt', 'confidence_threshold': 0.5, 'person_class_id': 0},
            'tracking': {'max_disappeared_frames': 30, 'max_distance_threshold': 100},
            'idle_detection': {'movement_threshold': 20, 'idle_alert_threshold': 30},
            'video': {'frame_resize_width': 640, 'frame_resize_height': 480, 'fps_limit': 15},
            'roi': {'enabled': True, 'coordinates': []},
            'websocket': {'port': 8002, 'max_connections': 10}
        }

    def set_roi(self, coordinates: List[Tuple[int, int]]):
        """Set Region of Interest polygon"""
        if len(coordinates) >= 3:
            self.roi_polygon = np.array(coordinates, np.int32)
            logger.info(f"ROI set with {len(coordinates)} points")
        else:
            self.roi_polygon = None
            logger.info("ROI cleared")

    def _point_in_roi(self, point: Tuple[int, int]) -> bool:
        """Check if point is inside ROI polygon"""
        if self.roi_polygon is None:
            return True
        return cv2.pointPolygonTest(self.roi_polygon, point, False) >= 0

    def _detect_persons(self, frame: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect persons in frame using YOLO"""
        try:
            # Resize frame for processing
            height, width = frame.shape[:2]
            target_width = self.config['video']['frame_resize_width']
            target_height = self.config['video']['frame_resize_height']
            
            # Calculate scale factors
            scale_x = width / target_width
            scale_y = height / target_height
            
            # Resize frame
            resized_frame = cv2.resize(frame, (target_width, target_height))
            
            # Run YOLO detection
            results = self.model(resized_frame, verbose=False)
            
            detections = []
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        # Get class ID and confidence
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        
                        # Only process person detections above threshold
                        if (class_id == self.config['detection']['person_class_id'] and 
                            confidence >= self.config['detection']['confidence_threshold']):
                            
                            # Get bounding box coordinates (scale back to original size)
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            x1, y1, x2, y2 = int(x1 * scale_x), int(y1 * scale_y), int(x2 * scale_x), int(y2 * scale_y)
                            
                            # Convert to x, y, w, h format
                            x, y, w, h = x1, y1, x2 - x1, y2 - y1
                            
                            # Check if detection center is in ROI
                            center_x, center_y = x + w // 2, y + h // 2
                            if self._point_in_roi((center_x, center_y)):
                                detections.append(((x, y, w, h), confidence))
            
            self.stats['total_detections'] += len(detections)
            return detections
            
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return []

    def _draw_detections(self, frame: np.ndarray, persons: List[Person]) -> np.ndarray:
        """Draw detection results on frame"""
        output_frame = frame.copy()
        
        # Draw ROI if set
        if self.roi_polygon is not None:
            cv2.polylines(output_frame, [self.roi_polygon], True, (255, 255, 0), 2)
            cv2.putText(output_frame, "ROI", tuple(self.roi_polygon[0]), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        # Draw person detections
        for person in persons:
            if person.disappeared_frames > 0:
                continue
                
            x, y, w, h = person.bbox
            center = person.center
            
            # Choose color based on idle status
            if person.is_idle:
                color = (0, 0, 255)  # Red for idle
                status = "IDLE"
                self.stats['idle_alerts'] += 1
            else:
                color = (0, 255, 0)  # Green for active
                status = "ACTIVE"
            
            # Draw bounding box
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), color, 2)
            
            # Draw center point
            cv2.circle(output_frame, center, 5, color, -1)
            
            # Draw person ID and status
            label = f"ID: {person.id[:8]} - {status}"
            cv2.putText(output_frame, label, (x, y - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Draw movement trail
            if len(person.movement_history) > 1:
                points = np.array(person.movement_history, np.int32).reshape((-1, 1, 2))
                cv2.polylines(output_frame, [points], False, (255, 0, 255), 1)
        
        # Draw statistics
        stats_text = [
            f"Active Persons: {len([p for p in persons if not p.disappeared_frames])}",
            f"Idle Persons: {len([p for p in persons if p.is_idle])}",
            f"FPS: {self.stats['processing_fps']:.1f}",
            f"Total Detections: {self.stats['total_detections']}"
        ]
        
        for i, text in enumerate(stats_text):
            cv2.putText(output_frame, text, (10, 30 + i * 25), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return output_frame

    async def _broadcast_to_clients(self, message: str):
        """Broadcast message to all connected WebSocket clients"""
        if self.connected_clients:
            disconnected = set()
            for client in self.connected_clients.copy():
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
                except Exception as e:
                    logger.error(f"Error broadcasting to client: {e}")
                    disconnected.add(client)
            
            # Remove disconnected clients
            self.connected_clients -= disconnected

    async def _handle_websocket_client(self, websocket, path):
        """Handle WebSocket client connection"""
        logger.info(f"WebSocket client connected: {websocket.remote_address}")
        self.connected_clients.add(websocket)
        
        try:
            await websocket.wait_closed()
        except Exception as e:
            logger.error(f"WebSocket client error: {e}")
        finally:
            self.connected_clients.discard(websocket)
            logger.info(f"WebSocket client disconnected: {websocket.remote_address}")

    def start_websocket_server(self):
        """Start WebSocket server for real-time communication"""
        async def server():
            self.websocket_server = await websockets.serve(
                self._handle_websocket_client,
                "0.0.0.0",  # Bind to all interfaces instead of localhost
                self.config['websocket']['port']
            )
            logger.info(f"WebSocket server started on 0.0.0.0:{self.config['websocket']['port']}")
            await self.websocket_server.wait_closed()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server())

    def start_processing(self, source: str):
        """Start video processing from source"""
        if self.is_processing:
            logger.info("Processing already running")
            return True  # Return True instead of False if already running
        
        try:
            # Initialize video capture
            if source.startswith(('rtsp://', 'http://')):
                self.video_capture = cv2.VideoCapture(source)
                self.video_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce latency
            elif source.isdigit():
                self.video_capture = cv2.VideoCapture(int(source))
            else:
                self.video_capture = cv2.VideoCapture(source)
            
            if not self.video_capture.isOpened():
                logger.warning(f"Failed to open video source: {source}, switching to demo mode")
                # For testing purposes, create a dummy video source
                self.video_capture = None
                self._create_dummy_video_source()
            
            self.is_processing = True
            
            # Start WebSocket server in separate thread
            websocket_thread = threading.Thread(target=self.start_websocket_server, daemon=True)
            websocket_thread.start()
            
            # Start processing thread
            self.processing_thread = threading.Thread(target=self._process_video, daemon=True)
            self.processing_thread.start()
            
            logger.info(f"Started processing video source: {source} (demo mode: {self.dummy_mode})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start processing: {e}")
            return False

    def _create_dummy_video_source(self):
        """Create a dummy video source for testing when no camera is available"""
        logger.info("Creating dummy video source for testing")
        # Create a simple synthetic video feed
        self.dummy_mode = True
        self.dummy_frame_count = 0

    def _generate_dummy_frame(self):
        """Generate a dummy frame with synthetic person detections for testing"""
        # Create a 640x480 blue frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (100, 50, 0)  # Dark blue background
        
        # Add some text
        cv2.putText(frame, "DEMO MODE - No Camera Available", (50, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"Frame: {self.dummy_frame_count}", (50, 100), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Simulate moving person detection boxes
        import math
        time_factor = self.dummy_frame_count * 0.1
        
        # Moving person 1
        x1 = int(200 + 100 * math.sin(time_factor))
        y1 = int(200 + 50 * math.cos(time_factor))
        cv2.rectangle(frame, (x1, y1), (x1 + 80, y1 + 160), (0, 255, 0), 2)
        cv2.putText(frame, "Person 1 - ACTIVE", (x1, y1 - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        # Stationary person 2 (idle)
        x2, y2 = 450, 250
        cv2.rectangle(frame, (x2, y2), (x2 + 80, y2 + 160), (0, 0, 255), 2)
        cv2.putText(frame, "Person 2 - IDLE", (x2, y2 - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        
        self.dummy_frame_count += 1
        return frame

    def _get_dummy_detections(self):
        """Generate dummy person detections for testing"""
        import math
        time_factor = self.dummy_frame_count * 0.1
        
        detections = []
        
        # Moving person 1
        x1 = int(200 + 100 * math.sin(time_factor))
        y1 = int(200 + 50 * math.cos(time_factor))
        detections.append(((x1, y1, 80, 160), 0.85))
        
        # Stationary person 2 (idle)
        detections.append(((450, 250, 80, 160), 0.92))
        
        return detections

    def _process_video(self):
        """Main video processing loop"""
        fps_limit = self.config['video']['fps_limit']
        frame_time = 1.0 / fps_limit if fps_limit > 0 else 0
        last_frame_time = time.time()
        
        while self.is_processing:
            try:
                start_time = time.time()
                
                # Get frame based on mode
                if self.dummy_mode or self.video_capture is None:
                    frame = self._generate_dummy_frame()
                    detections = self._get_dummy_detections()
                    ret = True
                else:
                    # Read frame from video capture
                    ret, frame = self.video_capture.read()
                    if not ret:
                        logger.warning("Failed to read frame, switching to dummy mode...")
                        self.dummy_mode = True
                        continue
                    
                    # Detect persons using YOLO
                    detections = self._detect_persons(frame)
                
                if not ret:
                    continue
                
                # Update tracker
                persons = self.tracker.update(
                    detections,
                    movement_threshold=self.config['idle_detection']['movement_threshold'],
                    idle_threshold=self.config['idle_detection']['idle_alert_threshold']
                )
                
                # Draw results
                output_frame = self._draw_detections(frame, persons)
                self.current_frame = output_frame
                self.detection_results = persons
                
                # Calculate FPS
                processing_time = time.time() - start_time
                self.stats['processing_fps'] = 1.0 / processing_time if processing_time > 0 else 0
                self.stats['last_update'] = datetime.now()
                
                # Send real-time data to WebSocket clients
                if self.connected_clients:
                    frame_data = self._encode_frame_for_websocket(output_frame)
                    detection_data = {
                        'type': 'realtime_update',
                        'persons': [person.to_dict() for person in persons],
                        'stats': {
                            'active_count': len([p for p in persons if not p.disappeared_frames]),
                            'idle_count': len([p for p in persons if p.is_idle]),
                            'fps': self.stats['processing_fps'],
                            'timestamp': datetime.now().isoformat()
                        },
                        'frame': frame_data
                    }
                    
                    # Broadcast asynchronously
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self._broadcast_to_clients(json.dumps(detection_data)))
                    except Exception as e:
                        logger.error(f"Error broadcasting WebSocket data: {e}")
                
                # FPS limiting
                if frame_time > 0:
                    elapsed = time.time() - last_frame_time
                    sleep_time = frame_time - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                last_frame_time = time.time()
                
            except Exception as e:
                logger.error(f"Processing error: {e}")
                time.sleep(0.1)

    def _encode_frame_for_websocket(self, frame: np.ndarray) -> str:
        """Encode frame as base64 for WebSocket transmission"""
        try:
            # Resize frame for transmission (reduce bandwidth)
            height, width = frame.shape[:2]
            if width > 800:
                scale = 800 / width
                new_width = 800
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height))
            
            # Encode as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            return frame_base64
        except Exception as e:
            logger.error(f"Frame encoding error: {e}")
            return ""

    def stop_processing(self):
        """Stop video processing"""
        self.is_processing = False
        
        if self.video_capture is not None:
            self.video_capture.release()
            self.video_capture = None
        
        if self.processing_thread is not None:
            self.processing_thread.join(timeout=5)
        
        if self.websocket_server is not None:
            self.websocket_server.close()
        
        logger.info("Video processing stopped")

    def get_current_frame(self) -> Optional[np.ndarray]:
        """Get current processed frame"""
        return self.current_frame

    def get_detection_results(self) -> List[Person]:
        """Get current detection results"""
        return self.detection_results.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return self.stats.copy()