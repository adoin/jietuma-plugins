"""Build Windows preview plugins and package them as .jtbplugin ZIP files."""
import json
import argparse
import io
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plugin', default='', help='Package only this plugin ID')
    args = parser.parse_args()
    manifests = [json.loads(p.read_text(encoding='utf-8')) | {'_path': p} for p in sorted((ROOT / 'plugins').glob('*/plugin.json'))]
    if args.plugin:
        manifests = [m for m in manifests if m['id'] == args.plugin]
        if not manifests:
            parser.error('Unknown plugin ID')
    command = ["cargo", "build", "--release", "--locked"]
    if args.plugin and manifests[0].get('command'):
        command += ['--bin', pathlib.Path(manifests[0]['command']).stem]
    subprocess.run(command, cwd=ROOT, check=True)
    metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--format-version", "1", "--locked"], cwd=ROOT))
    licenses = []
    for crate in metadata["packages"]:
        if not crate.get("source"):
            continue
        folder = pathlib.Path(crate["manifest_path"]).parent
        for license_path in sorted(folder.glob("LICENSE*")):
            if license_path.is_file():
                licenses.append((license_path, f"{crate['name']} {crate['version']} / {license_path.name}"))
    notices = "\n\n".join(f"===== {name} =====\n{path.read_text(encoding='utf-8', errors='replace')}" for path, name in licenses)
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    for manifest in manifests:
        manifest_path = manifest['_path']
        output = destination / f"{manifest['id']}-{manifest['version']}.jtbplugin"
        archive_bytes=io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as package:
            package.write(manifest_path, "plugin.json")
            for asset in ('icon.png','icon.svg','plugin.ico'):
                asset_path=manifest_path.parent/asset
                if asset_path.is_file():
                    package.write(asset_path,asset,compress_type=zipfile.ZIP_STORED if asset=='plugin.ico' else zipfile.ZIP_DEFLATED)
            if "command" in manifest:
                executable = ROOT / "target" / "release" / manifest["command"]
                package.write(executable, manifest["command"])
            icons = set()
            for entry in manifest.get("contributes", {}).get("toolbar", []):
                if icon := entry.get("icon"):
                    path = pathlib.PurePosixPath(icon)
                    if path.is_absolute() or ".." in path.parts or "\\" in icon or ":" in icon:
                        raise ValueError(f"Unsafe icon path: {icon}")
                    if icon not in icons:
                        package.write(manifest_path.parent.joinpath(*path.parts), icon)
                        icons.add(icon)
            package.write(ROOT / "LICENSE", "licenses/jietuma-plugins-LICENSE")
            package.writestr("licenses/THIRD_PARTY_LICENSES.txt", notices.encode("utf-8"))
        icon=manifest_path.parent/'plugin.ico'
        output.write_bytes((icon.read_bytes() if icon.is_file() else b'')+archive_bytes.getvalue())
        print(output)

if __name__ == "__main__":
    main()
