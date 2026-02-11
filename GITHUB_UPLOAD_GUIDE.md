# GitHub Upload Guide

## Pre-Upload Checklist

### ✅ Files Already Protected
Your `.gitignore` is configured to exclude:
- `.env` files (API keys are safe)
- `venv/` (Python virtual environment)
- `__pycache__/` and build artifacts
- `.vscode/` IDE settings
- Image files (`.jpg`, `.jpeg`, `.png`)
- Audio files (`.pcm`, `.wav`)
- Log files

### ⚠️ Before Uploading - Verify No Secrets

Run this command to check for any `.env` files:
```bash
find . -name ".env" -o -name ".env.local"
```

If any `.env` files exist, make sure they're listed in `.gitignore` (they already are).

## Step-by-Step GitHub Upload

### Option 1: Using Git Command Line

#### 1. Initialize Git Repository (if not already done)
```bash
git init
```

#### 2. Add All Files
```bash
git add .
```

#### 3. Check What Will Be Committed
```bash
git status
```

Verify that `.env` files and `venv/` are NOT listed.

#### 4. Create Initial Commit
```bash
git commit -m "Initial commit: ESP32 ASR Capture Vision MVP"
```

#### 5. Create GitHub Repository
- Go to https://github.com/new
- Create a new repository (e.g., `esp32-asr-vision-mvp`)
- Do NOT initialize with README (you already have one)
- Copy the repository URL

#### 6. Add Remote and Push
```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```

### Option 2: Using GitHub Desktop

1. Open GitHub Desktop
2. Click "Add" → "Add Existing Repository"
3. Select this project folder
4. Click "Publish repository" 
5. Choose repository name and visibility (public/private)
6. Uncheck "Keep this code private" if you want it public
7. Click "Publish Repository"

### Option 3: Using VS Code

1. Open Source Control panel (Ctrl+Shift+G)
2. Click "Initialize Repository"
3. Stage all changes (click + next to "Changes")
4. Enter commit message: "Initial commit: ESP32 ASR Capture Vision MVP"
5. Click "Commit"
6. Click "Publish Branch"
7. Choose repository name and visibility

## What Gets Uploaded

### ✅ Included Files (Safe to Upload)
```
├── .gitignore
├── .kiro/
│   └── specs/
│       └── esp32-asr-capture-vision-mvp/
│           ├── requirements.md
│           ├── design.md
│           └── tasks.md
├── backend/
│   ├── .env.example          ← Template only (safe)
│   ├── *.py                  ← All Python source files
│   └── requirements.txt
├── device/
│   ├── esp32_full_firmware.ino
│   ├── esp32_camera_test.ino
│   └── esp32_simulator.py
├── tests/
│   └── *.py
├── web/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── *.md                      ← All documentation
├── *.sh                      ← Shell scripts
├── pytest.ini
└── test_upload.py
```

### ❌ Excluded Files (Protected by .gitignore)
```
├── .env                      ← Your actual API keys (SAFE)
├── venv/                     ← Virtual environment (SAFE)
├── __pycache__/              ← Python cache (SAFE)
├── *.log                     ← Log files (SAFE)
├── images/                   ← Captured images (SAFE)
└── .vscode/                  ← IDE settings (SAFE)
```

## After Upload

### 1. Verify Upload
Visit your GitHub repository and check:
- All source files are present
- `.env` is NOT visible
- `venv/` is NOT visible
- README.md displays correctly

### 2. Add Repository Secrets (for CI/CD later)
If you plan to use GitHub Actions:
1. Go to repository Settings → Secrets and variables → Actions
2. Add secrets:
   - `DASHSCOPE_API_KEY`
   - `QWEN_API_KEY`

### 3. Update README (Optional)
Add GitHub-specific badges:
```markdown
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
```

## Security Double-Check

Before pushing, run:
```bash
# Check for potential secrets
git grep -i "api_key" -- ':!.env.example' ':!*.md'
git grep -i "secret" -- ':!.env.example' ':!*.md'
git grep -i "password" -- ':!.env.example' ':!*.md'
```

If any real secrets are found, remove them before pushing.

## Common Issues

### Issue: `.env` file was accidentally committed
**Solution:**
```bash
git rm --cached backend/.env
git commit -m "Remove .env file"
git push
```

Then change all API keys immediately.

### Issue: Large files (>100MB)
**Solution:**
GitHub has a 100MB file size limit. Your project should be fine, but if you hit this:
```bash
# Find large files
find . -type f -size +50M
```

### Issue: Too many files
**Solution:**
Your project has a reasonable number of files. If needed:
```bash
# Count files to be committed
git ls-files | wc -l
```

## Repository Settings Recommendations

After upload, configure:

1. **Branch Protection** (Settings → Branches)
   - Protect `main` branch
   - Require pull request reviews

2. **Security** (Settings → Security)
   - Enable Dependabot alerts
   - Enable secret scanning

3. **Description**
   Add: "ESP32-based voice-controlled object recognition system with ASR and vision AI"

4. **Topics**
   Add: `esp32`, `asr`, `computer-vision`, `iot`, `qwen`, `websocket`, `fastapi`

## Quick Commands Summary

```bash
# Initialize and upload
git init
git add .
git commit -m "Initial commit: ESP32 ASR Capture Vision MVP"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main

# Future updates
git add .
git commit -m "Your commit message"
git push
```

## Need Help?

- GitHub Docs: https://docs.github.com/en/get-started
- Git Basics: https://git-scm.com/book/en/v2/Getting-Started-Git-Basics
- GitHub Desktop: https://desktop.github.com/

---

**Remember:** Never commit `.env` files with real API keys. Always use `.env.example` as a template.
