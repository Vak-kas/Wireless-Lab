#!/usr/bin/env python3
"""앱 아이콘을 만든다(macOS): tools/icon/wireless-lab.svg → "Wireless Lab.app" 안의 AppIcon.icns, 그리고 화면의 파비콘.

    venv/bin/python tools/make_icon.py

그림을 바꾸려면 SVG 를 고치고 이 스크립트를 다시 돌린다. macOS 의 AppKit(pyobjc)과 iconutil 을 쓴다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "tools" / "icon" / "wireless-lab.svg"
ICNS = ROOT / "Wireless Lab.app" / "Contents" / "Resources" / "AppIcon.icns"
PNG = ROOT / "tools" / "icon" / "wireless-lab.png"          # 실행기가 독 아이콘으로 쓴다
FAVICON = ROOT / "web" / "public" / "favicon.png"
SIZES = [16, 32, 128, 256, 512]


def render(size: int, out: Path) -> None:
    """SVG 를 size × size 픽셀 PNG 로 그린다."""
    from AppKit import (
        NSBitmapImageRep,
        NSCalibratedRGBColorSpace,
        NSGraphicsContext,
        NSImage,
        NSMakeRect,
        NSPNGFileType,
    )

    image = NSImage.alloc().initWithContentsOfFile_(str(SVG))
    if image is None:
        raise SystemExit(f"SVG 를 읽지 못했습니다: {SVG}")
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)
    image.drawInRect_(NSMakeRect(0, 0, size, size))
    NSGraphicsContext.restoreGraphicsState()
    out.parent.mkdir(parents=True, exist_ok=True)
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(out), True)


def main() -> int:
    if sys.platform != "darwin":
        print("macOS 에서만 만듭니다.")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        for size in SIZES:
            render(size, iconset / f"icon_{size}x{size}.png")
            render(size * 2, iconset / f"icon_{size}x{size}@2x.png")
        ICNS.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    render(512, PNG)
    render(64, FAVICON)
    print(f"만들었습니다: {ICNS.relative_to(ROOT)}, {PNG.relative_to(ROOT)}, {FAVICON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
