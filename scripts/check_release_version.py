"""Validate independent plugin versions and select assets for a release tag."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
TAG = re.compile(rf"(?:(?P<plugin>[a-z0-9][a-z0-9._-]*)/)?v(?P<version>{VERSION})\Z")

def validate(tag: str, plugins: dict[str, str]) -> tuple[str, str]:
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("Expected v<batch-version> or <plugin-id>/v<plugin-version>")
    if not plugins:
        raise ValueError("No plugin manifests found")
    for name, version in plugins.items():
        if not re.fullmatch(VERSION, version):
            raise ValueError(f"Invalid version for {name}: {version}")
    plugin = match.group('plugin') or ''
    version = match.group('version')
    if plugin:
        if plugin not in plugins:
            raise ValueError(f"Unknown plugin: {plugin}")
        if plugins[plugin] != version:
            raise ValueError(f"Tag version {version} does not match {plugin}: {plugins[plugin]}")
    return plugin, version

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tag')
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    versions = {}
    for path in sorted((ROOT / 'plugins').glob('*/plugin.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        plugin_id = manifest['id']
        if plugin_id in versions or plugin_id != path.parent.name:
            raise SystemExit(f'Duplicate or inconsistent plugin ID: {plugin_id}')
        versions[plugin_id] = manifest.get('version', '')
    try:
        plugin, version = validate(args.tag, versions)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if args.github_output:
        with args.github_output.open('a', encoding='utf-8') as output:
            output.write(f'plugin={plugin}\n')
            output.write(f'assets=dist/{plugin}-{version}.jtbplugin\n' if plugin else 'assets=dist/*.jtbplugin\n')
            output.write(f'prerelease={str("-" in version).lower()}\n')
    print(f'Release {args.tag}: {plugin or "all plugins with independent versions"}')

if __name__ == '__main__':
    main()
