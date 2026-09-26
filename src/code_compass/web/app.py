"""code_compass.web.app — standalone FastAPI web server for Code Compass.

Enables zero-friction browser ingestion via GitHub URL or ZIP upload,
auto-analyzes repositories with the core engine, and serves interactive dashboards.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from code_compass.analysis import analyze as run_analysis
from code_compass.analysis.git_stats import detect_github_slug
from code_compass.discovery import discover
from code_compass.renderer import render

app = FastAPI(
    title="Code Compass Web",
    description="Autonomous Codebase Architecture & Static Analysis Engine",
    version="0.2.0",
)

STORAGE_DIR = Path(tempfile.gettempdir()) / "code_compass_web_runs"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


class GitAnalyzeRequest(BaseModel):
    url: str
    strict: bool = True
    semantic: bool = False
    token: str | None = None


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
      width: 28px;
      height: 28px;
      color: var(--accent-cyan);
      filter: drop-shadow(0 0 8px var(--glow-cyan));
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
    }

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
      background: var(--bg-card);
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
    }
    .spinner {
      width: 22px;
      height: 22px;
      border: 2.5px solid rgba(0, 180, 216, 0.2);
      border-top-color: var(--accent-cyan);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
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
      width: 45%;
      background: linear-gradient(90deg, #00b4d8, #38bdf8);
      border-radius: 9999px;
      transition: width 0.4s ease;
      animation: pulse-bar 2s ease-in-out infinite;
    }
    @keyframes pulse-bar {
      0%, 100% { opacity: 0.7; }
      50% { opacity: 1; filter: drop-shadow(0 0 6px var(--accent-sky)); }
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
  </style>
</head>
<body>

  <!-- Top Bar -->
  <nav>
    <div class="brand">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon>
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

          <button id="authGithubBtn" class="btn btn-secondary" onclick="openTokenModal()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            Connect GitHub
          </button>
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
          <div class="spinner" id="statusSpinner"></div>
          <div>
            <div class="status-title" id="statusTitle">READY FOR INGESTION</div>
            <div class="status-sub" id="statusSub">Enter repository URL or upload ZIP</div>
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
            <div class="metric-val" id="fileCountVal">6,600+</div>
            <div class="metric-lbl">Max Parse Capacity</div>
          </div>
        </div>

        <div class="hud-card metric-card">
          <div class="metric-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
            </svg>
          </div>
          <div>
            <div class="metric-val">0.75s</div>
            <div class="metric-lbl">AST Processing Velocity</div>
          </div>
        </div>

        <div class="hud-card metric-card">
          <div class="metric-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
          </div>
          <div>
            <div class="metric-val">100%</div>
            <div class="metric-lbl">Zero-Panic Guarantee</div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- GitHub Token Modal -->
  <div class="modal-backdrop" id="tokenModal">
    <div class="modal-box">
      <div class="modal-title">Connect GitHub</div>
      <div class="modal-sub">Enter a personal access token for higher rate limits and private repository access.</div>
      <input type="password" id="ghTokenInput" class="modal-input" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx">
      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeTokenModal()">Cancel</button>
        <button class="btn btn-primary" onclick="saveToken()">Save Token</button>
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
    function openTokenModal() {
      document.getElementById('tokenModal').style.display = 'flex';
      const saved = localStorage.getItem('code_compass_gh_token');
      if (saved) document.getElementById('ghTokenInput').value = saved;
    }
    function closeTokenModal() {
      document.getElementById('tokenModal').style.display = 'none';
    }
    function saveToken() {
      const val = document.getElementById('ghTokenInput').value.trim();
      if (val) localStorage.setItem('code_compass_gh_token', val);
      else localStorage.removeItem('code_compass_gh_token');
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
        const token = localStorage.getItem('code_compass_gh_token') || null;
        const res = await fetch('/api/analyze-git', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url, strict: true, semantic: false, token: token })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Analysis failed');

        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('statusTitle').textContent = '100% COMPLETE';
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
        const res = await fetch('/api/analyze-upload', {
          method: 'POST',
          body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Zip analysis failed');

        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('statusTitle').textContent = '100% COMPLETE';
        setTimeout(() => {
          window.location.href = data.dashboard_url;
        }, 800);

      } catch (err) {
        alert('Upload Error: ' + err.message);
        resetState();
      }
    }

    function setAnalyzingState(title, sub) {
      document.getElementById('statusTitle').textContent = title;
      document.getElementById('statusSub').textContent = sub;
      document.getElementById('progressBar').style.width = '75%';
      document.getElementById('analyzeBtn').disabled = true;
      document.getElementById('analyzeBtn').style.opacity = '0.6';
    }

    function resetState() {
      document.getElementById('statusTitle').textContent = 'READY FOR INGESTION';
      document.getElementById('statusSub').textContent = 'Enter repository URL or upload ZIP';
      document.getElementById('progressBar').style.width = '15%';
      document.getElementById('analyzeBtn').disabled = false;
      document.getElementById('analyzeBtn').style.opacity = '1';
    }
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def homepage() -> HTMLResponse:
    """Serve the Cult UI-inspired Cyberpunk Hero Landing Page."""
    return HTMLResponse(content=LANDING_HTML, status_code=200)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Railway health check endpoint."""
    return {"status": "ok", "service": "code-compass"}


@app.post("/api/analyze-git")
async def analyze_git_repo(req: GitAnalyzeRequest) -> dict[str, str]:
    """Clone a public/private Git repository and run Code Compass analysis."""
    repo_url = req.url.strip()
    if not repo_url.startswith(("http://", "https://", "git@")):
        raise HTTPException(status_code=400, detail="Invalid Git repository URL.")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    work_dir = STORAGE_DIR / run_id
    clone_dir = work_dir / "repo"
    clone_dir.mkdir(parents=True, exist_ok=True)

    # Inject token if provided
    auth_url = repo_url
    if req.token and "github.com" in repo_url and repo_url.startswith("https://"):
        auth_url = repo_url.replace("https://", f"https://x-access-token:{req.token}@")

    # Run git clone in a thread pool to avoid blocking async loop
    def _clone_and_analyze() -> tuple[Path, str]:
        import git

        git.Repo.clone_from(auth_url, clone_dir, depth=1)
        manifest = discover(clone_dir)
        result = run_analysis(manifest, strict=req.strict, semantic=req.semantic)
        slug = detect_github_slug(clone_dir) or ""

        out_dashboard = work_dir / "dashboard.html"
        written = render(result, out_dashboard, repo_name=clone_dir.name, github_slug=slug)
        return written, run_id

    try:
        _, analysis_id = await asyncio.to_thread(_clone_and_analyze)
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Git ingestion error: {exc}")

    return {
        "success": "true",
        "analysis_id": analysis_id,
        "dashboard_url": f"/dashboard/{analysis_id}",
        "summary_url": f"/summary/{analysis_id}",
    }


@app.post("/api/analyze-upload")
async def analyze_zip_upload(file: UploadFile = File(...)) -> dict[str, str]:
    """Accept and extract a repository ZIP file and run analysis."""
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    work_dir = STORAGE_DIR / run_id
    extract_dir = work_dir / "repo"
    extract_dir.mkdir(parents=True, exist_ok=True)

    zip_path = work_dir / "upload.zip"

    try:
        content = await file.read()
        zip_path.write_bytes(content)

        def _extract_and_analyze() -> tuple[Path, str]:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Basic zip-slip protection
                for member in zf.namelist():
                    resolved = (extract_dir / member).resolve()
                    if not str(resolved).startswith(str(extract_dir.resolve())):
                        raise ValueError("Zip file contains unsafe path traversal paths.")
                zf.extractall(extract_dir)

            # If zip contains a single root folder, inspect inside it
            candidates = [p for p in extract_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
            target_repo = candidates[0] if len(candidates) == 1 else extract_dir

            manifest = discover(target_repo)
            result = run_analysis(manifest, strict=True, semantic=False)

            out_dashboard = work_dir / "dashboard.html"
            written = render(result, out_dashboard, repo_name=file.filename.replace(".zip", ""))
            return written, run_id

        _, analysis_id = await asyncio.to_thread(_extract_and_analyze)

    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Upload error: {exc}")

    return {
        "success": "true",
        "analysis_id": analysis_id,
        "dashboard_url": f"/dashboard/{analysis_id}",
        "summary_url": f"/summary/{analysis_id}",
    }


@app.get("/dashboard/{analysis_id}", response_class=HTMLResponse)
async def view_dashboard(analysis_id: str) -> HTMLResponse:
    """Serve the generated dashboard for a specific analysis run."""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", analysis_id)
    dash_path = STORAGE_DIR / clean_id / "dashboard.html"
    if not dash_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found or expired.")
    return HTMLResponse(content=dash_path.read_text(encoding="utf-8"), status_code=200)


@app.get("/summary/{analysis_id}", response_class=HTMLResponse)
async def view_summary(analysis_id: str) -> HTMLResponse:
    """Serve the companion summary page for a specific analysis run."""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", analysis_id)
    summary_path = STORAGE_DIR / clean_id / "dashboard-summary.html"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Summary not found or expired.")
    return HTMLResponse(content=summary_path.read_text(encoding="utf-8"), status_code=200)
