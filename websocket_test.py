import asyncio
import websockets
import ssl
import json

async def test_websocket():
    uri = "wss://0421f659-b986-4b39-9da8-3f4cbeb0ff72.preview.emergentagent.com/ws"
    print(f"Connecting to WebSocket: {uri}")
    
    try:
        # Disable SSL verification for testing
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            print("Connected to WebSocket")
            
            # Wait for messages for 10 seconds
            for _ in range(5):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(message)
                    print(f"Received message type: {data.get('type', 'unknown')}")
                    print(f"Stats: {data.get('stats', {})}")
                    print(f"Persons detected: {len(data.get('persons', []))}")
                    print(f"Frame data length: {len(data.get('frame', ''))}")
                    print("-" * 50)
                except asyncio.TimeoutError:
                    print("No message received (timeout)")
                except Exception as e:
                    print(f"Error receiving message: {e}")
            
            print("WebSocket test completed")
    except Exception as e:
        print(f"WebSocket connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())