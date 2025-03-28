from flask import Flask, request, render_template, redirect, url_for, jsonify
import yt_dlp
import speech_recognition as sr
from pydub import AudioSegment
import os
import re
import time
import json
import threading
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound

app = Flask(__name__)

# YouTube API setup
YOUTUBE_API_KEY = "AIzaSyDS2Of1My9aiRAP5OhOjJoBaxNiFE0Nbq4"
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# In-memory storage for deployment (replace with a database in production)
blocked_channels = []
liked_videos = []
settings = {"bad_words": ["damn", "hell", "stupid", "crap"]}
video_log = []

# Global dictionary to store safety check results
safety_results = {}

# Fetch kid-safe video suggestions using YouTube API
def get_kid_safe_videos():
    try:
        request = youtube.search().list(
            part="snippet",
            q="kid friendly videos",
            type="video",
            maxResults=10,
            safeSearch="strict"
        )
        response = request.execute()
        videos = []
        for item in response['items']:
            video_id = item['id']['videoId']
            title = item['snippet']['title']
            thumbnail = item['snippet']['thumbnails']['medium']['url']
            channel_id = item['snippet']['channelId']
            videos.append({
                "id": video_id,
                "title": title,
                "thumbnail": thumbnail,
                "channel_id": channel_id
            })
        return videos
    except HttpError as e:
        print(f"HTTP Error fetching videos: {e}")
        return [
            {"id": "dQw4w9WgXcQ", "title": "Rick Astley - Never Gonna Give You Up", 
             "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw"},
            {"id": "9bZkp7q19f0", "title": "PSY - Gangnam Style", 
             "thumbnail": "https://i.ytimg.com/vi/9bZkp7q19f0/hqdefault.jpg", "channel_id": "UC0C-w0YjGpqDXGB8IHb662A"}
        ]
    except Exception as e:
        print(f"Error fetching videos: {e}")
        return [
            {"id": "dQw4w9WgXcQ", "title": "Rick Astley - Never Gonna Give You Up", 
             "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw"},
            {"id": "9bZkp7q19f0", "title": "PSY - Gangnam Style", 
             "thumbnail": "https://i.ytimg.com/vi/9bZkp7q19f0/hqdefault.jpg", "channel_id": "UC0C-w0YjGpqDXGB8IHb662A"}
        ]

# Fetch related videos using YouTube API
def get_related_videos(video_id):
    try:
        # First, get the video's title to use as a search query
        request = youtube.videos().list(
            part="snippet",
            id=video_id
        )
        response = request.execute()
        if not response['items']:
            return []
        title = response['items'][0]['snippet']['title']

        # Search for related videos using the title
        request = youtube.search().list(
            part="snippet",
            q=title,
            type="video",
            maxResults=5,
            safeSearch="strict"
        )
        response = request.execute()
        videos = []
        for item in response['items']:
            related_video_id = item['id']['videoId']
            # Skip the current video
            if related_video_id == video_id:
                continue
            title = item['snippet']['title']
            thumbnail = item['snippet']['thumbnails']['medium']['url']
            channel_id = item['snippet']['channelId']
            videos.append({
                "id": related_video_id,
                "title": title,
                "thumbnail": thumbnail,
                "channel_id": channel_id
            })
        return videos
    except HttpError as e:
        print(f"HTTP Error fetching related videos: {e}")
        return []
    except Exception as e:
        print(f"Error fetching related videos: {e}")
        return []

# Quick metadata check for initial safety
def check_metadata_safety(url):
    try:
        ydl_opts = {
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info['id']
            title = info.get('title', '').lower()
            description = info.get('description', '').lower()
            channel_id = info['channel_id']

        if channel_id in blocked_channels:
            return False, f"Video '{title}' is from a blocked channel!"

        bad_words = settings["bad_words"]
        flagged = []
        for word in bad_words:
            if word in title or word in description:
                flagged.append(word)
        if flagged:
            if channel_id not in blocked_channels:
                blocked_channels.append(channel_id)
            return False, f"Flagged words in metadata: {flagged}<br>This video would be blocked!"
        return True, "Safe to play (metadata check)"
    except Exception as e:
        print(f"Error in check_metadata_safety: {str(e)}")
        return False, f"Oops, something went wrong: {str(e)}."

# Check captions for bad words
def check_captions_safety(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        full_text = " ".join([entry['text'].lower() for entry in transcript if entry['start'] <= 30])
        bad_words = settings["bad_words"]
        flagged = []
        for word in bad_words:
            if re.search(r'\b' + re.escape(word) + r'\b', full_text):
                flagged.append(word)
        return flagged
    except NoTranscriptFound:
        print(f"No transcript found for video {video_id}")
        return None
    except Exception as e:
        print(f"Error fetching transcript for video {video_id}: {str(e)}")
        return None

# Background audio safety check (first 30 seconds)
def background_audio_check(url, video_id):
    print(f"Starting background audio check for video {video_id}")
    try:
        # First, try captions
        flagged = check_captions_safety(video_id)
        if flagged is not None:
            if flagged:
                channel_id = None
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    channel_id = info['channel_id']
                if channel_id and channel_id not in blocked_channels:
                    blocked_channels.append(channel_id)
                safety_results[video_id] = (False, f"Flagged words in captions: {flagged}<br>This video would be blocked!", "completed")
                print(f"Finished background check for video {video_id} using captions: blocked")
                return
            else:
                safety_results[video_id] = (True, "Safe to play (captions check)", "completed")
                print(f"Finished background check for video {video_id} using captions: safe")
                return

        # Fallback to audio if no captions
        ydl_opts = {
            'format': 'bestaudio',
            'outtmpl': 'test_audio.%(ext)s',
            'overwrite': True,
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as e:
                print(f"Download error in background_audio_check: {str(e)}")
                safety_results[video_id] = (False, f"Failed to download the video: {str(e)}. It might be restricted, age-gated, or unavailable in your region.", "completed")
                return
            video_id = info['id']
            title = info['title']
            channel_id = info['channel_id']

        # Verify file exists with a delay
        time.sleep(1)
        if not os.path.exists("test_audio.webm"):
            print("test_audio.webm not found after download attempt")
            safety_results[video_id] = (False, "Failed to download the audio file. The video might be restricted or unavailable.", "completed")
            return

        if channel_id in blocked_channels:
            safety_results[video_id] = (False, f"Video '{title}' is from a blocked channel!", "completed")
            return

        # Process audio (first 30 seconds)
        audio = AudioSegment.from_file("test_audio.webm")
        audio = audio[:30000]  # First 30 seconds
        chunk_length = 15000  # Process in 15-second chunks
        chunks = [audio[i:i + chunk_length] for i in range(0, len(audio), chunk_length)]

        # Transcribe and filter
        recognizer = sr.Recognizer()
        full_text = ""
        flagged = []
        bad_words = settings["bad_words"]

        for i, chunk in enumerate(chunks):
            chunk_file = f"chunk_{i}.wav"
            chunk.export(chunk_file, format="wav")
            with sr.AudioFile(chunk_file) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data)
                    full_text += text + " "
                    text_lower = text.lower()
                    for word in bad_words:
                        if re.search(r'\b' + re.escape(word) + r'\b', text_lower) and word not in flagged:
                            flagged.append(word)
                except sr.UnknownValueError:
                    full_text += "[Unclear audio] "
            time.sleep(0.5)
            if os.path.exists(chunk_file):
                os.remove(chunk_file)

        # Check if safe
        if flagged:
            if channel_id not in blocked_channels:
                blocked_channels.append(channel_id)
            safety_results[video_id] = (False, f"Flagged words: {flagged}<br>This video would be blocked!", "completed")
        else:
            safety_results[video_id] = (True, "Safe to play", "completed")

        # Log the checked video
        video_log.append({
            "video_id": video_id,
            "title": title,
            "result": "blocked" if flagged else "safe",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })

        print(f"Finished background audio check for video {video_id}: {'blocked' if flagged else 'safe'}")

    except Exception as e:
        print(f"Error in background_audio_check: {str(e)}")
        safety_results[video_id] = (False, f"Oops, something went wrong: {str(e)}.", "completed")
    finally:
        if os.path.exists("test_audio.webm"):
            os.remove("test_audio.webm")

# Homepage with video suggestions and checking
@app.route('/', methods=['GET', 'POST'])
def index():
    result = ""
    all_suggestions = get_kid_safe_videos()
    suggestions = [s for s in all_suggestions if s['channel_id'] not in blocked_channels]

    if request.method == 'POST':
        url = request.form['url']
        action = request.form.get('action', 'check')
        video_id = url.split('v=')[-1] if 'v=' in url else url

        if action == 'like':
            if video_id not in liked_videos:
                liked_videos.append(video_id)
            return redirect(url_for('index'))

        if action == 'dislike':
            ydl_opts = {'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                channel_id = info['channel_id']
            if channel_id not in blocked_channels:
                blocked_channels.append(channel_id)
            return redirect(url_for('index'))

        if action == 'check':
            try:
                # Download audio and metadata with user-agent
                ydl_opts = {
                    'format': 'bestaudio',
                    'outtmpl': 'test_audio.%(ext)s',
                    'overwrite': True,
                    'quiet': True,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(url, download=True)
                    except yt_dlp.utils.DownloadError as e:
                        result = f"Failed to download the video: {str(e)}. It might be restricted, age-gated, or unavailable in your region."
                        return render_template('index.html', result=result, suggestions=suggestions)
                    video_id = info['id']
                    title = info['title']
                    channel_id = info['channel_id']

                # Verify file exists with a delay
                time.sleep(1)
                if not os.path.exists("test_audio.webm"):
                    result = "Failed to download the audio file. The video might be restricted or unavailable."
                    return render_template('index.html', result=result, suggestions=suggestions)

                if channel_id in blocked_channels:
                    result = f"Video '{title}' is from a blocked channel!"
                    return render_template('index.html', result=result, suggestions=suggestions)

                # Process audio
                audio = AudioSegment.from_file("test_audio.webm")
                chunk_length = 59000
                chunks = [audio[i:i + chunk_length] for i in range(0, len(audio), chunk_length)]

                # Transcribe and filter
                recognizer = sr.Recognizer()
                full_text = ""
                flagged = []
                bad_words = settings["bad_words"]

                for i, chunk in enumerate(chunks):
                    chunk_file = f"chunk_{i}.wav"
                    chunk.export(chunk_file, format="wav")
                    with sr.AudioFile(chunk_file) as source:
                        audio_data = recognizer.record(source)
                        try:
                            text = recognizer.recognize_google(audio_data)
                            full_text += text + " "
                            text_lower = text.lower()
                            for word in bad_words:
                                if re.search(r'\b' + re.escape(word) + r'\b', text_lower) and word not in flagged:
                                    flagged.append(word)
                        except sr.UnknownValueError:
                            full_text += "[Unclear audio] "
                    time.sleep(0.5)
                    if os.path.exists(chunk_file):
                        os.remove(chunk_file)

                # Build result
                result = f"Transcription: {full_text.strip()}<br>"
                if flagged:
                    result += f"Flagged words: {flagged}<br>This video would be blocked!"
                    if channel_id not in blocked_channels:
                        blocked_channels.append(channel_id)
                else:
                    result += "No flagged words detected. Video is safe."

                # Log the checked video
                video_log.append({
                    "video_id": video_id,
                    "title": title,
                    "result": "blocked" if flagged else "safe",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })

            except yt_dlp.utils.DownloadError as e:
                result = f"Failed to download the video: {str(e)}. It might be restricted, age-gated, or unavailable in your region."
            except FileNotFoundError:
                result = "Failed to download the audio file. The video might be restricted or unavailable."
            except Exception as e:
                result = f"Oops, something went wrong: {str(e)}. Please try again!"
            finally:
                if os.path.exists("test_audio.webm"):
                    os.remove("test_audio.webm")
    return render_template('index.html', result=result, suggestions=suggestions)

# Watch page for video playback
@app.route('/watch/<video_id>')
def watch(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    # Initial metadata check
    is_safe, message = check_metadata_safety(url)
    if not is_safe:
        return render_template('watch.html', video_id=video_id, is_safe=False, message=message, related_videos=[])

    # Start background audio check
    safety_results[video_id] = (True, "Checking...", "processing")  # Initial state
    threading.Thread(target=background_audio_check, args=(url, video_id), daemon=True).start()

    # Fetch related videos
    related_videos = get_related_videos(video_id)
    related_videos = [v for v in related_videos if v['channel_id'] not in blocked_channels]
    return render_template('watch.html', video_id=video_id, is_safe=True, message="", related_videos=related_videos)

# Route to check safety status
@app.route('/check_safety/<video_id>')
def check_safety(video_id):
    if video_id in safety_results:
        is_safe, message, status = safety_results[video_id]
        return jsonify({"is_safe": is_safe, "message": message, "status": status})
    return jsonify({"is_safe": True, "message": "Checking...", "status": "processing"})

# Settings page for parental controls
@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    if request.method == 'POST':
        bad_words = request.form['bad_words'].split(',')
        settings['bad_words'] = [word.strip().lower() for word in bad_words if word.strip()]
        return redirect(url_for('index'))
    return render_template('settings.html', settings=settings)

# Monitoring page for parents
@app.route('/monitor')
def monitor():
    return render_template('monitor.html', video_log=video_log)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)