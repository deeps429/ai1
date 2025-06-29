import requests
import json
import time
import base64
import os
import sys
from datetime import datetime
import websocket
import threading
import ssl

# Get the backend URL from the frontend .env file
BACKEND_URL = "https://0421f659-b986-4b39-9da8-3f4cbeb0ff72.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

class IdlePersonDetectionTester:
    def __init__(self, api_url):
        self.api_url = api_url
        self.tests_run = 0
        self.tests_passed = 0
        self.ws_messages = []
        self.ws = None
        self.ws_thread = None
        
    def run_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    # For file uploads, don't use JSON headers
                    response = requests.post(url, files=files)
                else:
                    response = requests.post(url, json=data, headers=headers)
            
            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    return success, response.json()
                except:
                    return success, {}
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                try:
                    print(f"Response: {response.text}")
                    return False, response.json()
                except:
                    return False, {}
                
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}
    
    def test_system_status(self):
        """Test system status endpoint"""
        return self.run_test(
            "System Status",
            "GET",
            "",
            200
        )
    
    def test_start_video_processing(self, source_type="webcam", source_path="0"):
        """Test starting video processing"""
        return self.run_test(
            "Start Video Processing",
            "POST",
            "video/start",
            200,
            data={
                "source_type": source_type,
                "source_path": source_path,
                "name": f"Test {source_type}"
            }
        )
    
    def test_stop_video_processing(self):
        """Test stopping video processing"""
        return self.run_test(
            "Stop Video Processing",
            "POST",
            "video/stop",
            200
        )
    
    def test_set_roi(self, coordinates=[[100, 100], [400, 100], [400, 300], [100, 300]]):
        """Test setting Region of Interest"""
        return self.run_test(
            "Set ROI",
            "POST",
            "roi/set",
            200,
            data={
                "coordinates": coordinates,
                "enabled": True
            }
        )
    
    def test_get_current_roi(self):
        """Test getting current ROI"""
        return self.run_test(
            "Get Current ROI",
            "GET",
            "roi/current",
            200
        )
    
    def test_clear_roi(self):
        """Test clearing ROI"""
        return self.run_test(
            "Clear ROI",
            "POST",
            "roi/set",
            200,
            data={
                "coordinates": [],
                "enabled": False
            }
        )
    
    def test_update_detection_config(self, confidence=0.6, movement=25, idle=35):
        """Test updating detection configuration"""
        return self.run_test(
            "Update Detection Config",
            "POST",
            "config/detection",
            200,
            data={
                "confidence_threshold": confidence,
                "movement_threshold": movement,
                "idle_alert_threshold": idle
            }
        )
    
    def test_get_detection_config(self):
        """Test getting detection configuration"""
        return self.run_test(
            "Get Detection Config",
            "GET",
            "config/detection",
            200
        )
    
    def test_get_stats(self):
        """Test getting system statistics"""
        return self.run_test(
            "Get System Stats",
            "GET",
            "stats",
            200
        )
    
    def test_get_persons(self):
        """Test getting detected persons"""
        return self.run_test(
            "Get Detected Persons",
            "GET",
            "persons",
            200
        )
    
    def test_get_idle_persons(self):
        """Test getting idle persons"""
        return self.run_test(
            "Get Idle Persons",
            "GET",
            "persons/idle",
            200
        )
    
    def test_get_current_frame(self):
        """Test getting current frame"""
        return self.run_test(
            "Get Current Frame",
            "GET",
            "video/frame",
            200
        )
    
    def test_upload_video(self, file_path):
        """Test uploading a video file"""
        if not os.path.exists(file_path):
            print(f"❌ Failed - File not found: {file_path}")
            return False, {}
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'video/mp4')}
            return self.run_test(
                "Upload Video File",
                "POST",
                "video/upload",
                200,
                files=files
            )
    
    def on_ws_message(self, ws, message):
        """Handle WebSocket messages"""
        try:
            data = json.loads(message)
            self.ws_messages.append(data)
            print(f"WebSocket message received: {data['type'] if 'type' in data else 'unknown'}")
        except Exception as e:
            print(f"Error parsing WebSocket message: {e}")
    
    def on_ws_error(self, ws, error):
        print(f"WebSocket error: {error}")
    
    def on_ws_close(self, ws, close_status_code, close_msg):
        print("WebSocket connection closed")
    
    def on_ws_open(self, ws):
        print("WebSocket connection established")
    
    def connect_websocket(self):
        """Connect to WebSocket for real-time updates"""
        ws_url = f"{BACKEND_URL.replace('http', 'ws')}/ws"
        print(f"Connecting to WebSocket: {ws_url}")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_ws_message,
            on_error=self.on_ws_error,
            on_close=self.on_ws_close,
            on_open=self.on_ws_open
        )
        
        self.ws_thread = threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}})
        self.ws_thread.daemon = True
        self.ws_thread.start()
        
        # Wait for connection to establish
        time.sleep(2)
        return self.ws_thread.is_alive()
    
    def disconnect_websocket(self):
        """Disconnect from WebSocket"""
        if self.ws:
            self.ws.close()
            if self.ws_thread:
                self.ws_thread.join(timeout=2)
    
    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting Idle Person Detection System API Tests")
        
        # Test system status
        self.test_system_status()
        
        # Test configuration endpoints
        self.test_get_detection_config()
        self.test_update_detection_config()
        self.test_get_detection_config()
        
        # Test ROI endpoints
        self.test_get_current_roi()
        self.test_set_roi()
        self.test_get_current_roi()
        self.test_clear_roi()
        
        # Test video processing with webcam
        success, _ = self.test_start_video_processing()
        
        if success:
            # If video processing started, test other endpoints
            time.sleep(2)  # Wait for processing to start
            
            # Test WebSocket connection
            ws_success = self.connect_websocket()
            if ws_success:
                print("✅ WebSocket connection successful")
                # Wait for some messages
                time.sleep(5)
                print(f"Received {len(self.ws_messages)} WebSocket messages")
                self.disconnect_websocket()
            else:
                print("❌ WebSocket connection failed")
            
            # Test data endpoints
            self.test_get_stats()
            self.test_get_persons()
            self.test_get_idle_persons()
            self.test_get_current_frame()
            
            # Stop video processing
            self.test_stop_video_processing()
        
        # Print test results
        print(f"\n📊 Tests passed: {self.tests_passed}/{self.tests_run} ({self.tests_passed/self.tests_run*100:.1f}%)")
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = IdlePersonDetectionTester(API_URL)
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)