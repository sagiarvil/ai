#!/usr/bin/env python3
"""Build a local Dock-launchable macOS app using the user's unmodified logo."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parent
BUNDLE_ID = "tr.barisai.local.launcher"

SWIFT = r"""
import AppKit
import Foundation
let args = CommandLine.arguments
guard let image = NSImage(contentsOfFile: args[1]),
      image.size.width > 0, image.size.height > 0 else {
    fputs("Logo okunamadi.\n", stderr); exit(1)
}
let target = URL(fileURLWithPath: args[2], isDirectory: true)
let entries: [(String, Int)] = [
 ("icon_16x16.png",16), ("icon_16x16@2x.png",32),
 ("icon_32x32.png",32), ("icon_32x32@2x.png",64),
 ("icon_128x128.png",128), ("icon_128x128@2x.png",256),
 ("icon_256x256.png",256), ("icon_256x256@2x.png",512),
 ("icon_512x512.png",512), ("icon_512x512@2x.png",1024)]
for (name, size) in entries {
 guard let bitmap = NSBitmapImageRep(
  bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
  isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
  let context = NSGraphicsContext(bitmapImageRep: bitmap) else { exit(2) }
 NSGraphicsContext.saveGraphicsState()
 NSGraphicsContext.current = context
 context.imageInterpolation = .high
 let side = CGFloat(size)
 NSColor.clear.setFill()
 NSRect(x: 0, y: 0, width: side, height: side).fill()
 let ratio = min(side / image.size.width, side / image.size.height)
 let width = image.size.width * ratio
 let height = image.size.height * ratio
 image.draw(in: NSRect(x: (side-width)/2, y: (side-height)/2,
                      width: width, height: height),
            from: .zero, operation: .sourceOver, fraction: 1)
 NSGraphicsContext.restoreGraphicsState()
 guard let data = bitmap.representation(using: .png, properties: [:]) else { exit(3) }
 try data.write(to: target.appendingPathComponent(name))
}
"""

HELPER = r"""
import json
from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1])
log_dir = source / ".baris_runtime"
log_dir.mkdir(exist_ok=True)
log = log_dir / "app-launch.log"
try:
    with log.open("ab") as output:
        result = subprocess.run(
            [sys.executable, str(source / "baris_local.py"), "start", "--port", "5053"],
            cwd=source, stdout=output, stderr=subprocess.STDOUT, timeout=90)
    if result.returncode:
        raise RuntimeError(log.read_text(errors="replace")[-2000:])
except Exception as exc:
    message = "Barış AI açılamadı.\n" + str(exc) + "\nKayıt: " + str(log)
    subprocess.run([
        "/usr/bin/osascript", "-e",
        'on run argv\ndisplay alert "Barış AI" message (item 1 of argv) as critical\nend run',
        message])
    raise SystemExit(1)
"""


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def choose_logo():
    result = run([
        "/usr/bin/osascript", "-e",
        'POSIX path of (choose file with prompt '
        '"Barış AI simgesi için gönderdiğiniz B logosunu seçin" '
        'of type {"public.png", "public.jpeg", "public.tiff"})'
    ])
    return Path(result.stdout.strip()).resolve()


def install(logo, applications):
    if sys.platform != "darwin":
        raise RuntimeError("Bu kurucu yalnızca macOS üzerinde çalışır.")
    if not (SOURCE / "baris_local.py").is_file():
        raise RuntimeError("Çalışan yerel başlatıcı bu dizinde bulunamadı.")
    logo = Path(logo).resolve()
    if not logo.is_file():
        raise RuntimeError("Seçilen logo dosyası bulunamadı.")
    if not Path(sys.executable).is_file():
        raise RuntimeError("Python yorumlayıcısı bulunamadı.")
    applications = Path(applications).expanduser().resolve()
    applications.mkdir(parents=True, exist_ok=True)
    destination = applications / "Barış AI.app"
    if destination.exists():
        info = destination / "Contents" / "Info.plist"
        if not info.is_file() or plistlib.loads(info.read_bytes()).get(
                "CFBundleIdentifier") != BUNDLE_ID:
            raise RuntimeError("Aynı adlı farklı uygulama var; üzerine yazılmadı.")

    print("Logo oranı ve şeffaflığı korunarak simge hazırlanıyor...", flush=True)
    with tempfile.TemporaryDirectory(prefix="baris-app-", dir=applications) as directory:
        temporary = Path(directory)
        iconset = temporary / "BarisAI.iconset"
        iconset.mkdir()
        swift_file = temporary / "icon.swift"
        swift_file.write_text(SWIFT, encoding="utf-8")
        run(["/usr/bin/swift", str(swift_file), str(logo), str(iconset)])

        bundle = temporary / "Barış AI.app"
        contents = bundle / "Contents"
        resources = contents / "Resources"
        executable_dir = contents / "MacOS"
        resources.mkdir(parents=True)
        executable_dir.mkdir()
        icon = resources / "BarisAI.icns"
        run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icon)])

        helper = resources / "launch.py"
        helper.write_text(HELPER, encoding="utf-8")
        executable = executable_dir / "BarisAI"
        executable.write_text(
            "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
            shlex.quote(str(destination / "Contents/Resources/launch.py")) +
            " " + shlex.quote(str(SOURCE)) + "\n", encoding="utf-8")
        executable.chmod(0o755)
        info = {
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleName": "Barış AI",
            "CFBundleDisplayName": "Barış AI",
            "CFBundleExecutable": "BarisAI",
            "CFBundleIconFile": "BarisAI.icns",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        if icon.stat().st_size == 0:
            raise RuntimeError("Uygulama simgesi üretilemedi.")
        if destination.exists():
            backup = applications / (
                "Barış AI.backup-" + time.strftime("%Y%m%d-%H%M%S") +
                "-" + str(os.getpid()) + ".app")
            destination.rename(backup)
            try:
                bundle.rename(destination)
            except BaseException:
                backup.rename(destination)
                raise
            print("Önceki sürüm yedeği:", backup)
        else:
            bundle.rename(destination)

    # Runtime readback: inspect the installed bundle, not only the staging files.
    actual = plistlib.loads((destination / "Contents/Info.plist").read_bytes())
    if actual["CFBundleIdentifier"] != BUNDLE_ID:
        raise RuntimeError("Uygulama kimliği doğrulanamadı.")
    if not os.access(destination / "Contents/MacOS/BarisAI", os.X_OK):
        raise RuntimeError("Başlatıcı çalıştırılabilir değil.")
    compile((destination / "Contents/Resources/launch.py").read_text(), "launch.py", "exec")
    print(json.dumps({
        "app": str(destination), "icon_bytes":
        (destination / "Contents/Resources/BarisAI.icns").stat().st_size,
        "source": str(SOURCE), "bundle_readback": True
    }, ensure_ascii=False, indent=2))
    run(["/usr/bin/open", "-R", str(destination)])
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logo", type=Path)
    parser.add_argument("--applications", type=Path, default=Path.home() / "Applications")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    logo = args.logo or choose_logo()
    app = install(logo, args.applications)
    if args.open:
        run(["/usr/bin/open", str(app)])


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit("macOS araç hatası: " + (exc.stderr or str(exc)))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit("Kurulum hatası: " + str(exc))
