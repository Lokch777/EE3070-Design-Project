#!/bin/bash
# Package project for OneDrive backup

echo "=================================="
echo "ESP32 ASR Vision MVP - Backup"
echo "=================================="
echo ""

# Create backup directory with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="esp32-asr-mvp-backup-${TIMESTAMP}"
BACKUP_DIR="${BACKUP_NAME}"

echo "Creating backup: ${BACKUP_NAME}"
mkdir -p "${BACKUP_DIR}"

# Copy essential files
echo "Copying files..."

# Backend
mkdir -p "${BACKUP_DIR}/backend"
cp backend/*.py "${BACKUP_DIR}/backend/" 2>/dev/null
cp backend/requirements.txt "${BACKUP_DIR}/backend/" 2>/dev/null
cp backend/.env.example "${BACKUP_DIR}/backend/" 2>/dev/null

# Web
mkdir -p "${BACKUP_DIR}/web"
cp web/*.html "${BACKUP_DIR}/web/" 2>/dev/null
cp web/*.css "${BACKUP_DIR}/web/" 2>/dev/null
cp web/*.js "${BACKUP_DIR}/web/" 2>/dev/null

# Device
mkdir -p "${BACKUP_DIR}/device"
cp device/*.ino "${BACKUP_DIR}/device/" 2>/dev/null
cp device/*.py "${BACKUP_DIR}/device/" 2>/dev/null

# Tests
mkdir -p "${BACKUP_DIR}/tests"
cp tests/*.py "${BACKUP_DIR}/tests/" 2>/dev/null

# Documentation
cp *.md "${BACKUP_DIR}/" 2>/dev/null
cp *.py "${BACKUP_DIR}/" 2>/dev/null
cp *.sh "${BACKUP_DIR}/" 2>/dev/null
cp *.ini "${BACKUP_DIR}/" 2>/dev/null
cp .gitignore "${BACKUP_DIR}/" 2>/dev/null

# Specs
mkdir -p "${BACKUP_DIR}/.kiro/specs/esp32-asr-capture-vision-mvp"
cp .kiro/specs/esp32-asr-capture-vision-mvp/*.md "${BACKUP_DIR}/.kiro/specs/esp32-asr-capture-vision-mvp/" 2>/dev/null

# Create archive
echo "Creating archive..."
tar -czf "${BACKUP_NAME}.tar.gz" "${BACKUP_DIR}"

# Also create zip for Windows
zip -r "${BACKUP_NAME}.zip" "${BACKUP_DIR}" > /dev/null 2>&1

# Clean up temporary directory
rm -rf "${BACKUP_DIR}"

echo ""
echo "✅ Backup complete!"
echo ""
echo "Files created:"
echo "  - ${BACKUP_NAME}.tar.gz (for Linux/Mac)"
echo "  - ${BACKUP_NAME}.zip (for Windows)"
echo ""
echo "Upload these files to OneDrive"
echo ""

# Show file sizes
ls -lh "${BACKUP_NAME}".* 2>/dev/null
