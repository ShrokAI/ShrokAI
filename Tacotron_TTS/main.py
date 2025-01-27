from flask import Flask, request, jsonify
from TTS.api import TTS
from pydub import AudioSegment
import os
import uuid
import paramiko  # For file transfer via SCP
import logging
import subprocess

# Logging setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger()

app = Flask(__name__, static_folder="static")

# Initialize TTS model
MODEL_NAME = "tts_models/en/ljspeech/tacotron2-DDC"
tts = TTS(MODEL_NAME, progress_bar=False)
logger.info("TTS model initialized: %s", MODEL_NAME)

# VPS settings
VPS_HOST = ""  # Your VPS IP address
VPS_USERNAME = ""  # Username
VPS_PASSWORD = ""  # Password
VPS_DEST_PATH = "/tmp/tts_files"  # Path for storing files on VPS

STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
logger.info("Static directory created: %s", STATIC_DIR)

# Check for ffmpeg installation
def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("ffmpeg is installed.")
    except FileNotFoundError:
        logger.error("ffmpeg is not installed. Please install ffmpeg.")
        raise Exception("ffmpeg is required but not installed.")
    except subprocess.CalledProcessError as e:
        logger.error("Error checking ffmpeg version: %s", e)
        raise

check_ffmpeg()  # Verify ffmpeg availability before processing audio

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "SHROKAI TTS is running!"})

def get_audio_length(file_path):
    """
    Determines the length of an audio file (in seconds).
    """
    try:
        audio = AudioSegment.from_file(file_path)
        duration = len(audio) / 1000  # Convert milliseconds to seconds
        return round(duration, 2)  # Round to 2 decimal places
    except Exception as e:
        logger.error("Error getting audio length: %s", str(e))
        return 0

@app.route("/generate", methods=["POST"])
def generate_audio():
    try:
        logger.info("Received request to generate audio.")

        # Get text from the request
        data = request.get_json()
        text = data.get("text", "")
        logger.debug("Text received: %s", text)

        if not text:
            logger.error("No text provided in the request.")
            return jsonify({"error": "Text is required"}), 400

        # Generate a file name
        output_filename = f"{uuid.uuid4().hex}.wav"
        output_path = os.path.join(STATIC_DIR, output_filename)
        logger.debug("Generated output file path: %s", output_path)

        # Generate audio
        tts.tts_to_file(text=text, file_path=output_path)
        logger.info("Audio file generated: %s", output_path)

        # Adjust pitch
        processed_filename = f"processed_{uuid.uuid4().hex}.wav"
        processed_path = os.path.join(STATIC_DIR, processed_filename)
        lower_pitch(output_path, processed_path)
        logger.info("Processed audio file created: %s", processed_path)

        # Convert to OGG
        ogg_filename = f"{uuid.uuid4().hex}.ogg"
        ogg_path = os.path.join(STATIC_DIR, ogg_filename)
        convert_to_ogg(processed_path, ogg_path)
        logger.info("Converted to OGG: %s", ogg_path)

        # Check if file exists
        if not os.path.exists(ogg_path):
            logger.error("OGG file not found.")
            return jsonify({"error": "OGG file not found."}), 500

        # Determine audio file length
        audio_length = get_audio_length(ogg_path)
        logger.info("Audio length calculated: %s seconds", audio_length)

        # Send file to VPS
        logger.info("Attempting to send file to VPS: %s", VPS_HOST)
        send_file_to_vps(ogg_path)

        # Delete temporary files
        os.remove(output_path)
        os.remove(processed_path)
        os.remove(ogg_path)
        logger.info("Temporary files deleted.")

        # Return audio file length in the response
        return jsonify({
            "status": "success",
            "message": "File sent to VPS successfully.",
            "audio_length": audio_length
        })

    except Exception as e:
        logger.error("Error during audio generation: %s", str(e))
        return jsonify({"error": str(e)}), 500

def lower_pitch(input_path, output_path):
    """
    Lowers the pitch of the audio with a fixed pitch_factor = 0.6.
    """
    try:
        logger.info("Lowering pitch of the audio.")
        pitch_factor = 0.6
        audio = AudioSegment.from_file(input_path)
        audio = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * pitch_factor)
        }).set_frame_rate(audio.frame_rate)
        audio.export(output_path, format="wav")
        logger.info("Pitch adjustment complete: %s", output_path)
    except Exception as e:
        logger.error("Error lowering pitch: %s", str(e))
        raise

def convert_to_ogg(input_path, output_path):
    """
    Converts a WAV file to OGG.
    """
    try:
        logger.info("Converting to OGG.")
        subprocess.run(["ffmpeg", "-i", input_path, "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k", output_path], check=True)
        logger.info("Conversion complete: %s", output_path)
    except Exception as e:
        logger.error("Error converting to OGG: %s", str(e))
        raise

def send_file_to_vps(file_path):
    """
    Sends a file to a VPS via SCP.
    """
    try:
        logger.info("Connecting to VPS at %s", VPS_HOST)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VPS_HOST, username=VPS_USERNAME, password=VPS_PASSWORD)
        logger.info("Connected to VPS successfully.")

        # Transfer file
        sftp = ssh.open_sftp()
        dest_path = os.path.join(VPS_DEST_PATH, os.path.basename(file_path))
        sftp.put(file_path, dest_path)
        sftp.close()
        ssh.close()
        logger.info("File successfully sent to VPS: %s", file_path)

    except Exception as e:
        logger.error("Error sending file to VPS: %s", str(e))
        raise

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)