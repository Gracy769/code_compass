"""code_compass.web.app — standalone FastAPI web server for Code Compass.

Enables zero-friction browser ingestion via GitHub URL or ZIP upload,
auto-analyzes repositories with the core engine, and serves interactive dashboards.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from code_compass.analysis import analyze as run_analysis
from code_compass.cache_manager import compute_hash, load_cache, save_cache
from code_compass.discovery import discover
from code_compass.renderer import render
from code_compass.web.security import (
    MAX_CLONE_SECONDS,
    MAX_UPLOAD_BYTES,
    canonical_github_url,
    check_run_owner,
    cleanup_expired_runs,
    log_security_event,
)

app = FastAPI(
    title="Code Compass Web",
    description="Autonomous Codebase Architecture & Static Analysis Engine",
    version="0.2.0",
)

# Step 3: Content-Security-Policy middleware — applied to all HTML responses.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https://api.github.com; "
    "img-src 'self' data: https:; "
    "font-src 'self';"
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Content-Security-Policy"] = _CSP
    return response


STORAGE_DIR = Path(tempfile.gettempdir()) / "code_compass_web_runs"
STORAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
STORAGE_DIR.chmod(0o700)
JOB_SLOTS = asyncio.Semaphore(2)
SESSION_COOKIE = "code_compass_session"
CSRF_COOKIE = "csrf_token"

# --- Step 1: Per-IP sequential rate limiter (max 10 requests / 60 s) ---
_RATE_LIMIT: dict[str, list[float]] = {}
_RL_WINDOW = 60
_RL_MAX = 10

# --- Step 9c: Per-IP upload rate limiter (max 2 uploads / 30 s) ---
_UPLOAD_RATE: dict[str, list[float]] = {}
_UL_WINDOW = 30
_UL_MAX = 2


class GitAnalyzeRequest(BaseModel):
    url: str
    strict: bool = True
    semantic: bool = False
    token: str | None = None


class AuditRequest(BaseModel):
    endpoint: str
    model: str
    api_key: str


def _check_rate_limit(ip: str) -> None:
    """Raise 429 if the IP has exceeded the per-minute request cap."""
    now = time.time()
    timestamps = _RATE_LIMIT.get(ip, [])
    timestamps = [t for t in timestamps if now - t < _RL_WINDOW]
    timestamps.append(now)
    _RATE_LIMIT[ip] = timestamps
    if len(timestamps) > _RL_MAX:
        log_security_event("rate_limit_block", ip, f"window={_RL_WINDOW}s max={_RL_MAX}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")


def _check_upload_rate(ip: str) -> None:
    """Raise 429 if the IP has exceeded the per-30-second upload cap."""
    now = time.time()
    timestamps = _UPLOAD_RATE.get(ip, [])
    timestamps = [t for t in timestamps if now - t < _UL_WINDOW]
    timestamps.append(now)
    _UPLOAD_RATE[ip] = timestamps
    if len(timestamps) > _UL_MAX:
        log_security_event("rate_limit_block", ip, f"upload_window={_UL_WINDOW}s max={_UL_MAX}")
        raise HTTPException(status_code=429, detail="Too many archive uploads. Try again shortly.")


def _check_csrf(request: Request) -> None:
    """Validate double-submit CSRF token (header must match cookie)."""
    header_token = request.headers.get("x-csrf-token", "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not header_token or not cookie_token or header_token != cookie_token:
        log_security_event("csrf_mismatch", request.client.host if request.client else "", "")
        raise HTTPException(status_code=403, detail="CSRF token mismatch.")


def _session(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-origin analysis is not allowed.")
    session = request.cookies.get(SESSION_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", session):
        raise HTTPException(status_code=403, detail="Open the homepage before starting an analysis.")
    return session


def _new_run(request: Request) -> tuple[str, Path]:
    session = _session(request)
    cleanup_expired_runs(STORAGE_DIR, time.time())
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    work_dir = STORAGE_DIR / run_id
    work_dir.mkdir(parents=True, mode=0o700)
    (work_dir / "owner").write_text(session, encoding="ascii")
    return run_id, work_dir


def _run_worker(kind: str, source: str, work_dir: Path, *, strict: bool, semantic: bool = False, token: str = "", name: str = "", endpoint: str = "", model: str = "", api_key: str = "") -> None:
    # Step 7: Subprocess path guard — ensure work_dir is inside STORAGE_DIR.
    work_dir_path = Path(str(work_dir)).resolve()
    if not work_dir_path.is_relative_to(STORAGE_DIR.resolve()) or not work_dir_path.is_dir():
        log_security_event("path_traversal_attempt", "", f"work_dir={work_dir}")
        raise ValueError("Invalid work directory path traversal.")
    env = os.environ.copy()
    if token:
        env["CODE_COMPASS_CLONE_TOKEN"] = token
    if api_key:
        env["CODE_COMPASS_AUDIT_KEY"] = api_key
    command = [sys.executable, "-m", "code_compass.web.worker", kind, source, str(work_dir)]
    if strict:
        command.append("--strict")
    if semantic:
        command.append("--semantic")
    if name:
        command.extend(("--name", name))
    if endpoint:
        command.extend(("--endpoint", endpoint))
    if model:
        command.extend(("--model", model))
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=MAX_CLONE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Analysis exceeded the time limit.") from exc
    if completed.returncode:
        raise RuntimeError("Analysis failed. Check the repository URL or ZIP contents.")


async def _bounded_worker(kind: str, source: str, work_dir: Path, *, strict: bool, semantic: bool = False, token: str = "", name: str = "", endpoint: str = "", model: str = "", api_key: str = "") -> None:
    try:
        await asyncio.wait_for(JOB_SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="Analysis is busy. Please retry shortly.") from exc
    try:
        await asyncio.to_thread(_run_worker, kind, source, work_dir, strict=strict, semantic=semantic, token=token, name=name, endpoint=endpoint, model=model, api_key=api_key)
    finally:
        JOB_SLOTS.release()


# Embedded responsive Cyberpunk Hero Landing Page
LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Code Compass — Autonomous Codebase Architecture Engine</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #070b14;
      --bg-card: rgba(13, 20, 36, 0.7);
      --border-cyan: rgba(0, 180, 216, 0.25);
      --accent-cyan: #00b4d8;
      --accent-sky: #38bdf8;
      --accent-blue: #3b82f6;
      --glow-cyan: rgba(0, 180, 216, 0.35);
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-dark);
      color: #f8fafc;
      font-family: 'Plus Jakarta Sans', sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
      display: flex;
      flex-direction: column;
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(0, 180, 216, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 85% 30%, rgba(59, 130, 246, 0.08) 0%, transparent 45%),
        radial-gradient(circle at 50% 90%, rgba(0, 180, 216, 0.05) 0%, transparent 50%);
    }

    /* Top Nav */
    nav {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1.25rem 2.5rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      backdrop-filter: blur(12px);
      background: rgba(7, 11, 20, 0.6);
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-weight: 800;
      letter-spacing: 0.1em;
      font-size: 1.1rem;
      color: #fff;
    }
    .brand svg {
      width: 34px;
      height: 34px;
      padding: 5px;
      border-radius: 9px;
      background: linear-gradient(135deg, #0ea5e9, #3b82d4);
      color: #fff;
      box-shadow: 0 0 12px var(--glow-cyan), 0 2px 8px rgba(0,0,0,.4);
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 1.75rem;
    }
    .nav-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 500;
      transition: color 0.2s;
    }
    .nav-links a:hover { color: var(--accent-sky); }

    /* Main Container */
    main {
      flex: 1;
      max-width: 1400px;
      margin: 0 auto;
      padding: 3rem 2rem;
      width: 100%;
      display: grid;
      grid-template-columns: 1.15fr 1fr;
      gap: 3.5rem;
      align-items: center;
      position: relative;
    }
    main::before {
      content: '';
      position: absolute;
      inset: 1.5rem 0;
      border: 1px solid rgba(125, 211, 252, 0.09);
      border-radius: 28px;
      background: radial-gradient(circle at 78% 18%, rgba(56,189,248,0.10), transparent 38%),
        repeating-linear-gradient(90deg, transparent 0 39px, rgba(148,163,184,0.025) 40px),
        repeating-linear-gradient(0deg, transparent 0 39px, rgba(148,163,184,0.025) 40px);
      pointer-events: none;
    }
    main > * { position: relative; }

    /* Left Hero Column */
    .hero-left {
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }
    .tagline {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      color: var(--accent-cyan);
      text-transform: uppercase;
    }
    .headline {
      font-size: 3.5rem;
      font-weight: 800;
      line-height: 1.12;
      letter-spacing: -0.02em;
    }
    .headline span {
      color: var(--accent-sky);
      text-shadow: 0 0 24px rgba(56, 189, 248, 0.3);
    }
    .subtext {
      color: var(--text-muted);
      font-size: 1.1rem;
      line-height: 1.6;
      max-width: 540px;
    }

    /* Search & Action Bar */
    .search-container {
      margin-top: 0.75rem;
      position: relative;
    }
    .search-input-wrap {
      display: flex;
      align-items: center;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid rgba(0, 180, 216, 0.35);
      border-radius: 12px;
      padding: 0.75rem 1.25rem;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05);
      transition: all 0.3s;
    }
    .search-input-wrap:focus-within {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 25px rgba(0, 180, 216, 0.25);
    }
    .search-input-wrap svg {
      width: 20px;
      height: 20px;
      color: var(--text-muted);
      margin-right: 0.75rem;
      flex-shrink: 0;
    }
    .search-input {
      background: transparent;
      border: none;
      outline: none;
      color: #fff;
      font-size: 1rem;
      font-family: inherit;
      width: 100%;
    }
    .search-input::placeholder { color: #64748b; }

    /* Action Buttons */
    .actions-row {
      display: flex;
      gap: 1rem;
      margin-top: 0.5rem;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.85rem 1.5rem;
      border-radius: 10px;
      font-weight: 700;
      font-size: 0.95rem;
      cursor: pointer;
      transition: all 0.25s;
      border: none;
      text-decoration: none;
    }
    .btn-primary {
      background: linear-gradient(135deg, #00b4d8 0%, #2563eb 100%);
      color: #fff;
      box-shadow: 0 4px 15px rgba(0, 180, 216, 0.4);
    }
    .btn-primary:hover {
      box-shadow: 0 6px 25px rgba(0, 180, 216, 0.6);
      transform: translateY(-2px);
    }
    .btn-secondary {
      background: rgba(15, 23, 42, 0.8);
      color: #f1f5f9;
      border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .btn-secondary:hover {
      background: rgba(30, 41, 59, 0.8);
      border-color: rgba(255, 255, 255, 0.25);
      transform: translateY(-2px);
    }

    /* Quick Launch Presets */
    .presets {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 0.5rem;
      font-size: 0.85rem;
      color: #64748b;
    }
    .chip {
      background: rgba(30, 41, 59, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #cbd5e1;
      padding: 0.35rem 0.85rem;
      border-radius: 9999px;
      cursor: pointer;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      transition: all 0.2s;
    }
    .chip:hover {
      border-color: var(--accent-cyan);
      color: var(--accent-sky);
      background: rgba(0, 180, 216, 0.1);
    }

    /* Right Hero Visual Column */
    .hero-right {
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
      position: relative;
    }
    .hud-card {
      background: radial-gradient(circle at 100% 0%, rgba(56,189,248,0.075), transparent 48%),
        linear-gradient(155deg, rgba(20,34,52,0.92), rgba(8,15,27,0.92));
      border: 1px solid var(--border-cyan);
      border-radius: 16px;
      backdrop-filter: blur(16px);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
      position: relative;
      overflow: hidden;
    }

    /* Status Card */
    .status-card {
      padding: 1rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }
    .status-left {
      display: flex;
      align-items: center;
      gap: 0.85rem;
      min-width: 0;
    }
    .status-indicator {
      width: 32px;
      height: 32px;
      flex: 0 0 32px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(56,189,248,0.24);
      border-radius: 50%;
      background: rgba(14,165,233,0.08);
      color: #67e8f9;
      position: relative;
    }
    .status-indicator::before {
      content: '';
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 11px rgba(103,232,249,0.5);
    }
    .status-indicator .loading-dots, .status-indicator .complete-mark { display: none; }
    .status-indicator.is-loading::before, .status-indicator.is-complete::before { display: none; }
    .status-indicator.is-loading .loading-dots { display: block; position: absolute; inset: 0; }
    .loading-dots span {
      position: absolute;
      inset: 0;
      transform: rotate(calc(var(--dot-index) * 45deg));
    }
    .loading-dots span::after {
      content: '';
      display: block;
      width: 4px;
      height: 4px;
      margin: 3px auto;
      border-radius: 50%;
      background: #67e8f9;
      animation: dot-pulse 0.9s ease-in-out infinite;
      animation-delay: calc(var(--dot-index) * -0.1125s);
    }
    @keyframes dot-pulse { 0%, 100% { opacity: 0.2; transform: scale(0.7); } 50% { opacity: 1; transform: scale(1.15); } }
    .status-indicator.is-complete {
      color: #6ee7b7;
      border-color: rgba(52,211,153,0.45);
      background: rgba(16,185,129,0.13);
    }
    .status-indicator.is-complete .complete-mark { display: block; }
    .status-title {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
      font-weight: 700;
      color: #fff;
      letter-spacing: 0.05em;
    }
    .status-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
      min-height: 1.3em;
    }
    .status-copy { min-width: 0; }
    .status-word-window {
      display: none;
      align-items: center;
      gap: 0.35rem;
      margin-top: 0.38rem;
      color: #8eb3c7;
      font-size: 0.8rem;
      font-weight: 600;
      line-height: 1.45;
    }
    .status-card.is-analyzing .status-word-window { display: flex; }
    .status-word-clip {
      display: inline-block;
      height: 1.45em;
      overflow: hidden;
      color: #67e8f9;
      -webkit-mask-image: linear-gradient(transparent, #000 18%, #000 82%, transparent);
      mask-image: linear-gradient(transparent, #000 18%, #000 82%, transparent);
    }
    .status-word-track { display: block; animation: status-words 10s ease-in-out infinite; }
    .status-word-track span { display: block; height: 1.45em; white-space: nowrap; }
    @keyframes status-words {
      0%, 14% { transform: translateY(0); }
      20%, 34% { transform: translateY(-1.45em); }
      40%, 54% { transform: translateY(-2.9em); }
      60%, 74% { transform: translateY(-4.35em); }
      80%, 94% { transform: translateY(-5.8em); }
      100% { transform: translateY(-7.25em); }
    }
    @media (prefers-reduced-motion: reduce) {
      .loading-dots span::after, .progress-bar-fill.running { animation: none; }
      .loading-dots span::after { opacity: 0.75; transform: none; }
      .status-word-track { animation: none; }
    }
    .progress-bar-wrap {
      width: 140px;
      height: 6px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 9999px;
      overflow: hidden;
      position: relative;
    }
    .progress-bar-fill {
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, #00b4d8, #38bdf8);
      border-radius: 9999px;
      transition: width 0.4s ease;
    }
    .progress-bar-fill.running {
      width: 35%;
      animation: progress-scan 1.3s ease-in-out infinite alternate;
    }
    @keyframes progress-scan {
      from { transform: translateX(0); }
      to { transform: translateX(185%); }
    }

    /* Interactive Topology Canvas */
    .canvas-wrap {
      height: 380px;
      width: 100%;
      position: relative;
      background: radial-gradient(circle at center, rgba(0, 180, 216, 0.05) 0%, transparent 70%);
    }
    #topologyCanvas {
      width: 100%;
      height: 100%;
      display: block;
    }
    .map-overlay {
      position: absolute;
      top: 1rem;
      right: 1rem;
      background: rgba(10, 15, 28, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      padding: 0.6rem 0.85rem;
      font-size: 0.7rem;
      color: var(--text-muted);
    }
    .map-overlay-title {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
      color: #fff;
      margin-bottom: 0.35rem;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin-top: 0.2rem;
    }
    .dot-cyan { width: 6px; height: 6px; border-radius: 50%; background: #00b4d8; }
    .dot-amber { width: 6px; height: 6px; border-radius: 50%; background: #f59e0b; }

    /* Metric Cards Grid */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1rem;
    }
    .metric-card {
      padding: 1.15rem;
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }
    .metric-icon {
      width: 42px;
      height: 42px;
      border-radius: 10px;
      background: rgba(0, 180, 216, 0.12);
      border: 1px solid rgba(0, 180, 216, 0.25);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent-cyan);
      flex-shrink: 0;
    }
    .metric-val {
      font-size: 1.1rem;
      font-weight: 800;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
    }
    .metric-lbl {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 0.1rem;
    }

    /* Modal */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 100;
      align-items: center;
      justify-content: center;
    }
    .modal-box {
      background: #0d1424;
      border: 1px solid var(--border-cyan);
      border-radius: 16px;
      padding: 2rem;
      max-width: 480px;
      width: 90%;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    }
    .modal-title { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; }
    .modal-sub { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1.25rem; }
    .modal-input {
      width: 100%;
      padding: 0.75rem 1rem;
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      color: #fff;
      font-family: inherit;
      margin-bottom: 1rem;
    }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.75rem; }

    /* Footer */
    footer {
      border-top: 1px solid rgba(255, 255, 255, 0.05);
      padding: 1.5rem 2.5rem;
      display: flex;
      justify-content: space-between;
      color: #64748b;
      font-size: 0.8rem;
      font-family: 'JetBrains Mono', monospace;
    }

    @media (max-width: 1024px) {
      main { grid-template-columns: 1fr; gap: 2.5rem; }
      .headline { font-size: 2.75rem; }
    }
    @media (max-width: 640px) {
      nav { padding: 1rem; }
      .nav-links { gap: 0.75rem; }
      main { padding: 2rem 1rem; min-width: 0; }
      .hero-left, .hero-right { min-width: 0; }
      .headline { font-size: clamp(2rem, 9vw, 2.75rem); overflow-wrap: anywhere; }
      .presets { flex-wrap: wrap; }
      .metrics-grid { grid-template-columns: 1fr; }
      .status-card { flex-wrap: wrap; }
      footer { padding: 1rem; flex-wrap: wrap; gap: 0.5rem; }
    }
  </style>
</head>
<body>

  <!-- Top Bar -->
  <nav>
    <div class="brand">
      <svg viewBox="0 0 40 40" fill="none" role="img" aria-label="Code Compass logo">
        <circle cx="20" cy="20" r="15" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
        <path d="M20 2v6M20 32v6M2 20h6M32 20h6" stroke="currentColor" stroke-opacity=".5" stroke-width="2" stroke-linecap="round"/>
        <path d="m25.8 14.2-3.7 7.9-7.9 3.7 3.7-7.9 7.9-3.7Z" fill="currentColor"/>
        <circle cx="20" cy="20" r="2.2" fill="#070b14"/>
      </svg>
      CODE COMPASS
    </div>
    <div class="nav-links">
      <a href="https://github.com/Gracy769/code-compass-app" target="_blank">Docs</a>
      <a href="https://github.com/Gracy769/code-compass-app" target="_blank">GitHub</a>
    </div>
  </nav>

  <!-- Main Hero -->
  <main>
    <!-- Left Column -->
    <div class="hero-left">
      <div class="tagline">Architecture, Made Visible</div>
      <h1 class="headline">
        Ingest any codebase.<br>
        <span>Surface invisible architecture.</span>
      </h1>
      <p class="subtext">
        Autonomous codebase onboarding and static analysis that maps architectural hubs, call graphs, and danger zones instantly.
      </p>

      <!-- URL Input & Actions -->
      <div class="search-container">
        <div class="search-input-wrap">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
          </svg>
          <input type="text" id="repoUrlInput" class="search-input" placeholder="Paste GitHub URL (e.g. https://github.com/mcollina/fastq)">
        </div>

        <div class="actions-row">
          <button id="analyzeBtn" class="btn btn-primary" onclick="startAnalysis()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            Analyze Codebase
          </button>
          
          <button id="uploadZipBtn" class="btn btn-secondary" onclick="document.getElementById('zipFileInput').click()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            Upload .ZIP
          </button>

          <button id="authGithubBtn" class="btn btn-secondary" onclick="handleGitHubAuth()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            <span id="authGithubBtnText">Sign in with GitHub</span>
          </button>

          <a href="/dashboard/demo" class="btn btn-secondary" style="border-color: rgba(0, 180, 216, 0.4); color: var(--accent-sky);">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
            </svg>
            Instant Live Demo
          </a>
        </div>

        <input type="file" id="zipFileInput" style="display:none" accept=".zip" onchange="uploadZip(event)">

        <!-- Quick Launch Presets -->
        <div class="presets">
          <span>Presets:</span>
          <div class="chip" onclick="setPreset('https://github.com/mcollina/fastq')">fastq</div>
          <div class="chip" onclick="setPreset('https://github.com/fastapi/fastapi')">fastapi</div>
          <div class="chip" onclick="setPreset('https://github.com/expressjs/express')">express</div>
          <div class="chip" onclick="setPreset('https://github.com/redis/redis')">redis</div>
        </div>
      </div>
    </div>

    <!-- Right Column (Cult UI Hero Color Panels HUD) -->
    <div class="hero-right">
      <!-- Status Card -->
      <div class="hud-card status-card">
        <div class="status-left">
          <div class="status-indicator" id="statusSpinner" role="img" aria-label="Ready for analysis">
            <div class="loading-dots" aria-hidden="true"><span style="--dot-index:0"></span><span style="--dot-index:1"></span><span style="--dot-index:2"></span><span style="--dot-index:3"></span><span style="--dot-index:4"></span><span style="--dot-index:5"></span><span style="--dot-index:6"></span><span style="--dot-index:7"></span></div>
            <svg class="complete-mark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l4 4L19 6"/></svg>
          </div>
          <div class="status-copy">
            <div class="status-title" id="statusTitle">READY FOR INGESTION</div>
            <div class="status-sub" id="statusSub">Enter repository URL or upload ZIP</div>
            <div class="status-word-window" aria-hidden="true">
              <span>Mapping</span>
              <span class="status-word-clip"><span class="status-word-track">
                <span>modules</span><span>symbols</span><span>call paths</span>
                <span>layers</span><span>landmarks</span><span>modules</span>
              </span></span>
            </div>
          </div>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" id="progressBar"></div>
        </div>
      </div>

      <!-- Topology Visual Canvas -->
      <div class="hud-card canvas-wrap">
        <canvas id="topologyCanvas"></canvas>
        <div class="map-overlay">
          <div class="map-overlay-title">CODEBASE MAP</div>
          <div class="legend-item"><span class="dot-cyan"></span> Core Hub</div>
          <div class="legend-item"><span class="dot-amber"></span> Risk Hotspot</div>
        </div>
      </div>

      <!-- 3 Metrics Preview -->
      <div class="metrics-grid">
        <div class="hud-card metric-card">
          <div class="metric-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
          </div>
          <div>
            <div class="metric-val" id="fileCountVal">—</div>
            <div class="metric-lbl">Files after analysis</div>
          </div>
        </div>

        <div class="hud-card metric-card">
          <div class="metric-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
            </svg>
          </div>
          <div>
            <div class="metric-val">—</div>
            <div class="metric-lbl">Measured AST time</div>
          </div>
        </div>

        <div class="hud-card metric-card">
          <div class="metric-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
          </div>
          <div>
            <div class="metric-val">—</div>
            <div class="metric-lbl">Critical findings</div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- Repo Picker Modal (Supabase OAuth) -->
  <div class="modal-backdrop" id="repoPickerModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center;">
    <div class="modal-box" style="max-height:60vh;overflow-y:auto;">
      <div class="modal-title">Your GitHub Repositories</div>
      <div id="repoPickerList" style="margin-top:1rem;display:flex;flex-direction:column;gap:0.5rem;"></div>
      <div class="modal-actions"><button class="btn btn-secondary" onclick="document.getElementById('repoPickerModal').style.display='none'">Close</button></div>
    </div>
  </div>

  <!-- GitHub Token Modal -->
  <div class="modal-backdrop" id="tokenModal">
    <div class="modal-box">
      <div class="modal-title">Connect GitHub Account</div>
      <div class="modal-sub">Authenticate via token for private repository indexing &amp; higher API limits.</div>
      <input type="password" id="ghTokenInput" class="modal-input" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx">
      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeTokenModal()">Cancel</button>
        <button class="btn btn-primary" onclick="saveToken()">Use for this analysis</button>
      </div>
    </div>
  </div>

  <footer>
    <div>EXPLORE &bull; UNDERSTAND &bull; BUILD &bull; FASTER</div>
    <div>A CLEARER PATH FROM CODE TO CONTEXT</div>
  </footer>

  <script>
    // Canvas Topology Rendering
    const canvas = document.getElementById('topologyCanvas');
    const ctx = canvas.getContext('2d');

    function resize() {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight;
    }
    window.addEventListener('resize', resize);
    resize();

    const nodes = [
      { name: 'core', x: 0.5, y: 0.42, r: 14, color: '#38bdf8', pulse: 0 },
      { name: 'api', x: 0.32, y: 0.22, r: 10, color: '#00b4d8', pulse: 1 },
      { name: 'models', x: 0.72, y: 0.26, r: 11, color: '#00b4d8', pulse: 2 },
      { name: 'services', x: 0.28, y: 0.72, r: 10, color: '#f59e0b', pulse: 3 },
      { name: 'data', x: 0.65, y: 0.76, r: 10, color: '#00b4d8', pulse: 4 },
      { name: 'utils', x: 0.82, y: 0.52, r: 9, color: '#00b4d8', pulse: 5 },
    ];

    const edges = [
      [0, 1], [0, 2], [0, 3], [0, 4], [0, 5],
      [1, 2], [3, 4], [2, 5], [4, 5]
    ];

    let t = 0;
    function renderCanvas() {
      t += 0.03;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw isometric grid platforms
      const cx = canvas.width / 2;
      const cy = canvas.height / 2;
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 180, 216, 0.06)';
      ctx.lineWidth = 1;
      for (let i = -4; i <= 4; i++) {
        ctx.beginPath();
        ctx.moveTo(cx + i * 40 - 150, cy + i * 20 + 80);
        ctx.lineTo(cx + i * 40 + 150, cy + i * 20 - 80);
        ctx.stroke();
      }
      ctx.restore();

      // Draw Edges
      edges.forEach(([a, b]) => {
        const na = nodes[a];
        const nb = nodes[b];
        const ax = na.x * canvas.width;
        const ay = na.y * canvas.height;
        const bx = nb.x * canvas.width;
        const by = nb.y * canvas.height;

        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.strokeStyle = 'rgba(0, 180, 216, 0.25)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });

      // Draw Nodes
      nodes.forEach((n, i) => {
        const x = n.x * canvas.width;
        const y = n.y * canvas.height;
        const pulseR = n.r + Math.sin(t + n.pulse) * 2.5;

        // Glow ring
        ctx.beginPath();
        ctx.arc(x, y, pulseR + 8, 0, Math.PI * 2);
        ctx.fillStyle = n.color === '#f59e0b' ? 'rgba(245, 158, 11, 0.1)' : 'rgba(56, 189, 248, 0.12)';
        ctx.fill();

        // Node circle
        ctx.beginPath();
        ctx.arc(x, y, pulseR, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.shadowColor = n.color;
        ctx.shadowBlur = 15;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Label
        ctx.font = '600 11px "JetBrains Mono", monospace';
        ctx.fillStyle = '#f8fafc';
        ctx.textAlign = 'center';
        ctx.fillText(n.name, x, y - pulseR - 6);
      });

      requestAnimationFrame(renderCanvas);
    }
    renderCanvas();

    // Presets
    function setPreset(url) {
      document.getElementById('repoUrlInput').value = url;
      startAnalysis();
    }

    // Modal
    let githubToken = null;
    const query = new URLSearchParams(window.location.search);
    if (query.has('repo')) document.getElementById('repoUrlInput').value = query.get('repo');
    if (query.get('connect') === '1') openTokenModal();
    function openTokenModal() {
      document.getElementById('tokenModal').style.display = 'flex';
    }
    function closeTokenModal() {
      document.getElementById('tokenModal').style.display = 'none';
    }
    function saveToken() {
      const val = document.getElementById('ghTokenInput').value.trim();
      githubToken = val || null;
      document.getElementById('ghTokenInput').value = '';
      closeTokenModal();
    }

    // Analysis Execution
    async function startAnalysis() {
      const url = document.getElementById('repoUrlInput').value.trim();
      if (!url) {
        alert('Please enter a GitHub repository URL or choose a preset.');
        return;
      }

      setAnalyzingState('CLONING & PARSING CODEBASE', 'Ingesting files, building AST, and mapping call relationships...');

      try {
        const token = githubToken;
        // Step 2: Send token in Authorization header, not in request body.
        // Step 4: Echo CSRF cookie value in X-CSRF-Token header (double-submit pattern).
        const csrfToken = document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] || '';
        const res = await fetch('/api/analyze-git', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfToken,
            ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
          },
          body: JSON.stringify({ url: url, strict: true, semantic: false })
        });

        const data = await res.json();
        githubToken = null;
        if (!res.ok) throw new Error(data.detail || 'Analysis failed');

        stopStatusAnimation();
        document.getElementById('progressBar').classList.remove('running');
        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('statusTitle').textContent = 'ANALYSIS COMPLETE';
        setStatusIndicator('complete');
        document.getElementById('statusSub').textContent = 'Redirecting to interactive dashboard...';

        setTimeout(() => {
          window.location.href = data.dashboard_url;
        }, 800);

      } catch (err) {
        alert('Analysis Error: ' + err.message);
        resetState();
      }
    }

    async function uploadZip(event) {
      const file = event.target.files[0];
      if (!file) return;

      setAnalyzingState('PARSING UPLOADED ZIP', 'Extracting repository and parsing symbols...');

      const formData = new FormData();
      formData.append('file', file);

      try {
        // Step 4: Echo CSRF cookie value in X-CSRF-Token header (double-submit pattern).
        const csrfToken = document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] || '';
        const res = await fetch('/api/analyze-upload', {
          method: 'POST',
          headers: { 'X-CSRF-Token': csrfToken },
          body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Zip analysis failed');

        stopStatusAnimation();
        document.getElementById('progressBar').classList.remove('running');
        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('statusTitle').textContent = 'ANALYSIS COMPLETE';
        setStatusIndicator('complete');
        setTimeout(() => {
          window.location.href = data.dashboard_url;
        }, 800);

      } catch (err) {
        alert('Upload Error: ' + err.message);
        resetState();
      }
    }

    function stopStatusAnimation() {
      document.getElementById('statusSpinner').closest('.status-card').classList.remove('is-analyzing');
    }

    function setStatusIndicator(state) {
      const indicator = document.getElementById('statusSpinner');
      indicator.classList.toggle('is-loading', state === 'loading');
      indicator.classList.toggle('is-complete', state === 'complete');
      indicator.closest('.status-card').classList.toggle('is-analyzing', state === 'loading');
      indicator.setAttribute('aria-label', state === 'complete' ? 'Analysis complete' : state === 'loading' ? 'Analysis in progress' : 'Ready for analysis');
    }

    function setAnalyzingState(title, sub) {
      stopStatusAnimation();
      setStatusIndicator('loading');
      document.getElementById('statusTitle').textContent = title;
      document.getElementById('statusSub').textContent = sub;
      document.getElementById('progressBar').style.width = '';
      document.getElementById('progressBar').classList.add('running');
      document.getElementById('analyzeBtn').disabled = true;
      document.getElementById('analyzeBtn').style.opacity = '0.6';
    }

    function resetState() {
      stopStatusAnimation();
      setStatusIndicator('ready');
      document.getElementById('statusTitle').textContent = 'READY FOR INGESTION';
      document.getElementById('statusSub').textContent = 'Enter repository URL or upload ZIP';
      document.getElementById('progressBar').classList.remove('running');
      document.getElementById('progressBar').style.width = '0';
      document.getElementById('analyzeBtn').disabled = false;
      document.getElementById('analyzeBtn').style.opacity = '1';
    }

    // GitHub Auth & Repo Picker
    // Auto-detect OAuth tokens in URL hash from Supabase redirect
    (function checkOAuthHash() {
      if (window.location.hash) {
        try {
          const hashParams = new URLSearchParams(window.location.hash.substring(1));
          const pToken = hashParams.get('provider_token');
          const aToken = hashParams.get('access_token');
          if (pToken) {
            localStorage.setItem('gh_token', pToken);
          }
          if (aToken) {
            localStorage.setItem('sb_access_token', aToken);
          }
          if (pToken || aToken) {
            // Clean up the URL hash cleanly without reloading
            history.replaceState(null, '', window.location.pathname);
          }
        } catch (_) {}
      }
    })();

    function _hasGitHubCredential() {
      return !!(localStorage.getItem('gh_token') || localStorage.getItem('sb_access_token'));
    }

    function updateGhButton() {
      const btn = document.getElementById('authGithubBtnText');
      if (btn) btn.textContent = _hasGitHubCredential() ? 'Upload from GitHub' : 'Sign in with GitHub';
    }

    async function openRepoPicker() {
      const ghToken = localStorage.getItem('gh_token') || '';
      const data = await fetch('/api/repos', {
        headers: ghToken ? { 'Authorization': 'Bearer ' + ghToken } : {}
      }).then(r => r.json()).catch(() => ({ repos: [], authenticated: false }));

      if (!data.authenticated || !data.repos.length) { openTokenModal(); return; }
      const list = document.getElementById('repoPickerList');
      list.innerHTML = '';
      data.repos.forEach(r => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-secondary';
        btn.style.cssText = 'width:100%;text-align:left;padding:0.6rem 1rem;';
        btn.textContent = r.full_name;
        btn.onclick = () => { document.getElementById('repoUrlInput').value = r.url; document.getElementById('repoPickerModal').style.display = 'none'; startAnalysis(); };
        list.appendChild(btn);
      });
      document.getElementById('repoPickerModal').style.display = 'flex';
    }

    async function handleGitHubAuth() {
      if (_hasGitHubCredential()) { openRepoPicker(); return; }
      try {
        const cfg = await fetch('/api/supabase-config').then(r => r.json()).catch(() => null);
        if (!cfg || !cfg.enabled) { openTokenModal(); return; }
        const { createClient } = await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm');
        const sb = createClient(cfg.supabase_url, cfg.anon_key);
        const { error } = await sb.auth.signInWithOAuth({ provider: 'github', options: { redirectTo: window.location.origin + '/auth/callback' } });
        if (error) { openTokenModal(); }
      } catch (_) {
        openTokenModal();
      }
    }

    // On load: sync button label with stored credential state
    updateGhButton();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    """Serve the Cult UI-inspired Cyberpunk Hero Landing Page."""
    response = HTMLResponse(content=LANDING_HTML, status_code=200)
    _secure = request.url.hostname not in {"localhost", "127.0.0.1"}
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", request.cookies.get(SESSION_COOKIE, "")):
        response.set_cookie(
            SESSION_COOKIE, secrets.token_urlsafe(32), httponly=True,
            secure=_secure, samesite="strict", max_age=24 * 60 * 60,
        )
    # Step 4: Set CSRF double-submit cookie (httponly=False so JS can read it).
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", request.cookies.get(CSRF_COOKIE, "")):
        response.set_cookie(
            CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False,
            secure=_secure, samesite="strict", max_age=24 * 60 * 60,
        )
    return response


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Railway health check endpoint."""
    return {"status": "ok", "service": "code-compass"}


@app.get("/api/supabase-config")
async def supabase_config() -> dict:
    url = os.environ.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    return {"enabled": bool(url and anon_key), "supabase_url": url if url else "", "anon_key": anon_key if anon_key else ""}


from fastapi.responses import RedirectResponse  # noqa: E402


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Exchange Supabase OAuth code for a session and redirect to homepage."""
    code = request.query_params.get("code")
    if not code:
        # Implicit hash-based redirect carries fragments automatically
        return RedirectResponse(url="/")
    try:
        from code_compass.cache_manager import _get_client
        client = _get_client()
        if client is None:
            return RedirectResponse(url="/")
        session_data = client.auth.exchange_code_for_session({"auth_code": code})
        access_token = session_data.session.access_token if session_data and session_data.session else None
        if not access_token:
            return RedirectResponse(url="/")
        response = RedirectResponse(url="/")
        response.set_cookie("sb_session", access_token, httponly=True, samesite="strict", max_age=3600)
        return response
    except Exception:
        return RedirectResponse(url="/")


@app.get("/api/repos")
async def list_repos(request: Request) -> dict:
    """Return the authenticated user's GitHub repos via GitHub provider token or session."""
    auth_hdr = request.headers.get("Authorization", "")
    token = auth_hdr.replace("Bearer ", "").strip() if auth_hdr.startswith("Bearer ") else request.cookies.get("sb_session", "")
    if not token:
        return {"repos": [], "authenticated": False}
    try:
        import json as _json
        import urllib.request
        req2 = urllib.request.Request(
            "https://api.github.com/user/repos?per_page=30&sort=updated",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "Code-Compass"}
        )
        with urllib.request.urlopen(req2, timeout=5) as resp:
            repos = _json.loads(resp.read())
        return {
            "repos": [{"name": r["name"], "full_name": r["full_name"], "url": r["html_url"]} for r in repos if isinstance(r, dict)],
            "authenticated": True,
        }
    except Exception:
        return {"repos": [], "authenticated": False}



@app.post("/api/analyze-git")
async def analyze_git_repo(req: GitAnalyzeRequest, request: Request) -> dict[str, str]:
    """Clone a public/private Git repository and run Code Compass analysis."""
    # Step 1: Per-IP rate limit.
    _check_rate_limit(request.client.host if request.client else "unknown")
    # Step 4: CSRF validation.
    _check_csrf(request)
    try:
        repo_url = canonical_github_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    hash_str = compute_hash(repo_url)
    cached = load_cache(hash_str, ttl_days=7)
    cached_ref = str(cached.repo_stats.get("github_ref", "")) if cached is not None else ""
    # Older cache entries have no source revision and cannot produce working
    # GitHub links. Refresh them once, then keep cache hits fully linked.
    if cached is not None and re.fullmatch(r"[0-9a-fA-F]{40}", cached_ref):
        run_id, work_dir = _new_run(request)
        try:
            slug = urlsplit(repo_url).path.strip("/").removesuffix(".git")
            render(cached, work_dir / "dashboard.html", repo_name=slug.split("/")[-1],
                   github_slug=slug, github_ref=cached_ref)
            return {
                "success": "true",
                "analysis_id": run_id,
                "dashboard_url": f"/dashboard/{run_id}",
                "summary_url": f"/summary/{run_id}",
            }
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)  # fall through to full analysis

    run_id, work_dir = _new_run(request)

    # Step 2: Extract token from Authorization header instead of request body.
    _token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()

    try:
        await _bounded_worker("git", repo_url, work_dir, strict=req.strict, semantic=req.semantic, token=_token)
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Repository analysis failed or timed out.") from exc

    try:
        import json as _json
        from code_compass.cache_manager import _dict_to_analysis_result
        _aj = work_dir / "analysis.json"
        if _aj.is_file():
            _data = _json.loads(_aj.read_text(encoding="utf-8"))
            _result = _dict_to_analysis_result(_data)
            save_cache(hash_str, _result, ttl_days=7, repo_name=Path(urlsplit(repo_url).path).stem)
    except Exception:
        pass

    return {
        "success": "true",
        "analysis_id": run_id,
        "dashboard_url": f"/dashboard/{run_id}",
        "summary_url": f"/summary/{run_id}",
    }


@app.post("/api/analyze-upload")
async def analyze_zip_upload(request: Request, file: UploadFile = File(...)) -> dict[str, str]:
    """Accept and extract a repository ZIP file and run analysis."""
    # Step 1: Per-IP rate limit.
    _check_rate_limit(request.client.host if request.client else "unknown")
    # Step 4: CSRF validation.
    _check_csrf(request)
    # Step 9c: Per-IP upload rate limit.
    _check_upload_rate(request.client.host if request.client else "unknown")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")

    run_id, work_dir = _new_run(request)
    zip_path = work_dir / "upload.zip"

    try:
        total = 0
        with zip_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="ZIP exceeds the 25 MB upload limit.")
                output.write(chunk)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename.replace("\\", "/").split("/")[-1])[:80]
        await _bounded_worker("zip", str(zip_path), work_dir, strict=True, name=safe_name.removesuffix(".zip"))

    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="ZIP analysis failed or timed out.") from exc

    return {
        "success": "true",
        "analysis_id": run_id,
        "dashboard_url": f"/dashboard/{run_id}",
        "summary_url": f"/summary/{run_id}",
    }


@app.post("/api/audit/{analysis_id}")
async def run_configured_audit(analysis_id: str, config: AuditRequest, request: Request) -> dict[str, str]:
    """Audit the saved repository using a one-time, user configured provider."""
    _session(request)
    if not re.fullmatch(r"run_[a-f0-9]{12}", analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")
    run_dir = STORAGE_DIR / analysis_id
    if not check_run_owner(run_dir, request.cookies.get(SESSION_COOKIE)):
        log_security_event("failed_auth", request.client.host if request.client else "", f"audit/{analysis_id}")
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if not (run_dir / "analysis.json").is_file():
        raise HTTPException(status_code=404, detail="Analysis source is unavailable.")
    if len(config.endpoint) > 500 or len(config.model) > 120 or len(config.api_key) > 1000:
        raise HTTPException(status_code=400, detail="Audit settings are too long.")
    try:
        await _bounded_worker("audit", ".", run_dir, strict=False,
                              endpoint=config.endpoint, model=config.model, api_key=config.api_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Audit failed. Check the HTTPS endpoint, model, API key, and provider response.") from exc
    return {"dashboard_url": f"/dashboard/{analysis_id}"}


@app.on_event("startup")
async def seed_demo_analysis() -> None:
    """Pre-generate a live demo dashboard on startup so visitors can view it instantly."""
    demo_dir = STORAGE_DIR / "demo"
    cleanup_expired_runs(STORAGE_DIR, time.time())
    try:
        demo_dir.mkdir(parents=True, exist_ok=True)
        local_src = Path(__file__).parent.parent
        started = time.perf_counter()
        manifest = discover(local_src)
        result = run_analysis(manifest, strict=True, semantic=False)
        result.repo_stats["analysis_seconds"] = round(time.perf_counter() - started, 2)
        render(result, demo_dir / "dashboard.html", repo_name="code-compass-core", github_slug="Gracy769/code-compass-app")
        print("[code-compass] Seeded live demo dashboard at /dashboard/demo")
    except Exception as err:
        print(f"[code-compass] Demo seed note: {err}")


@app.get("/dashboard/{analysis_id}", response_class=HTMLResponse)
async def view_dashboard(analysis_id: str, request: Request):
    """Serve one run only to the browser session that started it."""
    if analysis_id != "demo" and not re.fullmatch(r"run_[a-f0-9]{12}", analysis_id):
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    run_dir = STORAGE_DIR / analysis_id
    dash_path = run_dir / "dashboard.html"
    if not dash_path.is_file():
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    if analysis_id != "demo" and not check_run_owner(run_dir, request.cookies.get(SESSION_COOKIE)):
        log_security_event("failed_auth", request.client.host if request.client else "", f"dashboard/{analysis_id}")
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    content = dash_path.read_text(encoding="utf-8")
    # Dynamically rewrite relative summary links to FastAPI route
    content = content.replace('"dashboard-summary.html"', f'"/summary/{analysis_id}"')
    return HTMLResponse(content=content, status_code=200, headers={"Cache-Control": "private, no-store"})


@app.get("/summary/{analysis_id}", response_class=HTMLResponse)
async def view_summary(analysis_id: str, request: Request):
    """Serve the companion summary page for a specific analysis run."""
    if analysis_id != "demo" and not re.fullmatch(r"run_[a-f0-9]{12}", analysis_id):
        raise HTTPException(status_code=404, detail="Summary not found.")
    run_dir = STORAGE_DIR / analysis_id
    summary_path = run_dir / "dashboard-summary.html"
    if not summary_path.is_file():
        raise HTTPException(status_code=404, detail="Summary not found.")
    if analysis_id != "demo" and not check_run_owner(run_dir, request.cookies.get(SESSION_COOKIE)):
        log_security_event("failed_auth", request.client.host if request.client else "", f"summary/{analysis_id}")
        raise HTTPException(status_code=404, detail="Summary not found.")

    content = summary_path.read_text(encoding="utf-8")
    # Dynamically rewrite relative dashboard links to FastAPI route
    content = content.replace('href="dashboard.html"', f'href="/dashboard/{analysis_id}"')
    return HTMLResponse(content=content, status_code=200, headers={"Cache-Control": "private, no-store"})

