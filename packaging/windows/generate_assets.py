"""Generate Windows packaging assets for PyInstaller and Inno Setup."""

from __future__ import annotations

import argparse
from pathlib import Path
import tomllib

from PIL import Image, ImageDraw


def load_version(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data["project"]["version"]


def parse_version_parts(version: str) -> tuple[int, int, int, int]:
    parts = version.split(".")
    normalized = [int(part) for part in parts[:3]]
    while len(normalized) < 3:
        normalized.append(0)
    normalized.append(0)
    return tuple(normalized)


def build_icon(icon_path: Path) -> None:
    icon_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 228, 228), radius=44, fill=(30, 33, 45, 255))
    draw.rounded_rectangle((96, 58, 160, 144), radius=28, fill=(241, 245, 249, 255))
    draw.rectangle((112, 144, 144, 186), fill=(241, 245, 249, 255))
    draw.arc((64, 86, 192, 192), start=200, end=340, fill=(125, 211, 252, 255), width=12)
    draw.line((66, 192, 190, 192), fill=(125, 211, 252, 255), width=12)
    image.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])


def build_version_file(version: str, version_path: Path) -> None:
    version_path.parent.mkdir(parents=True, exist_ok=True)
    major, minor, patch, build = parse_version_parts(version)
    version_tuple = f"({major}, {minor}, {patch}, {build})"
    version_text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Alan Banks'),
            StringStruct('FileDescription', 'Vocal-Scriber Windows Tray App'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'Vocal-Scriber'),
            StringStruct('OriginalFilename', 'Vocal-Scriber.exe'),
            StringStruct('ProductName', 'Vocal-Scriber'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    version_path.write_text(version_text, encoding="utf-8")


def build_inno_version_file(version: str, inno_version_path: Path) -> None:
    inno_version_path.parent.mkdir(parents=True, exist_ok=True)
    inno_version_path.write_text(f'#define MyAppVersion "{version}"\n', encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Windows packaging assets.")
    parser.add_argument("--pyproject", required=True, help="Path to pyproject.toml")
    parser.add_argument("--output-dir", required=True, help="Directory for generated assets")
    args = parser.parse_args()

    pyproject_path = Path(args.pyproject).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    version = load_version(pyproject_path)
    build_icon(output_dir / "vocal_scriber.ico")
    build_version_file(version, output_dir / "version_info.txt")
    build_inno_version_file(version, output_dir / "version.iss")


if __name__ == "__main__":
    main()
