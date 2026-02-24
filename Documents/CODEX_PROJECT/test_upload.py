#!/usr/bin/env python3
"""
Simple test script to upload an image to EC2 backend
Usage: python test_upload.py <image_file> [server_url]
"""

import sys
import requests
import time

def test_http_upload(image_path, server_url="http://localhost:8000"):
    """Test image upload via HTTP POST"""
    print(f"Testing HTTP upload to {server_url}")
    print(f"Image file: {image_path}")
    
    try:
        with open(image_path, 'rb') as f:
            files = {'file': (image_path, f, 'image/jpeg')}
            data = {'req_id': f'test-{int(time.time())}'}
            
            print("Uploading...")
            response = requests.post(
                f"{server_url}/api/upload_image",
                files=files,
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Upload successful!")
                print(f"   Filename: {result['filename']}")
                print(f"   Size: {result['size']} bytes")
                print(f"   Path: {result['path']}")
            else:
                print(f"❌ Upload failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
    except FileNotFoundError:
        print(f"❌ Error: Image file not found: {image_path}")
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to server at {server_url}")
        print("   Make sure the backend is running!")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_websocket_upload(image_path, server_url="ws://localhost:8000"):
    """Test image upload via WebSocket"""
    print(f"\nTesting WebSocket upload to {server_url}")
    print(f"Image file: {image_path}")
    
    try:
        import websocket
        import json
        
        ws_url = f"{server_url}/ws_camera"
        print(f"Connecting to {ws_url}...")
        
        ws = websocket.create_connection(ws_url)
        print("✅ Connected!")
        
        # Read image
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        # Send JSON header
        header = {
            "req_id": f"test-ws-{int(time.time())}",
            "size": len(image_data),
            "format": "jpeg"
        }
        print(f"Sending header: {header}")
        ws.send(json.dumps(header))
        
        # Send binary image data
        print(f"Sending image data ({len(image_data)} bytes)...")
        ws.send(image_data, opcode=websocket.ABNF.OPCODE_BINARY)
        
        # Receive acknowledgment
        response = ws.recv()
        result = json.loads(response)
        
        if result.get("status") == "success":
            print("✅ Upload successful!")
            print(f"   Filename: {result['filename']}")
            print(f"   Size: {result['size']} bytes")
        else:
            print(f"❌ Upload failed: {result}")
        
        ws.close()
        
    except FileNotFoundError:
        print(f"❌ Error: Image file not found: {image_path}")
    except ImportError:
        print("❌ Error: websocket-client not installed")
        print("   Install it with: pip install websocket-client")
    except Exception as e:
        print(f"❌ Error: {e}")

def check_server_health(server_url="http://localhost:8000"):
    """Check if server is running"""
    print(f"Checking server health at {server_url}...")
    try:
        response = requests.get(f"{server_url}/api/health", timeout=5)
        if response.status_code == 200:
            health = response.json()
            print("✅ Server is running!")
            print(f"   Status: {health['status']}")
            print(f"   Images stored: {health['images_stored']}")
            return True
        else:
            print(f"❌ Server returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to server at {server_url}")
        print("   Make sure the backend is running!")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_upload.py <image_file> [server_url]")
        print("Example: python test_upload.py test.jpg http://your-ec2-ip:8000")
        sys.exit(1)
    
    image_path = sys.argv[1]
    server_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    
    # Remove trailing slash
    server_url = server_url.rstrip('/')
    
    # Check server health first
    if not check_server_health(server_url):
        sys.exit(1)
    
    print("\n" + "="*60)
    
    # Test HTTP upload
    test_http_upload(image_path, server_url)
    
    print("\n" + "="*60)
    
    # Test WebSocket upload
    ws_url = server_url.replace('http://', 'ws://').replace('https://', 'wss://')
    test_websocket_upload(image_path, ws_url)
    
    print("\n" + "="*60)
    print("\n✅ Testing complete!")
