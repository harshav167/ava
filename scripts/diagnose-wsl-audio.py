#!/usr/bin/env python3
"""
Diagnostic script for WSL2 audio issues with voice-mode.

This script checks various audio subsystems and provides recommendations
for getting microphone access working in WSL2.
"""

import os
import sys
import subprocess
import platform

def check_command(cmd):
    """Check if a command exists"""
    try:
        subprocess.run(["which", cmd], capture_output=True, check=True)
        return True
    except:
        return False

def run_command(cmd, shell=False):
    """Run a command and return output"""
    try:
        result = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_wsl_version():
    """Check if running in WSL and get version info"""
    if not os.path.exists("/proc/version"):
        return False, None
    
    with open("/proc/version", "r") as f:
        version_string = f.read()
    
    is_wsl = "microsoft" in version_string.lower() or "wsl" in version_string.lower()
    
    # Try to get WSL version
    wsl_version = "Unknown"
    if os.path.exists("/proc/sys/kernel/osrelease"):
        with open("/proc/sys/kernel/osrelease", "r") as f:
            osrelease = f.read().strip()
            if "WSL2" in osrelease:
                wsl_version = "WSL2"
            elif "Microsoft" in osrelease:
                wsl_version = "WSL1"
    
    return is_wsl, wsl_version

def check_audio_packages():
    """Check if required audio packages are installed"""
    packages = {
        "libasound2-plugins": "ALSA plugins for PulseAudio",
        "pulseaudio": "PulseAudio sound server",
        "pulseaudio-utils": "PulseAudio utilities",
        "libportaudio2": "PortAudio library",
        "portaudio19-dev": "PortAudio development files",
    }
    
    installed = {}
    for pkg, desc in packages.items():
        success, stdout, _ = run_command(["dpkg", "-l", pkg])
        installed[pkg] = success and "ii" in stdout
    
    return installed

def check_pulseaudio():
    """Check PulseAudio status"""
    checks = {}
    
    # Check if PulseAudio is running
    success, stdout, _ = run_command(["pgrep", "-x", "pulseaudio"])
    checks["running"] = success
    
    # Check if we can connect to PulseAudio
    if check_command("pactl"):
        success, stdout, stderr = run_command(["pactl", "info"])
        checks["connectable"] = success
        checks["info"] = stdout if success else stderr
    else:
        checks["connectable"] = False
        checks["info"] = "pactl not found"
    
    # Check for audio sources
    if check_command("pactl"):
        success, stdout, _ = run_command(["pactl", "list", "sources", "short"])
        checks["sources"] = stdout if success else "No sources found"
    
    return checks

def check_alsa():
    """Check ALSA status"""
    checks = {}
    
    # Check for ALSA devices
    if check_command("aplay"):
        success, stdout, stderr = run_command(["aplay", "-l"])
        checks["devices"] = stdout if success else stderr
    else:
        checks["devices"] = "aplay not found"
    
    # Check for recording devices
    if check_command("arecord"):
        success, stdout, stderr = run_command(["arecord", "-l"])
        checks["recording_devices"] = stdout if success else stderr
    else:
        checks["recording_devices"] = "arecord not found"
    
    return checks

def check_python_audio():
    """Check Python audio libraries"""
    checks = {}
    
    # Check sounddevice
    try:
        import sounddevice as sd
        checks["sounddevice_installed"] = True
        
        # Try to query devices
        try:
            devices = sd.query_devices()
            checks["devices_found"] = len(str(devices)) > 0
            checks["device_list"] = str(devices)
            
            # Check for input devices
            input_devices = []
            if hasattr(devices, '__iter__'):
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0:
                        input_devices.append(f"{i}: {dev['name']}")
            checks["input_devices"] = input_devices if input_devices else ["No input devices found"]
            
        except Exception as e:
            checks["devices_found"] = False
            checks["device_error"] = str(e)
            
    except ImportError:
        checks["sounddevice_installed"] = False
    
    # Check numpy (required by sounddevice)
    try:
        import numpy
        checks["numpy_installed"] = True
    except ImportError:
        checks["numpy_installed"] = False
    
    return checks

def check_windows_integration():
    """Check WSLg and Windows integration"""
    checks = {}
    
    # Check for WSLg
    checks["wslg"] = os.path.exists("/mnt/wslg")
    
    # Check for X11
    checks["display"] = os.environ.get("DISPLAY", "Not set")
    
    # Check for PulseAudio socket
    checks["pulse_socket"] = os.path.exists("/mnt/wslg/PulseAudio")
    
    # Check Windows IP (for network audio)
    success, stdout, _ = run_command(["grep", "nameserver", "/etc/resolv.conf"])
    if success and stdout:
        checks["windows_ip"] = stdout.strip().split()[-1]
    else:
        checks["windows_ip"] = "Unknown"
    
    return checks

def print_recommendations(is_wsl, wsl_version, packages, pulse_checks, python_checks, wslg_checks):
    """Print recommendations based on checks"""
    print("\n=== RECOMMENDATIONS ===\n")
    
    if not is_wsl:
        print("✓ Not running in WSL - audio should work normally")
        return
    
    recommendations = []
    
    # Package recommendations
    missing_packages = [pkg for pkg, installed in packages.items() if not installed]
    if missing_packages:
        recommendations.append(f"Install missing packages:\n  sudo apt update && sudo apt install -y {' '.join(missing_packages)}")
    
    # PulseAudio recommendations
    if not pulse_checks.get("running"):
        recommendations.append("Start PulseAudio:\n  pulseaudio --start")
    elif not pulse_checks.get("connectable"):
        recommendations.append("PulseAudio is running but not connectable. Try:\n  pulseaudio -k && pulseaudio --start")
    
    # WSLg recommendations
    if wsl_version == "WSL2" and not wslg_checks.get("wslg"):
        recommendations.append("WSLg not detected. Update WSL:\n  In Windows: wsl --update")
    
    # Python audio recommendations
    if not python_checks.get("sounddevice_installed"):
        recommendations.append("Install Python audio libraries:\n  pip install sounddevice numpy scipy")
    elif not python_checks.get("devices_found"):
        if wslg_checks.get("pulse_socket"):
            recommendations.append("WSLg PulseAudio socket found. Try:\n  export PULSE_SERVER=unix:/mnt/wslg/PulseAudio")
        else:
            recommendations.append("No audio devices found. Check Windows microphone permissions:\n  Windows Settings → Privacy → Microphone → Allow desktop apps")
    
    # Alternative solutions
    if wsl_version == "WSL2":
        recommendations.append("\nAlternative Solutions:")
        recommendations.append("1. Use LiveKit transport instead of local microphone")
        recommendations.append("2. Set up PulseAudio server on Windows")
        recommendations.append("3. Use USB microphone with usbipd-win")
        recommendations.append("4. Run voice-mode on native Linux or in Docker")
    
    if recommendations:
        for rec in recommendations:
            print(f"\n• {rec}")
    else:
        print("✓ Everything looks good! Audio should be working.")

def main():
    print("=== Voice-Mode WSL Audio Diagnostic Tool ===\n")
    
    # Check if running in WSL
    is_wsl, wsl_version = check_wsl_version()
    print(f"Running in WSL: {is_wsl}")
    if is_wsl:
        print(f"WSL Version: {wsl_version}")
    print()
    
    # Check packages
    print("Checking audio packages...")
    packages = check_audio_packages()
    for pkg, installed in packages.items():
        status = "✓" if installed else "✗"
        print(f"  {status} {pkg}")
    print()
    
    # Check PulseAudio
    print("Checking PulseAudio...")
    pulse_checks = check_pulseaudio()
    print(f"  Running: {'✓' if pulse_checks.get('running') else '✗'}")
    print(f"  Connectable: {'✓' if pulse_checks.get('connectable') else '✗'}")
    if pulse_checks.get("sources"):
        print(f"  Audio sources: {len(pulse_checks['sources'].strip().split('\\n')) if pulse_checks['sources'].strip() else 0}")
    print()
    
    # Check ALSA
    print("Checking ALSA...")
    alsa_checks = check_alsa()
    if "no soundcards found" in alsa_checks.get("devices", "").lower():
        print("  ✗ No ALSA devices found")
    else:
        print("  ✓ ALSA devices available")
    print()
    
    # Check Python audio
    print("Checking Python audio libraries...")
    python_checks = check_python_audio()
    print(f"  sounddevice: {'✓' if python_checks.get('sounddevice_installed') else '✗'}")
    print(f"  numpy: {'✓' if python_checks.get('numpy_installed') else '✗'}")
    if python_checks.get("sounddevice_installed"):
        print(f"  Devices found: {'✓' if python_checks.get('devices_found') else '✗'}")
        if python_checks.get("input_devices"):
            print(f"  Input devices: {len(python_checks['input_devices'])}")
    print()
    
    # Check Windows integration
    if is_wsl:
        print("Checking Windows integration...")
        wslg_checks = check_windows_integration()
        print(f"  WSLg: {'✓' if wslg_checks.get('wslg') else '✗'}")
        print(f"  DISPLAY: {wslg_checks.get('display')}")
        print(f"  PulseAudio socket: {'✓' if wslg_checks.get('pulse_socket') else '✗'}")
        print(f"  Windows IP: {wslg_checks.get('windows_ip')}")
    else:
        wslg_checks = {}
    
    # Print recommendations
    print_recommendations(is_wsl, wsl_version, packages, pulse_checks, python_checks, wslg_checks)

if __name__ == "__main__":
    main()