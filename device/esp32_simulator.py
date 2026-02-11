#!/usr/bin/env python3
"""
ESP32 Simulator for testing without physical hardware.
Simulates audio streaming and image capture.
"""

import asyncio
import websockets
import json
import time
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ESP32Simulator:
    """Simulates ESP32 device behavior"""
    
    def __init__(self, server_url: str, audio_file: str = None, image_file: str = None):
        self.server_url = server_url
        self.audio_file = audio_file
        self.image_file = image_file
        self.ws_audio = None
        self.ws_ctrl = None
        self.ws_camera = None
        self.running = False
        
    async def connect_audio(self):
        """Connect to audio WebSocket"""
        url = f"{self.server_url}/ws_audio"
        logger.info(f"Connecting to audio endpoint: {url}")
        
        try:
            self.ws_audio = await websockets.connect(url)
            logger.info("Audio WebSocket connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect audio: {e}")
            return False
    
    async def connect_ctrl(self):
        """Connect to control WebSocket"""
        url = f"{self.server_url}/ws_ctrl"
        logger.info(f"Connecting to control endpoint: {url}")
        
        try:
            self.ws_ctrl = await websockets.connect(url)
            logger.info("Control WebSocket connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect control: {e}")
            return False
    
    async def connect_camera(self):
        """Connect to camera WebSocket"""
        url = f"{self.server_url}/ws_camera"
        logger.info(f"Connecting to camera endpoint: {url}")
        
        try:
            self.ws_camera = await websockets.connect(url)
            logger.info("Camera WebSocket connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect camera: {e}")
            return False
    
    async def stream_audio(self):
        """Stream audio data"""
        if not self.ws_audio:
            logger.error("Audio WebSocket not connected")
            return
        
        if self.audio_file and Path(self.audio_file).exists():
            logger.info(f"Streaming audio from file: {self.audio_file}")
            
            with open(self.audio_file, 'rb') as f:
                audio_data = f.read()
            
            # Send in chunks (100ms = 3200 bytes for 16kHz mono PCM16)
            chunk_size = 3200
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i+chunk_size]
                await self.ws_audio.send(chunk)
                await asyncio.sleep(0.1)  # 100ms
                
            logger.info("Audio streaming complete")
        else:
            # Send dummy audio chunks
            logger.info("Sending dummy audio chunks")
            chunk = b'\x00' * 3200  # Silent audio
            
            for _ in range(50):  # 5 seconds
                await self.ws_audio.send(chunk)
                await asyncio.sleep(0.1)
    
    async def listen_for_capture(self):
        """Listen for CAPTURE commands"""
        if not self.ws_ctrl:
            logger.error("Control WebSocket not connected")
            return
        
        logger.info("Listening for CAPTURE commands...")
        
        try:
            async for message in self.ws_ctrl:
                data = json.loads(message)
                
                if data.get("type") == "CAPTURE":
                    req_id = data.get("req_id")
                    logger.info(f"Received CAPTURE command: req_id={req_id}")
                    
                    # Send image
                    await self.send_image(req_id)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("Control connection closed")
        except Exception as e:
            logger.error(f"Error listening for capture: {e}")
    
    async def send_image(self, req_id: str):
        """Send image to server"""
        if not self.ws_camera:
            logger.error("Camera WebSocket not connected")
            return
        
        # Read image file or use dummy data
        if self.image_file and Path(self.image_file).exists():
            logger.info(f"Sending image from file: {self.image_file}")
            with open(self.image_file, 'rb') as f:
                image_data = f.read()
        else:
            # Create minimal JPEG (1x1 pixel)
            logger.info("Sending dummy image")
            image_data = bytes.fromhex(
                'ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707'
                '07090909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c'
                '231c1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b'
                '0c180d0d1832211c213232323232323232323232323232323232323232323232323232'
                '32323232323232323232323232323232323232323232ffc00011080001000103011100'
                '021101031101ffc4001500010100000000000000000000000000000000ffc400140001'
                '0000000000000000000000000000000000ffda000c03010002110311003f00bf800000'
                '00ffd9'
            )
        
        # Send JSON header
        header = {
            "req_id": req_id,
            "size": len(image_data),
            "format": "jpeg"
        }
        
        await self.ws_camera.send(json.dumps(header))
        logger.info(f"Sent image header: {header}")
        
        # Send binary image data
        await self.ws_camera.send(image_data)
        logger.info(f"Sent image data: {len(image_data)} bytes")
        
        # Wait for acknowledgment
        response = await self.ws_camera.recv()
        result = json.loads(response)
        logger.info(f"Server response: {result}")
    
    async def run(self):
        """Run simulator"""
        self.running = True
        
        # Connect all WebSockets
        await self.connect_audio()
        await self.connect_ctrl()
        await self.connect_camera()
        
        # Start tasks
        tasks = []
        
        if self.ws_audio:
            tasks.append(asyncio.create_task(self.stream_audio()))
        
        if self.ws_ctrl:
            tasks.append(asyncio.create_task(self.listen_for_capture()))
        
        # Wait for all tasks
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("Simulator stopped")
    
    async def close(self):
        """Close all connections"""
        self.running = False
        
        if self.ws_audio:
            await self.ws_audio.close()
        if self.ws_ctrl:
            await self.ws_ctrl.close()
        if self.ws_camera:
            await self.ws_camera.close()


async def main():
    parser = argparse.ArgumentParser(description="ESP32 Simulator")
    parser.add_argument("--server", default="ws://localhost:8000", help="Server URL")
    parser.add_argument("--audio", help="Audio file (PCM16)")
    parser.add_argument("--image", help="Image file (JPEG)")
    
    args = parser.parse_args()
    
    simulator = ESP32Simulator(
        server_url=args.server,
        audio_file=args.audio,
        image_file=args.image
    )
    
    try:
        await simulator.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await simulator.close()


if __name__ == "__main__":
    asyncio.run(main())
