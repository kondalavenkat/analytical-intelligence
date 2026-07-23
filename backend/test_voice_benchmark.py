import requests
import wave
import struct
import time
import os

BASE_URL = "http://localhost:8000"

def create_dummy_wav(filename="dummy.wav"):
    """Creates a 1-second silent wav file for testing."""
    sample_rate = 16000
    with wave.open(filename, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        for _ in range(sample_rate):
            f.writeframesraw(struct.pack('<h', 0))

def test_transcription():
    # 1. Login to get token
    print("Logging in to get JWT token...")
    login_resp = requests.post(f"{BASE_URL}/auth/login", json={
        "email": "admin",
        "password": "Admin@123"
    })
    
    if login_resp.status_code != 200:
        print("Login failed!", login_resp.text)
        return
        
    token = login_resp.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Create and send audio file
    create_dummy_wav("dummy.wav")
    
    print("Testing /voice/transcribe endpoint...")
    
    with open("dummy.wav", "rb") as f:
        files = {"file": ("dummy.wav", f, "audio/wav")}
        
        # Start timer for client-side latency
        client_start = time.time()
        
        response = requests.post(
            f"{BASE_URL}/voice/transcribe", 
            headers=headers,
            files=files
        )
        
        client_latency_ms = round((time.time() - client_start) * 1000, 2)
        
    if response.status_code == 200:
        data = response.json()
        print("\n✅ Success!")
        print(f"Transcribed Text: '{data.get('text')}'")
        print(f"Backend Server Latency: {data.get('latency_ms')} ms")
        print(f"Total Client-Side Latency: {client_latency_ms} ms")
        
        if data.get('latency_ms', float('inf')) < 1500:
            print("🚀 Benchmark passed! Backend latency is under 1.5s.")
        else:
            print("⚠️ Benchmark failed! Backend latency is over 1.5s.")
    else:
        print(f"❌ Failed: {response.status_code}")
        print(response.text)
        
    # Cleanup
    if os.path.exists("dummy.wav"):
        os.remove("dummy.wav")

if __name__ == "__main__":
    test_transcription()
