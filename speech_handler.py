from fastapi import APIRouter, HTTPException, UploadFile, File
import speech_recognition as sr
import os
import uuid
from query_handler import process_query, QueryRequest

router = APIRouter()

# Directory for storing uploaded audio files
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/speech-to-chatbot")
async def speech_to_chatbot(audio_file: UploadFile = File(...)):
    """Converts speech to text and sends it to the chatbot."""
    
    # Generate a secure filename
    file_ext = os.path.splitext(audio_file.filename)[-1].lower()
    secure_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, secure_filename)
    
    try:
        # Save uploaded file
        with open(file_path, "wb") as buffer:
            buffer.write(await audio_file.read())
        
        # Initialize recognizer and process audio
        recognizer = sr.Recognizer()
        with sr.AudioFile(file_path) as source:
            audio_data = recognizer.record(source)
            recognized_text = recognizer.recognize_google(audio_data)
        
        # Process query and return response
        return process_query(QueryRequest(user_input=recognized_text))
    
    except sr.UnknownValueError:
        raise HTTPException(status_code=400, detail="Could not understand the audio. Please try again.")
    except sr.RequestError:
        raise HTTPException(status_code=500, detail="Speech-to-text service is temporarily unavailable.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
    
    finally:
        # Clean up: Remove saved audio file after processing
        if os.path.exists(file_path):
            os.remove(file_path)
