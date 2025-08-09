import os
import uuid
import asyncio
import time
import zipfile
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
import yt_dlp
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter

cookies_content = os.getenv("YT_COOKIES")
if cookies_content:
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(cookies_content)
@app.exception_handler(RateLimitExceeded)

async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please slow down."}
    )

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def _download_audio_sync(url: str):
    output_template = os.path.join(DOWNLOAD_DIR, f"%(title)s.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': False,
        'outtmpl': output_template,
        'cookiefile': 'cookies.txt',
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }
        ],
        'quiet': True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if 'entries' in info:  
        files = []
        for entry in info['entries']:
            if entry:
                filename = ydl.prepare_filename(entry)
                mp3_file = os.path.splitext(filename)[0] + ".mp3"
                files.append(mp3_file)
        return files
    else:
        filename = ydl.prepare_filename(info)
        mp3_file = os.path.splitext(filename)[0] + ".mp3"
        return [mp3_file]


async def download_audio(url: str):
    return await asyncio.to_thread(_download_audio_sync, url)


@app.get("/download-audio")
@limiter.limit("10/day")  
async def download_audio_endpoint(
    request: Request,
    url: str = Query(..., description="YouTube video or playlist URL"),
    background_tasks: BackgroundTasks = None
):
    try:
        files = await download_audio(url)

        if len(files) == 1:
            file_path = files[0]
            background_tasks.add_task(os.remove, file_path)  
            return FileResponse(
                file_path,
                media_type="audio/mpeg",
                filename=os.path.basename(file_path),
                background=background_tasks
            )

        else:
            zip_path = os.path.join(DOWNLOAD_DIR, f"{uuid.uuid4()}.zip")
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in files:
                    zipf.write(file, os.path.basename(file))
                    background_tasks.add_task(os.remove, file) 
            background_tasks.add_task(os.remove, zip_path)  

            return FileResponse(
                zip_path,
                media_type="application/zip",
                filename=f"playlist_{uuid.uuid4()}.zip",
                background=background_tasks
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
