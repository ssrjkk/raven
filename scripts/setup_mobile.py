"""Raven AI Mobile App Setup — Capacitor (iOS + Android)

Usage:
    python scripts/setup_mobile.py               # Install + init both platforms
    python scripts/setup_mobile.py --ios          # iOS only
    python scripts/setup_mobile.py --android      # Android only
    python scripts/setup_mobile.py --skip-install # Skip npm install
    python scripts/setup_mobile.py --update       # Just sync (after web build)

Requirements:
    Node.js 20+, npm 9+
    iOS: Xcode 15+
    Android: Android Studio, Android SDK 34+
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")


def run(cmd: list[str], cwd: str = WEB_DIR) -> None:
    print(f"[mobile] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"[mobile] ERROR: Command failed with code {result.returncode}")
        sys.exit(result.returncode)


def check_capacitor_config() -> None:
    config_path = os.path.join(WEB_DIR, "capacitor.config.ts")
    if not os.path.exists(config_path):
        print(f"[mobile] ERROR: {config_path} not found")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup Raven AI mobile app")
    parser.add_argument("--ios", action="store_true", help="Init iOS platform")
    parser.add_argument("--android", action="store_true", help="Init Android platform")
    parser.add_argument("--skip-install", action="store_true", help="Skip npm install")
    parser.add_argument("--update", action="store_true", help="Rebuild web + cap sync (skip install)")
    args = parser.parse_args()

    check_capacitor_config()

    if not args.update and not args.skip_install:
        print("[mobile] Adding Capacitor dependencies...")
        run(["npm", "install", "--save-dev", "@capacitor/cli@^7.0.0"])
        run(["npm", "install", "--save",
             "@capacitor/core@^7.0.0",
             "@capacitor/camera@^7.0.0",
             "@capacitor/geolocation@^7.0.0",
             "@capacitor/preferences@^7.0.0",
             "@capacitor/push-notifications@^7.0.0",
             "@capacitor/local-notifications@^7.0.0",
             "@capacitor/status-bar@^7.0.0",
             "@capacitor/splash-screen@^7.0.0",
             "@capacitor/haptics@^7.0.0",
             "@capacitor/network@^7.0.0",
             "@capacitor/clipboard@^7.0.0",
             "@capacitor/dialog@^7.0.0"])

    # Build the web app
    print("[mobile] Building web app...")
    run(["npm", "run", "build"])

    if args.ios or not (args.android or args.ios):
        print("[mobile] Initializing iOS platform...")
        run(["npx", "cap", "add", "ios"])

    if args.android or not (args.ios or args.android):
        print("[mobile] Initializing Android platform...")
        run(["npx", "cap", "add", "android"])

    print("[mobile] Syncing Capacitor...")
    run(["npx", "cap", "sync"])

    print()
    print("=" * 50)
    print("Mobile setup complete!")
    print("=" * 50)
    print()
    print("To open in Xcode:")
    print("  cd web && npx cap open ios")
    print()
    print("To open in Android Studio:")
    print("  cd web && npx cap open android")
    print()
    print("To rebuild after web changes:")
    print("  python scripts/setup_mobile.py --update")
    print()
    print("To build a release APK:")
    print("  cd web/android && ./gradlew assembleRelease")
    print()
    print("To build a release IPA:")
    print("  cd web/ios && xcodebuild -workspace App.xcworkspace -scheme App archive")
    print()


if __name__ == "__main__":
    main()
