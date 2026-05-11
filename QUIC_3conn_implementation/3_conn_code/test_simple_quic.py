#!/usr/bin/env python3
"""Simple test of QUIC server/client connectivity."""

import asyncio
import sys
from pathlib import Path
from aioquic.asyncio import serve, connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

class SimpleServerProtocol:
    def __init__(self, *args, **kwargs):
        print("[Server] Protocol created")

    def quic_event_received(self, event):
        print(f"[Server] Event: {type(event).__name__}")

async def test_server():
    """Run the server side."""
    print("[Server] Starting QUIC server on localhost:4433")
    
    config = QuicConfiguration(is_client=False, max_datagram_frame_size=65536)
    config.load_cert_chain("certs/cert.pem", "certs/key.pem")
    
    server = await serve(
        "localhost",
        4433,
        configuration=config,
        create_protocol=lambda *args, **kwargs: SimpleServerProtocol(*args, **kwargs),
    )
    print("[Server] Server started successfully")
    return server

async def test_client():
    """Run the client side."""
    await asyncio.sleep(1)  # Wait for server to start
    print("[Client] Attempting to connect...")
    
    config = QuicConfiguration(is_client=True)
    config.verify_mode = False
    
    try:
        async with connect("localhost", 4433, configuration=config) as protocol:
            print("[Client] Connected successfully!")
            return True
    except Exception as e:
        print(f"[Client] Connection failed: {type(e).__name__}: {e}")
        return False

async def main():
    server = await test_server()
    
    # Run client with timeout
    try:
        result = await asyncio.wait_for(test_client(), timeout=10)
        if result:
            print("[Test] SUCCESS: Client connected to server")
        else:
            print("[Test] FAILED: Client could not connect")
    except asyncio.TimeoutError:
        print("[Test] FAILED: Client connection timed out after 10 seconds")
    except Exception as e:
        print(f"[Test] ERROR: {e}")
    finally:
        server.close()

if __name__ == "__main__":
    asyncio.run(main())
