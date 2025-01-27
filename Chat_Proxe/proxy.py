from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import websockets
import json

# Initialize FastAPI
app = FastAPI()

# List of active WebSocket connections
active_connections = set()

# Queue for incoming user requests
message_queue = asyncio.Queue()

# AI Server WebSocket URL
AI_SERVER_URL = ""

# Global status variables
is_processing = False  # Is the AI currently processing?
block_time = 0  # Time to block before accepting the next request

# Messages to users
WELCOME_MESSAGE = "Mention @ShrokAI, and I’ll respond… probably. If I’m not lost in a mushroom trip."
BUSY_MESSAGE = "Thinking... but the mushrooms are taking over my brain. Give me a bit more time."
REQUEST_RECEIVED_MESSAGE = "Got it, let me think about my response."

async def process_queue():
    """Function to process incoming messages from the queue."""
    global is_processing

    while True:
        message, websocket = await message_queue.get()

        # ✅ Mark AI as busy as soon as a request enters processing
        if is_processing:
            print("[BUSY] AI is already processing, sending placeholder response to the client.")
            try:
                await websocket.send_text(BUSY_MESSAGE)
            except WebSocketDisconnect:
                print("[DISCONNECT] Client disconnected during placeholder response.")
            continue  # Skip processing and wait for the next request

        # AI is now processing
        is_processing = True
        print(f"[PROCESSING] AI accepted a new request: {message}")

        # Notify the user that the request has been received
        try:
            await websocket.send_text(REQUEST_RECEIVED_MESSAGE)
        except WebSocketDisconnect:
            print("[DISCONNECT] Client disconnected during 'Request received' message.")

        # Start processing the request
        response = await forward_to_ai(message)

        # Extract only the text response (remove `audio_length`)
        if isinstance(response, dict) and "response" in response:
            filtered_response = response["response"]
        else:
            filtered_response = response

        # Broadcast the AI response to all connected users
        for connection in list(active_connections):
            try:
                await connection.send_text(filtered_response)
            except Exception as e:
                print(f"[ERROR] Failed to send response to client: {e}")
                active_connections.remove(connection)

        # Unlock processing for new requests
        asyncio.create_task(unblock_after_delay())

async def forward_to_ai(message: str):
    """Sends the request to the AI server and retrieves the response."""
    global is_processing, block_time

    print(f"[FORWARD] Sending request to AI: {message}")

    try:
        async with websockets.connect(AI_SERVER_URL, ping_interval=10, ping_timeout=None) as ai_ws:
            await ai_ws.send(message)

            while True:
                try:
                    response = await ai_ws.recv()  # 🔥 Wait indefinitely for a response
                except websockets.ConnectionClosed:
                    print("[ERROR] AI WebSocket connection unexpectedly closed!")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                try:
                    data = json.loads(response)
                except json.JSONDecodeError:
                    print(f"[ERROR] Failed to decode JSON: {response}")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                # 🔥 Ignore "processing" signals and wait for a real response
                if "processing" in data:
                    print("[INFO] AI confirmed processing, waiting for a real response...")
                    continue  

                # Process the actual response
                if "response" not in data or "audio_length" not in data:
                    print(f"[ERROR] Invalid JSON response from AI: {data}")
                    return "Overdosed on swamp shrooms—brain.exe not found."

                block_time = data["audio_length"] + 10  # Block new requests for the specified time
                print(f"[FORWARD] Received response from AI: {data['response']} (block_time={block_time}s)")

                return data  # Return the full response

    except Exception as e:
        print(f"[ERROR] Failed to connect to AI server: {e}")
        return "Overdosed on swamp shrooms—brain.exe not found."

@app.websocket("/ws/proxy")
async def proxy_websocket(websocket: WebSocket):
    global is_processing
    await websocket.accept()
    active_connections.add(websocket)
    
    print(f"[CONNECT] New client connected ({len(active_connections)} total).")

    # Send a welcome message
    await websocket.send_text(WELCOME_MESSAGE)
    
    try:
        while True:
            message = await websocket.receive_text()
            print(f"[MESSAGE] Received message: {message}")

            # ✅ Immediately check AI status and send a placeholder if busy
            if is_processing:
                print("[BUSY] AI is currently busy, instantly sending placeholder response.")
                await websocket.send_text(BUSY_MESSAGE)
                continue  # Skip adding the request to the queue

            # Add the request to the queue
            await message_queue.put((message, websocket))

    except WebSocketDisconnect:
        print("[DISCONNECT] Client disconnected.")
        active_connections.remove(websocket)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        await websocket.close(code=1001)

async def unblock_after_delay():
    """Function to unlock processing after a delay."""
    global is_processing
    print(f"[TIMER] Blocking requests for {block_time} seconds...")
    await asyncio.sleep(block_time)
    is_processing = False
    print("[TIMER] AI is free again, ready to accept new requests.")

# Start queue processing in the background
asyncio.create_task(process_queue())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)