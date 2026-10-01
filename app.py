import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import os
import time
import uuid
import json
import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.config import BASE_DIR, TEMP_DIR, OUTPUT_DIR, DEFAULT_MODEL, DEFAULT_VOICE, DEFAULT_DEVICE
from src.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Automated Video Dubbing Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount outputs for video playback
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# In-memory task store
tasks = {}

def execute_dubbing_task(task_id: str, video_source: str, output_name: str, model_size: str, voice: str):
    task = tasks[task_id]
    task["status"] = "processing"
    task["start_time"] = time.time()

    def pipeline_callback(data):
        task["stage"] = data.get("stage", task.get("stage"))
        task["message"] = data.get("message", task.get("message"))
        task["details"] = data
        # Push to async queue
        loop = task.get("loop")
        queue = task.get("queue")
        if loop and queue:
            asyncio.run_coroutine_threadsafe(queue.put(dict(task)), loop)

    try:
        final_path, benchmarks = run_pipeline(
            url=video_source,
            output_name=output_name,
            model_size=model_size,
            voice=voice,
            whisper_task="translate",
            mix_background=False,
            progress_callback=pipeline_callback
        )
        task["status"] = "completed"
        task["stage"] = "completed"
        task["output_file"] = output_name
        task["output_url"] = f"/outputs/{output_name}"
        task["benchmarks"] = benchmarks
        task["message"] = "Dubbed video successfully generated!"
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        task["status"] = "failed"
        task["error"] = str(e)
        task["message"] = f"Processing failed: {e}"
    finally:
        loop = task.get("loop")
        queue = task.get("queue")
        if loop and queue:
            asyncio.run_coroutine_threadsafe(queue.put(dict(task)), loop)

@app.post("/api/dub")
async def start_dubbing(
    url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    model: str = Form(DEFAULT_MODEL),
    voice: str = Form(DEFAULT_VOICE)
):
    if not url and not file:
        raise HTTPException(status_code=400, detail="Please provide either a YouTube URL or an uploaded MP4 file.")

    task_id = str(uuid.uuid4())
    output_name = f"dubbed_{task_id[:8]}.mp4"
    video_source = ""

    if file and file.filename:
        upload_path = str(TEMP_DIR / f"upload_{task_id[:8]}_{file.filename}")
        with open(upload_path, "wb") as f:
            content = await file.read()
            f.write(content)
        video_source = upload_path
    else:
        video_source = url.strip()

    loop = asyncio.get_running_loop()
    task_queue = asyncio.Queue()

    tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "stage": "download",
        "message": "Initializing pipeline...",
        "start_time": time.time(),
        "output_file": None,
        "output_url": None,
        "benchmarks": None,
        "loop": loop,
        "queue": task_queue
    }

    # Run in background thread so server remains unblocked
    thread = threading.Thread(
        target=execute_dubbing_task,
        args=(task_id, video_source, output_name, model, voice),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id, "status": "queued"}

@app.get("/api/progress/{task_id}")
async def get_progress_sse(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    queue = task["queue"]

    async def event_generator():
        # Send initial state
        initial_data = dict(task)
        initial_data.pop("loop", None)
        initial_data.pop("queue", None)
        initial_data["elapsed_seconds"] = round(time.time() - task.get("start_time", time.time()), 1)
        yield f"data: {json.dumps(initial_data)}\n\n"

        while True:
            try:
                # Wait for new progress update or timeout every 1s for elapsed time heartbeat
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    update = dict(task)

                clean_update = dict(update)
                clean_update.pop("loop", None)
                clean_update.pop("queue", None)
                clean_update["elapsed_seconds"] = round(time.time() - task.get("start_time", time.time()), 1)
                
                yield f"data: {json.dumps(clean_update)}\n\n"

                if clean_update.get("status") in ["completed", "failed"]:
                    break
            except Exception as e:
                logger.error(f"SSE generator error: {e}")
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/benchmarks")
async def get_benchmarks():
    benchmark_file = OUTPUT_DIR / "benchmarks.json"
    if benchmark_file.exists():
        try:
            with open(benchmark_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

@app.get("/", response_class=HTMLResponse)
async def serve_studio():
    return HTML_CONTENT

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Automated Video Dubbing Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Plus Jakarta Sans', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          },
          colors: {
            brand: {
              50: '#eef2ff',
              100: '#e0e7ff',
              500: '#6366f1',
              600: '#4f46e5',
              700: '#4338ca',
            }
          }
        }
      }
    }
  </script>
  <style>
    .glass-panel {
      background: rgba(17, 24, 39, 0.7);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .glow-accent {
      box-shadow: 0 0 25px -5px rgba(99, 102, 241, 0.3);
    }
  </style>
</head>
<body class="bg-[#0b0f19] text-gray-100 min-h-screen font-sans selection:bg-brand-500 selection:text-white">

  <!-- Header -->
  <header class="border-b border-gray-800/80 bg-[#0b0f19]/80 sticky top-0 z-50 backdrop-blur-md">
    <div class="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-400 flex items-center justify-center shadow-lg shadow-brand-500/20">
          <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z"></path></svg>
        </div>
        <div>
          <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            Automated Video Dubbing Studio
            <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-brand-500/10 text-brand-400 border border-brand-500/20">v2.0 CPU INT8</span>
          </h1>
        </div>
      </div>
      <div class="flex items-center space-x-4">
        <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-2 animate-pulse"></span> Pipeline Online
        </span>
      </div>
    </div>
  </header>

  <main class="max-w-6xl mx-auto px-6 py-10 space-y-10">

    <!-- Hero / Title -->
    <div class="text-center max-w-2xl mx-auto space-y-3">
      <h2 class="text-3xl font-extrabold tracking-tight sm:text-4xl text-white">
        Studio-Quality Video Dubbing, <span class="text-transparent bg-clip-text bg-gradient-to-r from-brand-400 to-indigo-300">Automatically</span>.
      </h2>
      <p class="text-sm text-gray-400">
        Faster-Whisper speech-to-English translation & Microsoft Edge-TTS neural speech synthesis, synchronized seamlessly with zero external API limits.
      </p>
    </div>

    <!-- 1. Input Section -->
    <section id="inputSection" class="glass-panel rounded-2xl p-6 sm:p-8 glow-accent">
      <div class="flex items-center justify-between pb-6 border-b border-gray-800">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <span class="flex items-center justify-center w-6 h-6 rounded-full bg-brand-500 text-xs text-white">1</span>
            Input Video Source
          </h3>
          <p class="text-xs text-gray-400 mt-0.5">Paste any foreign YouTube URL or upload a local MP4 file.</p>
        </div>

        <!-- Mode Toggle Tabs -->
        <div class="flex p-1 bg-gray-900 rounded-xl border border-gray-800 text-xs font-semibold">
          <button id="tabUrl" onclick="switchTab('url')" class="px-4 py-1.5 rounded-lg bg-brand-600 text-white shadow-sm transition">YouTube URL</button>
          <button id="tabUpload" onclick="switchTab('upload')" class="px-4 py-1.5 rounded-lg text-gray-400 hover:text-white transition">Upload MP4</button>
        </div>
      </div>

      <div class="mt-6">
        <!-- URL Input Tab -->
        <div id="urlInputContainer" class="space-y-4">
          <div class="relative">
            <input type="text" id="youtubeUrl" placeholder="https://www.youtube.com/watch?v=1EIbR0_z-y8" 
              class="w-full bg-gray-900/90 border border-gray-700/80 rounded-xl px-4 py-3.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent transition">
          </div>
          <div class="flex flex-wrap items-center gap-2 text-xs text-gray-400">
            <span>Quick Test:</span>
            <button onclick="setUrl('https://www.youtube.com/watch?v=1EIbR0_z-y8')" class="px-2.5 py-1 rounded-md bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 transition">
              ⭐ 30-Min Test Video (Osho Hindi Speech)
            </button>
            <button onclick="setUrl('https://www.youtube.com/watch?v=jNQXAC9IVRw')" class="px-2.5 py-1 rounded-md bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 transition">
              Short 19s Test Video
            </button>
          </div>
        </div>

        <!-- Local Upload Tab -->
        <div id="uploadInputContainer" class="hidden space-y-4">
          <div id="dropZone" onclick="document.getElementById('fileInput').click()" 
            class="border-2 border-dashed border-gray-700 hover:border-brand-500 rounded-2xl p-8 text-center cursor-pointer bg-gray-900/50 hover:bg-gray-900/80 transition group">
            <svg class="mx-auto h-10 w-10 text-gray-500 group-hover:text-brand-400 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
            <p class="mt-3 text-sm font-semibold text-gray-200">Drop your video here, or <span class="text-brand-400 underline">browse</span></p>
            <p class="text-xs text-gray-500 mt-1">MP4, MKV, or WebM format up to 2 GB</p>
            <p id="selectedFileName" class="text-xs font-semibold text-emerald-400 mt-3 hidden"></p>
            <input type="file" id="fileInput" accept="video/*" class="hidden" onchange="handleFileSelect(this)">
          </div>
        </div>

        <!-- Submit Button -->
        <div class="mt-6 flex items-center justify-end">
          <button id="startBtn" onclick="startDubbing()" class="px-6 py-3 rounded-xl bg-gradient-to-r from-brand-600 to-indigo-600 hover:from-brand-500 hover:to-indigo-500 text-white font-semibold text-sm shadow-lg shadow-brand-500/25 transition transform active:scale-98 flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            Generate Dubbed Video
          </button>
        </div>
      </div>
    </section>

    <!-- 2. Live Processing Status Section -->
    <section id="processingSection" class="hidden glass-panel rounded-2xl p-6 sm:p-8 space-y-6">
      <div class="flex items-center justify-between pb-6 border-b border-gray-800">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <span class="flex items-center justify-center w-6 h-6 rounded-full bg-brand-500 text-xs text-white">2</span>
            Live Processing Status
          </h3>
          <p class="text-xs text-gray-400 mt-0.5">Real-time telemetry and state streaming via Server-Sent Events (SSE).</p>
        </div>

        <!-- Elapsed Timer -->
        <div class="text-right">
          <span class="text-xs uppercase tracking-wider text-gray-400 block font-medium">Elapsed Time</span>
          <span id="elapsedTimer" class="font-mono text-xl font-bold text-brand-400">00:00:00</span>
        </div>
      </div>

      <!-- Live Stage Telemetry -->
      <div class="grid grid-cols-1 sm:grid-cols-5 gap-3">
        <!-- Stage 1 -->
        <div id="stageCard-download" class="p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-300">1. Video Load</span>
            <span id="badge-download" class="w-2.5 h-2.5 rounded-full bg-gray-600"></span>
          </div>
          <p id="msg-download" class="text-[11px] text-gray-500 mt-2 truncate">Waiting...</p>
        </div>

        <!-- Stage 2 -->
        <div id="stageCard-transcribe" class="p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-300">2. Transcribe</span>
            <span id="badge-transcribe" class="w-2.5 h-2.5 rounded-full bg-gray-600"></span>
          </div>
          <p id="msg-transcribe" class="text-[11px] text-gray-500 mt-2 truncate">Waiting...</p>
        </div>

        <!-- Stage 3 -->
        <div id="stageCard-translate" class="p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-300">3. Translate</span>
            <span id="badge-translate" class="w-2.5 h-2.5 rounded-full bg-gray-600"></span>
          </div>
          <p id="msg-translate" class="text-[11px] text-gray-500 mt-2 truncate">Waiting...</p>
        </div>

        <!-- Stage 4 -->
        <div id="stageCard-tts" class="p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-300">4. Neural Voice</span>
            <span id="badge-tts" class="w-2.5 h-2.5 rounded-full bg-gray-600"></span>
          </div>
          <p id="msg-tts" class="text-[11px] text-gray-500 mt-2 truncate">Waiting...</p>
        </div>

        <!-- Stage 5 -->
        <div id="stageCard-sync" class="p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-300">5. Sync & Render</span>
            <span id="badge-sync" class="w-2.5 h-2.5 rounded-full bg-gray-600"></span>
          </div>
          <p id="msg-sync" class="text-[11px] text-gray-500 mt-2 truncate">Waiting...</p>
        </div>
      </div>

      <!-- Live Terminal Log ticker -->
      <div class="p-3.5 bg-gray-950/80 rounded-xl border border-gray-800 font-mono text-xs flex items-center justify-between">
        <div class="flex items-center space-x-2 text-gray-300 truncate">
          <span class="w-2 h-2 rounded-full bg-brand-400 animate-ping"></span>
          <span id="liveStatusText" class="truncate">Engine ready...</span>
        </div>
        <span id="currentStageBadge" class="text-[10px] font-bold uppercase tracking-wider text-brand-400 bg-brand-500/10 px-2.5 py-0.5 rounded-full border border-brand-500/20">INITIALIZING</span>
      </div>
    </section>

    <!-- 3. Completed Output Section -->
    <section id="outputSection" class="hidden glass-panel rounded-2xl p-6 sm:p-8 space-y-6">
      <div class="flex items-center justify-between pb-6 border-b border-gray-800">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <span class="flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500 text-xs text-white">✓</span>
            Dubbed Video Ready
          </h3>
          <p class="text-xs text-gray-400 mt-0.5">Preview the result or download the synthesized MP4 video.</p>
        </div>
        <a id="downloadBtn" href="#" download class="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs shadow-lg shadow-emerald-500/20 transition flex items-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
          Download MP4
        </a>
      </div>

      <!-- Video Player & Benchmark Details Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Video Preview -->
        <div class="lg:col-span-2 rounded-xl overflow-hidden bg-black aspect-video border border-gray-800 flex items-center justify-center">
          <video id="videoPlayer" controls class="w-full h-full object-contain"></video>
        </div>

        <!-- Benchmark Card -->
        <div class="p-5 rounded-xl bg-gray-900/80 border border-gray-800 space-y-4">
          <h4 class="text-xs font-bold uppercase tracking-wider text-gray-400">Processing Telemetry</h4>
          <dl class="space-y-3 text-xs">
            <div class="flex justify-between">
              <dt class="text-gray-400">Total Processing Time:</dt>
              <dd id="statTotalTime" class="font-mono font-bold text-white">-</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-gray-400">Speech Segments:</dt>
              <dd id="statSegments" class="font-mono font-bold text-white">-</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-gray-400">Transcription Speed:</dt>
              <dd id="statTranscribeTime" class="font-mono text-gray-300">-</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-gray-400">TTS Synthesis Speed:</dt>
              <dd id="statTtsTime" class="font-mono text-gray-300">-</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-gray-400">Dubbed Audio Track:</dt>
              <dd class="text-emerald-400 font-semibold">100% Collision-Free</dd>
            </div>
          </dl>
          <div class="pt-3 border-t border-gray-800">
            <button onclick="resetStudio()" class="w-full py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-semibold text-gray-200 transition">
              Dub Another Video
            </button>
          </div>
        </div>
      </div>
    </section>

  </main>

  <script>
    let activeTab = 'url';
    let selectedFile = null;
    let timerInterval = null;
    let startTime = 0;

    function switchTab(tab) {
      activeTab = tab;
      if (tab === 'url') {
        document.getElementById('tabUrl').className = 'px-4 py-1.5 rounded-lg bg-brand-600 text-white shadow-sm transition';
        document.getElementById('tabUpload').className = 'px-4 py-1.5 rounded-lg text-gray-400 hover:text-white transition';
        document.getElementById('urlInputContainer').classList.remove('hidden');
        document.getElementById('uploadInputContainer').classList.add('hidden');
      } else {
        document.getElementById('tabUpload').className = 'px-4 py-1.5 rounded-lg bg-brand-600 text-white shadow-sm transition';
        document.getElementById('tabUrl').className = 'px-4 py-1.5 rounded-lg text-gray-400 hover:text-white transition';
        document.getElementById('uploadInputContainer').classList.remove('hidden');
        document.getElementById('urlInputContainer').classList.add('hidden');
      }
    }

    function setUrl(url) {
      document.getElementById('youtubeUrl').value = url;
    }

    function handleFileSelect(input) {
      if (input.files && input.files[0]) {
        selectedFile = input.files[0];
        const label = document.getElementById('selectedFileName');
        label.textContent = `Selected: ${selectedFile.name} (${(selectedFile.size / (1024*1024)).toFixed(1)} MB)`;
        label.classList.remove('hidden');
      }
    }

    // Drag and drop handlers
    const dropZone = document.getElementById('dropZone');
    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => { e.preventDefault(); dropZone.classList.add('border-brand-500'); }, false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => { e.preventDefault(); dropZone.classList.remove('border-brand-500'); }, false);
    });
    dropZone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt.files && dt.files[0]) {
        selectedFile = dt.files[0];
        const label = document.getElementById('selectedFileName');
        label.textContent = `Selected: ${selectedFile.name} (${(selectedFile.size / (1024*1024)).toFixed(1)} MB)`;
        label.classList.remove('hidden');
      }
    });

    async function startDubbing() {
      const formData = new FormData();
      if (activeTab === 'url') {
        const url = document.getElementById('youtubeUrl').value.trim();
        if (!url) {
          alert('Please enter a YouTube video URL.');
          return;
        }
        formData.append('url', url);
      } else {
        if (!selectedFile) {
          alert('Please select or drop an MP4 video file.');
          return;
        }
        formData.append('file', selectedFile);
      }

      // UI state transition
      document.getElementById('startBtn').disabled = true;
      document.getElementById('startBtn').classList.add('opacity-50', 'cursor-not-allowed');
      document.getElementById('processingSection').classList.remove('hidden');
      document.getElementById('outputSection').classList.add('hidden');

      // Start elapsed timer
      startTime = Date.now();
      clearInterval(timerInterval);
      timerInterval = setInterval(updateTimer, 500);

      try {
        const res = await fetch('/api/dub', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.task_id) {
          listenToProgress(data.task_id);
        } else {
          alert(data.detail || 'Failed to start dubbing task');
          resetStudio();
        }
      } catch (err) {
        alert('Server connection error: ' + err.message);
        resetStudio();
      }
    }

    function updateTimer() {
      const diffMs = Date.now() - startTime;
      const totalSec = Math.floor(diffMs / 1000);
      const hrs = String(Math.floor(totalSec / 3600)).padStart(2, '0');
      const mins = String(Math.floor((totalSec % 3600) / 60)).padStart(2, '0');
      const secs = String(totalSec % 60).padStart(2, '0');
      document.getElementById('elapsedTimer').textContent = `${hrs}:${mins}:${secs}`;
    }

    function listenToProgress(taskId) {
      const eventSource = new EventSource(`/api/progress/${taskId}`);

      eventSource.onmessage = (event) => {
        const state = JSON.parse(event.data);
        updateStageUI(state);

        if (state.status === 'completed') {
          eventSource.close();
          clearInterval(timerInterval);
          showOutput(state);
        } else if (state.status === 'failed') {
          eventSource.close();
          clearInterval(timerInterval);
          alert('Processing Error: ' + (state.error || state.message));
          document.getElementById('startBtn').disabled = false;
          document.getElementById('startBtn').classList.remove('opacity-50', 'cursor-not-allowed');
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
      };
    }

    const STAGES = ['download', 'transcribe', 'translate', 'tts', 'sync'];

    function updateStageUI(state) {
      const stage = state.stage;
      const msg = state.message || '';
      document.getElementById('liveStatusText').textContent = msg;
      document.getElementById('currentStageBadge').textContent = (stage || 'PROCESSING').toUpperCase();

      const stageIndex = STAGES.indexOf(stage);

      STAGES.forEach((s, idx) => {
        const card = document.getElementById(`stageCard-${s}`);
        const badge = document.getElementById(`badge-${s}`);
        const msgEl = document.getElementById(`msg-${s}`);

        if (idx < stageIndex || (idx === stageIndex && state.status === 'completed')) {
          // Completed stage
          card.className = 'p-4 rounded-xl border border-emerald-500/30 bg-emerald-950/20 transition';
          badge.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
        } else if (idx === stageIndex) {
          // Active stage
          card.className = 'p-4 rounded-xl border border-brand-500 bg-brand-950/20 transition shadow-lg shadow-brand-500/10';
          badge.className = 'w-2.5 h-2.5 rounded-full bg-brand-400 animate-ping';
          msgEl.textContent = msg;
        } else {
          // Pending stage
          card.className = 'p-4 rounded-xl border border-gray-800 bg-gray-900/60 transition';
          badge.className = 'w-2.5 h-2.5 rounded-full bg-gray-600';
        }
      });
    }

    function showOutput(state) {
      document.getElementById('outputSection').classList.remove('hidden');
      const videoUrl = state.output_url;
      const player = document.getElementById('videoPlayer');
      player.src = videoUrl;
      document.getElementById('downloadBtn').href = videoUrl;

      if (state.benchmarks) {
        const b = state.benchmarks;
        document.getElementById('statTotalTime').textContent = `${b.total_processing_time_s}s (${(b.total_processing_time_s / 60).toFixed(2)}m)`;
        document.getElementById('statSegments').textContent = b.num_segments || 'N/A';
        document.getElementById('statTranscribeTime').textContent = `${b.transcription_time_s}s`;
        document.getElementById('statTtsTime').textContent = `${b.tts_synthesis_time_s}s`;
      }

      document.getElementById('outputSection').scrollIntoView({ behavior: 'smooth' });
    }

    function resetStudio() {
      clearInterval(timerInterval);
      document.getElementById('startBtn').disabled = false;
      document.getElementById('startBtn').classList.remove('opacity-50', 'cursor-not-allowed');
      document.getElementById('processingSection').classList.add('hidden');
      document.getElementById('outputSection').classList.add('hidden');
      document.getElementById('selectedFileName').classList.add('hidden');
      selectedFile = null;
      document.getElementById('youtubeUrl').value = '';
    }
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*65)
    print("  >> Starting Automated Video Dubbing Studio Web Application")
    print("  >> Open in your browser: http://localhost:8000")
    print("="*65 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
