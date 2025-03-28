import yt_dlp
import speech_recognition as sr
from pydub import AudioSegment
import os
import re

# Set FFmpeg paths for desktop
os.environ["PATH"] += os.pathsep + r"D:\Coding\ffmpeg\bin"
AudioSegment.converter = r"D:\Coding\ffmpeg\bin\ffmpeg.exe"
AudioSegment.ffprobe   = r"D:\Coding\ffmpeg\bin\ffprobe.exe"

url = "https://www.youtube.com/watch?v=wfIsVBvbWEs"  # Trump Speech Jan 2025
print("Connecting to YouTube...")
ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': 'test_audio.%(ext)s',
    'overwrite': True,
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    print("Downloading audio...")
    ydl.download([url])
    print("Audio downloaded!")

# Convert webm to wav (trim to 59 seconds)
print("Converting audio...")
audio = AudioSegment.from_file("test_audio.webm")
audio = audio[:59000]  # Trim to 59 seconds
audio.export("test_audio.wav", format="wav")
print("Conversion complete!")

# Transcribe and filter
recognizer = sr.Recognizer()
print("Transcribing audio...")
with sr.AudioFile("test_audio.wav") as source:
    audio_data = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio_data)
        print("Transcription:", text)

        # Filter with context (whole words only)
        bad_words = ["damn", "hell", "stupid", "crap", "ass", "shit", "fuck", "bitch", 
                     "bastard", "piss", "dick", "pussy", "cock", "tits", "jerk", 
                     "idiot", "suck", "whore", "slut", "nigger", "chink", "spic", 
                     "kike", "wetback", "coon", "gook"]
        text_lower = text.lower()
        flagged = []
        for word in bad_words:
            if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
                flagged.append(word)
        if flagged:
            print(f"Flagged words detected: {flagged}")
            print("This video would be blocked!")
        else:
            print("No flagged words detected. Video is safe.")
    except sr.RequestError as e:
        print(f"API error: {e}")
    except sr.UnknownValueError:
        print("Couldn’t understand the audio")

print("Done!")
if os.path.exists("test_audio.webm"):
    os.remove("test_audio.webm")
if os.path.exists("test_audio.wav"):
    os.remove("test_audio.wav")