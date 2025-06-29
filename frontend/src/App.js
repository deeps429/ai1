import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const WS_URL = BACKEND_URL.replace('http', 'ws');

const App = () => {
  // State management
  const [isProcessing, setIsProcessing] = useState(false);
  const [videoSource, setVideoSource] = useState('');
  const [sourceType, setSourceType] = useState('webcam');
  const [currentFrame, setCurrentFrame] = useState(null);
  const [detectedPersons, setDetectedPersons] = useState([]);
  const [stats, setStats] = useState({
    active_persons: 0,
    idle_persons: 0,
    processing_fps: 0,
    total_detections: 0
  });
  
  // Configuration states
  const [config, setConfig] = useState({
    confidence_threshold: 0.5,
    movement_threshold: 20,
    idle_alert_threshold: 30
  });
  
  // ROI states
  const [roiMode, setRoiMode] = useState(false);
  const [roiPoints, setRoiPoints] = useState([]);
  const [currentRoi, setCurrentRoi] = useState({ enabled: false, coordinates: [] });
  
  // WebSocket and canvas refs
  const wsRef = useRef(null);
  const canvasRef = useRef(null);
  const fileInputRef = useRef(null);

  // WebSocket connection for real-time updates
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        wsRef.current = new WebSocket(`${WS_URL}/ws`);
        
        wsRef.current.onopen = () => {
          console.log('WebSocket connected');
        };
        
        wsRef.current.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'realtime_update') {
              setStats(data.stats);
              setDetectedPersons(data.persons);
              if (data.frame) {
                setCurrentFrame(`data:image/jpeg;base64,${data.frame}`);
              }
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };
        
        wsRef.current.onclose = () => {
          console.log('WebSocket disconnected, attempting to reconnect...');
          setTimeout(connectWebSocket, 3000);
        };
        
        wsRef.current.onerror = (error) => {
          console.error('WebSocket error:', error);
        };
      } catch (error) {
        console.error('Error connecting to WebSocket:', error);
      }
    };

    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Load configuration on mount
  useEffect(() => {
    loadConfiguration();
    loadCurrentRoi();
  }, []);

  const loadConfiguration = async () => {
    try {
      const response = await axios.get(`${API}/config/detection`);
      setConfig(response.data);
    } catch (error) {
      console.error('Error loading configuration:', error);
    }
  };

  const loadCurrentRoi = async () => {
    try {
      const response = await axios.get(`${API}/roi/current`);
      setCurrentRoi(response.data);
    } catch (error) {
      console.error('Error loading ROI:', error);
    }
  };

  const startVideoProcessing = async () => {
    try {
      let sourcePath = videoSource;
      
      // Handle different source types
      if (sourceType === 'webcam') {
        sourcePath = videoSource || '0';
      }
      
      const response = await axios.post(`${API}/video/start`, {
        source_type: sourceType,
        source_path: sourcePath,
        name: `${sourceType} - ${sourcePath}`
      });
      
      setIsProcessing(true);
      console.log('Video processing started:', response.data);
    } catch (error) {
      console.error('Error starting video processing:', error);
      alert('Failed to start video processing. Please check your video source.');
    }
  };

  const stopVideoProcessing = async () => {
    try {
      await axios.post(`${API}/video/stop`);
      setIsProcessing(false);
      setCurrentFrame(null);
      setDetectedPersons([]);
      console.log('Video processing stopped');
    } catch (error) {
      console.error('Error stopping video processing:', error);
    }
  };

  const updateDetectionConfig = async () => {
    try {
      await axios.post(`${API}/config/detection`, config);
      alert('Configuration updated successfully!');
    } catch (error) {
      console.error('Error updating configuration:', error);
      alert('Failed to update configuration.');
    }
  };

  const handleCanvasClick = (event) => {
    if (!roiMode || !canvasRef.current) return;
    
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    const x = Math.round((event.clientX - rect.left) * scaleX);
    const y = Math.round((event.clientY - rect.top) * scaleY);
    
    setRoiPoints([...roiPoints, [x, y]]);
  };

  const setRoi = async () => {
    try {
      if (roiPoints.length < 3) {
        alert('ROI requires at least 3 points');
        return;
      }
      
      await axios.post(`${API}/roi/set`, {
        coordinates: roiPoints,
        enabled: true
      });
      
      setCurrentRoi({ enabled: true, coordinates: roiPoints });
      setRoiMode(false);
      setRoiPoints([]);
      alert('ROI set successfully!');
    } catch (error) {
      console.error('Error setting ROI:', error);
      alert('Failed to set ROI.');
    }
  };

  const clearRoi = async () => {
    try {
      await axios.post(`${API}/roi/set`, {
        coordinates: [],
        enabled: false
      });
      
      setCurrentRoi({ enabled: false, coordinates: [] });
      setRoiPoints([]);
      alert('ROI cleared successfully!');
    } catch (error) {
      console.error('Error clearing ROI:', error);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      await axios.post(`${API}/video/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      setIsProcessing(true);
      alert('Video file uploaded and processing started!');
    } catch (error) {
      console.error('Error uploading file:', error);
      alert('Failed to upload video file.');
    }
  };

  // Draw ROI points on canvas
  useEffect(() => {
    if (!canvasRef.current || !currentFrame) return;
    
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const img = new Image();
    
    img.onload = () => {
      canvas.width = 800;
      canvas.height = 600;
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      
      // Draw ROI points if in ROI mode
      if (roiMode && roiPoints.length > 0) {
        ctx.strokeStyle = '#00ff00';
        ctx.fillStyle = '#00ff00';
        ctx.lineWidth = 2;
        
        roiPoints.forEach((point, index) => {
          ctx.beginPath();
          ctx.arc(point[0], point[1], 5, 0, 2 * Math.PI);
          ctx.fill();
          
          // Draw line to next point
          if (index < roiPoints.length - 1) {
            ctx.beginPath();
            ctx.moveTo(point[0], point[1]);
            ctx.lineTo(roiPoints[index + 1][0], roiPoints[index + 1][1]);
            ctx.stroke();
          }
        });
        
        // Close polygon if we have more than 2 points
        if (roiPoints.length > 2) {
          ctx.beginPath();
          ctx.moveTo(roiPoints[roiPoints.length - 1][0], roiPoints[roiPoints.length - 1][1]);
          ctx.lineTo(roiPoints[0][0], roiPoints[0][1]);
          ctx.stroke();
        }
      }
    };
    
    img.src = currentFrame;
  }, [currentFrame, roiMode, roiPoints]);

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="bg-gray-800 shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <h1 className="text-2xl font-bold text-blue-400">
                  Idle Person Detection System
                </h1>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <div className={`px-3 py-1 rounded-full text-sm font-medium ${
                isProcessing ? 'bg-green-600' : 'bg-red-600'
              }`}>
                {isProcessing ? 'Processing' : 'Stopped'}
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Video Display */}
          <div className="lg:col-span-2">
            <div className="bg-gray-800 rounded-lg shadow-lg p-6">
              <h2 className="text-xl font-semibold mb-4">Live Video Feed</h2>
              <div className="relative">
                {currentFrame ? (
                  <canvas
                    ref={canvasRef}
                    onClick={handleCanvasClick}
                    className={`w-full h-auto border-2 rounded-lg ${
                      roiMode ? 'border-green-400 cursor-crosshair' : 'border-gray-600'
                    }`}
                    style={{ maxHeight: '500px' }}
                  />
                ) : (
                  <div className="w-full h-64 bg-gray-700 rounded-lg flex items-center justify-center">
                    <p className="text-gray-400">No video feed available</p>
                  </div>
                )}
                
                {roiMode && (
                  <div className="absolute top-2 left-2 bg-green-600 text-white px-3 py-1 rounded">
                    ROI Mode: Click to add points ({roiPoints.length} points)
                  </div>
                )}
              </div>
            </div>

            {/* Statistics */}
            <div className="bg-gray-800 rounded-lg shadow-lg p-6 mt-6">
              <h2 className="text-xl font-semibold mb-4">Real-time Statistics</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-blue-600 rounded-lg p-4">
                  <div className="text-2xl font-bold">{stats.active_persons}</div>
                  <div className="text-sm opacity-80">Active Persons</div>
                </div>
                <div className="bg-red-600 rounded-lg p-4">
                  <div className="text-2xl font-bold">{stats.idle_persons}</div>
                  <div className="text-sm opacity-80">Idle Persons</div>
                </div>
                <div className="bg-green-600 rounded-lg p-4">
                  <div className="text-2xl font-bold">{stats.processing_fps?.toFixed(1) || '0.0'}</div>
                  <div className="text-sm opacity-80">Processing FPS</div>
                </div>
                <div className="bg-purple-600 rounded-lg p-4">
                  <div className="text-2xl font-bold">{stats.total_detections || 0}</div>
                  <div className="text-sm opacity-80">Total Detections</div>
                </div>
              </div>
            </div>
          </div>

          {/* Control Panel */}
          <div className="space-y-6">
            {/* Video Source Control */}
            <div className="bg-gray-800 rounded-lg shadow-lg p-6">
              <h2 className="text-xl font-semibold mb-4">Video Source</h2>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Source Type</label>
                  <select
                    value={sourceType}
                    onChange={(e) => setSourceType(e.target.value)}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={isProcessing}
                  >
                    <option value="webcam">Webcam</option>
                    <option value="rtsp">RTSP Stream</option>
                    <option value="file">Video File</option>
                  </select>
                </div>

                {sourceType !== 'file' && (
                  <div>
                    <label className="block text-sm font-medium mb-2">
                      {sourceType === 'webcam' ? 'Camera Index (0, 1, 2...)' : 'RTSP URL'}
                    </label>
                    <input
                      type="text"
                      value={videoSource}
                      onChange={(e) => setVideoSource(e.target.value)}
                      placeholder={sourceType === 'webcam' ? '0' : 'rtsp://username:password@ip:port/stream'}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      disabled={isProcessing}
                    />
                  </div>
                )}

                {sourceType === 'file' && (
                  <div>
                    <label className="block text-sm font-medium mb-2">Upload Video File</label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="video/*"
                      onChange={handleFileUpload}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      disabled={isProcessing}
                    />
                  </div>
                )}

                <div className="flex space-x-2">
                  <button
                    onClick={startVideoProcessing}
                    disabled={isProcessing || (sourceType !== 'file' && !videoSource)}
                    className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed px-4 py-2 rounded-md font-medium transition-colors"
                  >
                    Start Processing
                  </button>
                  <button
                    onClick={stopVideoProcessing}
                    disabled={!isProcessing}
                    className="flex-1 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed px-4 py-2 rounded-md font-medium transition-colors"
                  >
                    Stop Processing
                  </button>
                </div>
              </div>
            </div>

            {/* ROI Configuration */}
            <div className="bg-gray-800 rounded-lg shadow-lg p-6">
              <h2 className="text-xl font-semibold mb-4">Region of Interest (ROI)</h2>
              
              <div className="space-y-4">
                <div className="flex space-x-2">
                  <button
                    onClick={() => {
                      setRoiMode(!roiMode);
                      setRoiPoints([]);
                    }}
                    className={`flex-1 px-4 py-2 rounded-md font-medium transition-colors ${
                      roiMode 
                        ? 'bg-yellow-600 hover:bg-yellow-700' 
                        : 'bg-blue-600 hover:bg-blue-700'
                    }`}
                    disabled={!currentFrame}
                  >
                    {roiMode ? 'Cancel ROI' : 'Set ROI'}
                  </button>
                </div>

                {roiMode && (
                  <div className="space-y-2">
                    <button
                      onClick={setRoi}
                      disabled={roiPoints.length < 3}
                      className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed px-4 py-2 rounded-md font-medium transition-colors"
                    >
                      Apply ROI ({roiPoints.length} points)
                    </button>
                    <button
                      onClick={() => setRoiPoints([])}
                      className="w-full bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-md font-medium transition-colors"
                    >
                      Clear Points
                    </button>
                  </div>
                )}

                {currentRoi.enabled && (
                  <div className="space-y-2">
                    <div className="text-sm text-green-400">
                      ✓ ROI Active ({currentRoi.coordinates?.length} points)
                    </div>
                    <button
                      onClick={clearRoi}
                      className="w-full bg-red-600 hover:bg-red-700 px-4 py-2 rounded-md font-medium transition-colors"
                    >
                      Clear ROI
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Detection Configuration */}
            <div className="bg-gray-800 rounded-lg shadow-lg p-6">
              <h2 className="text-xl font-semibold mb-4">Detection Settings</h2>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Confidence Threshold: {(config.confidence_threshold * 100).toFixed(0)}%
                  </label>
                  <input
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.1"
                    value={config.confidence_threshold}
                    onChange={(e) => setConfig({...config, confidence_threshold: parseFloat(e.target.value)})}
                    className="w-full"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">
                    Movement Threshold: {config.movement_threshold} pixels
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="100"
                    step="5"
                    value={config.movement_threshold}
                    onChange={(e) => setConfig({...config, movement_threshold: parseInt(e.target.value)})}
                    className="w-full"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">
                    Idle Alert Threshold: {config.idle_alert_threshold} seconds
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="120"
                    step="5"
                    value={config.idle_alert_threshold}
                    onChange={(e) => setConfig({...config, idle_alert_threshold: parseInt(e.target.value)})}
                    className="w-full"
                  />
                </div>

                <button
                  onClick={updateDetectionConfig}
                  className="w-full bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-md font-medium transition-colors"
                >
                  Update Configuration
                </button>
              </div>
            </div>

            {/* Detected Persons */}
            <div className="bg-gray-800 rounded-lg shadow-lg p-6">
              <h2 className="text-xl font-semibold mb-4">Detected Persons</h2>
              
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {detectedPersons.length > 0 ? (
                  detectedPersons.map((person) => (
                    <div
                      key={person.id}
                      className={`p-3 rounded-lg border-l-4 ${
                        person.is_idle 
                          ? 'bg-red-900 border-red-500' 
                          : 'bg-green-900 border-green-500'
                      }`}
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <div className="font-medium">ID: {person.id.slice(0, 8)}...</div>
                          <div className="text-sm opacity-80">
                            Status: {person.is_idle ? 'IDLE' : 'ACTIVE'}
                          </div>
                          {person.is_idle && (
                            <div className="text-sm text-red-400">
                              Idle for: {person.idle_duration?.toFixed(0)}s
                            </div>
                          )}
                        </div>
                        <div className="text-sm opacity-80">
                          Confidence: {(person.confidence * 100).toFixed(0)}%
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-gray-400 text-center py-4">
                    No persons detected
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;