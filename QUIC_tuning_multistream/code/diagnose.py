#!/usr/bin/env python3
"""
Diagnostic script to check wireless bottleneck setup.

Run this first to verify everything is configured correctly.

Usage:
    python3 diagnose.py
"""

import sys
import subprocess
from pathlib import Path


def check_python():
    """Check Python version."""
    print("🔍 Checking Python...")
    print(f"   Version: {sys.version}")
    print(f"   Executable: {sys.executable}")
    if sys.version_info >= (3, 8):
        print("   ✓ Python version OK\n")
        return True
    else:
        print("   ✗ Python 3.8+ required\n")
        return False


def check_tc():
    """Check if tc command is available."""
    print("🔍 Checking tc (Traffic Control)...")
    try:
        result = subprocess.run(
            ["tc", "-Version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        print(f"   Version: {result.stderr.strip() if result.stderr else result.stdout.strip()}")
        print("   ✓ tc command available\n")
        return True
    except FileNotFoundError:
        print("   ✗ tc command not found")
        print("   Install with: apt-get install iproute2\n")
        return False
    except Exception as e:
        print(f"   ✗ Error checking tc: {e}\n")
        return False


def check_privileges():
    """Check if we have necessary privileges for tc."""
    print("🔍 Checking privileges...")
    try:
        # Try to list tc rules (read-only operation)
        result = subprocess.run(
            ["tc", "qdisc", "show", "dev", "lo"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("   ✓ Can access tc (sufficient privileges)\n")
            return True
        else:
            print("   ✗ Cannot access tc")
            print("   Try running with sudo or in Docker with --privileged\n")
            return False
    except Exception as e:
        print(f"   ✗ Error: {e}\n")
        return False


def check_module_structure():
    """Check if wireless_bottleneck module is available."""
    print("🔍 Checking module structure...")
    
    code_dir = Path.cwd()
    wb_dir = code_dir / "wireless_bottleneck"
    
    print(f"   Current directory: {code_dir}")
    print(f"   Looking for: {wb_dir}")
    
    if not wb_dir.exists():
        print("   ✗ wireless_bottleneck directory not found")
        print(f"   Expected at: {wb_dir}")
        print("   Make sure you're in the /app/code directory\n")
        return False
    
    required_files = ["__init__.py", "config.py", "scenarios.py", "bottleneck.py", "monitor.py"]
    missing = []
    
    for file in required_files:
        file_path = wb_dir / file
        if file_path.exists():
            print(f"   ✓ {file}")
        else:
            print(f"   ✗ {file} missing")
            missing.append(file)
    
    if not missing:
        print("   ✓ All required files present\n")
        return True
    else:
        print(f"   ✗ Missing files: {', '.join(missing)}\n")
        return False


def check_module_import():
    """Try to import the wireless_bottleneck module."""
    print("🔍 Checking module import...")
    
    try:
        sys.path.insert(0, str(Path.cwd()))
        from wireless_bottleneck import (
            WirelessBottleneck,
            BottleneckConfig,
            get_scenario,
            list_scenarios,
        )
        print("   ✓ wireless_bottleneck module imported successfully")
        
        scenarios = list_scenarios()
        print(f"   ✓ Found {len(scenarios)} scenarios: {', '.join(scenarios)}\n")
        return True
    except ImportError as e:
        print(f"   ✗ Import error: {e}")
        print("   Check that all module files are present\n")
        return False
    except Exception as e:
        print(f"   ✗ Error: {e}\n")
        return False


def check_example_files():
    """Check if example files are present."""
    print("🔍 Checking example files...")
    
    examples_dir = Path.cwd() / "examples"
    
    if not examples_dir.exists():
        print("   ⚠ examples directory not found")
        print("   Example scripts won't be available\n")
        return False
    
    test_file = Path.cwd() / "test_bottleneck_only.py"
    if test_file.exists():
        print("   ✓ test_bottleneck_only.py found")
    else:
        print("   ⚠ test_bottleneck_only.py not found")
    
    quickstart = examples_dir / "quickstart.py"
    if quickstart.exists():
        print("   ✓ examples/quickstart.py found")
    else:
        print("   ⚠ examples/quickstart.py not found")
    
    print()
    return True


def print_next_steps(results):
    """Print recommendations based on diagnostic results."""
    print("=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print()
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"{status} {check}")
    
    print()
    
    if all_passed:
        print("✅ All checks passed! You're ready to go.")
        print()
        print("🚀 Next steps:")
        print("   1. Test bottleneck: python3 test_bottleneck_only.py")
        print("   2. List scenarios:  python3 -m wireless_bottleneck list")
        print("   3. Run validation:  python3 -m wireless_bottleneck validate")
        print("   4. Try example:     python3 examples/quickstart.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        print()
        print("💡 Common fixes:")
        
        if not results.get("tc available"):
            print("   • Install iproute2: apt-get update && apt-get install -y iproute2")
        
        if not results.get("Privileges"):
            print("   • Run in Docker with --privileged flag")
            print("   • Or use: sudo python3 diagnose.py")
        
        if not results.get("Module structure") or not results.get("Module import"):
            print("   • Make sure you're in the correct directory: cd /app/code")
            print("   • Verify files are mounted: ls -la wireless_bottleneck/")
        
        print()
        print("🐳 If in Docker, make sure you started with:")
        print("   docker run --rm -it --privileged \\")
        print("       -v \"$(pwd)/code:/app/code\" \\")
        print("       -w /app/code \\")
        print("       ubuntu:22.04 bash")
    
    print()


def main():
    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║        Wireless Bottleneck - Diagnostic Tool                      ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print("Running diagnostic checks...\n")
    
    results = {}
    
    # Run all checks
    results["Python 3.8+"] = check_python()
    results["tc available"] = check_tc()
    results["Privileges"] = check_privileges()
    results["Module structure"] = check_module_structure()
    results["Module import"] = check_module_import()
    results["Example files"] = check_example_files()
    
    # Print summary and recommendations
    print_next_steps(results)
    
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
