
# ===================================
# startup.py - Application Startup Script
# ===================================

#!/usr/bin/env python3
"""
Startup script for Financial Analytics Dashboard API
"""

import sys
import os
import subprocess
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.8+"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ is required")
        sys.exit(1)
    print(f"✅ Python {sys.version}")

def check_env_file():
    """Check if .env file exists"""
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ .env file not found")
        print("📝 Please create a .env file with your Alpha Vantage API key:")
        print("   ALPHA_VANTAGE_API_KEY=your_api_key_here")
        sys.exit(1)
    print("✅ .env file found")

def install_requirements():
    """Install required packages"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Requirements installed")
    except subprocess.CalledProcessError:
        print("❌ Failed to install requirements")
        sys.exit(1)

def start_server():
    """Start the FastAPI server"""
    try:
        print("🚀 Starting FastAPI server...")
        print("📍 API will be available at: http://localhost:8000")
        print("📚 API Documentation: http://localhost:8000/docs")
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "main:app", 
            "--host", "0.0.0.0", 
            "--port", "8000", 
            "--reload"
        ])
    except KeyboardInterrupt:
        print("\n👋 Server stopped")

def main():
    """Main startup function"""
    print("🏗️  Financial Analytics Dashboard API - Startup")
    print("=" * 50)
    
    check_python_version()
    check_env_file()
    install_requirements()
    start_server()

if __name__ == "__main__":
    main()
