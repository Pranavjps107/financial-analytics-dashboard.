# setup.py - Quick Setup Script
import os
import sys
from pathlib import Path

def create_env_file():
    """Create .env file with example configuration"""
    env_content = """# Alpha Vantage API Keys Configuration
# You can use any of these methods:

# Method 1: Multiple keys (comma-separated) - RECOMMENDED
ALPHA_VANTAGE_API_KEYS=demo,your_key_2,your_key_3,your_key_4,your_key_5

# Method 2: Individual numbered keys
# ALPHA_VANTAGE_API_KEY_1=your_first_key_here
# ALPHA_VANTAGE_API_KEY_2=your_second_key_here
# ALPHA_VANTAGE_API_KEY_3=your_third_key_here

# Method 3: Single key (fallback)
# ALPHA_VANTAGE_API_KEY=your_single_key_here

# Optional: Router Configuration
ROUTER_STRATEGY=round_robin
ROUTER_MAX_RETRIES=3

# Optional: Other services
# SUPABASE_URL=your_supabase_url
# SUPABASE_KEY=your_supabase_key
# REDIS_URL=redis://localhost:6379
"""
    
    env_path = Path(".env")
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write(env_content)
        print("✅ Created .env file with example configuration")
        print("📝 Please edit .env file and add your Alpha Vantage API keys")
    else:
        print("ℹ️  .env file already exists")

def create_requirements_file():
    """Create requirements.txt file"""
    requirements = """fastapi==0.104.1
uvicorn[standard]==0.24.0
requests==2.31.0
python-dotenv==1.0.0
pydantic==2.5.0
"""
    
    req_path = Path("requirements.txt")
    if not req_path.exists():
        with open(req_path, "w") as f:
            f.write(requirements)
        print("✅ Created requirements.txt")
    else:
        print("ℹ️  requirements.txt already exists")

def install_requirements():
    """Install required packages"""
    try:
        import subprocess
        print("📦 Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Requirements installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install requirements: {e}")
        return False
    return True

def check_api_keys():
    """Check if API keys are configured"""
    from dotenv import load_dotenv
    load_dotenv()
    
    # Check different methods
    keys_found = []
    
    # Method 1: Comma-separated
    keys_string = os.getenv("ALPHA_VANTAGE_API_KEYS")
    if keys_string:
        keys = [key.strip() for key in keys_string.split(",") if key.strip()]
        keys_found.extend(keys)
    
    # Method 2: Individual numbered keys
    i = 1
    while True:
        key = os.getenv(f"ALPHA_VANTAGE_API_KEY_{i}")
        if key and key.strip():
            keys_found.append(key.strip())
            i += 1
        else:
            break
    
    # Method 3: Single key
    if not keys_found:
        single_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if single_key and single_key.strip():
            keys_found.append(single_key.strip())
    
    if keys_found:
        print(f"✅ Found {len(keys_found)} API key(s) configured")
        for i, key in enumerate(keys_found, 1):
            print(f"   Key {i}: ...{key[-4:] if len(key) > 4 else key}")
        return True
    else:
        print("❌ No API keys found!")
        print("📝 Please edit .env file and add your Alpha Vantage API keys")
        return False

def main():
    """Main setup function"""
    print("🚀 Financial Analytics Dashboard - Setup")
    print("=" * 50)
    
    # Create necessary files
    create_env_file()
    create_requirements_file()
    
    # Install requirements
    if not install_requirements():
        return
    
    # Check API keys
    if not check_api_keys():
        print("\n⚠️  Setup incomplete - please configure API keys in .env file")
        return
    
    print("\n🎉 Setup completed successfully!")
    print("\n🚀 To start the server, run:")
    print("   python main.py")
    print("\n📚 Or use uvicorn directly:")
    print("   uvicorn main:app --reload")
    print("\n🌐 The API will be available at:")
    print("   http://localhost:8000")
    print("   http://localhost:8000/docs (API documentation)")

if __name__ == "__main__":
    main()