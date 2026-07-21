from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen

from .config import FIXED_RELEASE_TAG, XraySettings
from .errors import AssetError

RELEASE_BASE_URL = "https://github.com/qqq694637644/Xray-core/releases/download/{tag}/{asset}"
KNOWN_ARCHIVE_SHA256 = {
    "xray-mt-linux-amd64.tar.gz": "099d8902c8ef35904199809f69bf1d52125ebb0af8d96be5c143bec8ed8ba78b",
}


@dataclass(frozen=True)
class PlatformAsset:
    platform_id: str
    archive_name: str
    executable_name: str


@dataclass(frozen=True)
class InstalledAsset:
    platform_asset: PlatformAsset
    install_dir: Path
    executable: Path


def detect_platform() -> PlatformAsset:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    else:
        raise AssetError(f"unsupported CPU architecture: {platform.machine()}")

    if system == "linux":
        return PlatformAsset("linux-amd64", "xray-mt-linux-amd64.tar.gz", "xray")
    if system == "windows":
        return PlatformAsset("windows-amd64", "xray-mt-windows-amd64.zip", "xray.exe")
    raise AssetError(f"unsupported operating system: {platform.system()}")


def asset_url(asset_name: str, tag: str = FIXED_RELEASE_TAG) -> str:
    return RELEASE_BASE_URL.format(tag=tag, asset=asset_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256_text(text: str, expected_asset_name: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.replace("*", " ").split()
        if len(parts) == 1 and len(parts[0]) == 64:
            return parts[0].lower()
        if len(parts) >= 2 and parts[1].endswith(expected_asset_name):
            return parts[0].lower()
    raise AssetError(f"sha256 file did not contain digest for {expected_asset_name}")


def _download(url: str, target: Path, timeout_seconds: int = 60) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(url, timeout=timeout_seconds) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except URLError as exc:
        raise AssetError(f"download failed: {url}: {exc}") from exc


def _safe_extract_zip(archive: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            destination = (target_dir / member.filename).resolve()
            if not str(destination).startswith(str(target_dir.resolve())):
                raise AssetError(f"unsafe zip entry: {member.filename}")
        zf.extractall(target_dir)


def _safe_extract_tar(archive: Path, target_dir: Path) -> None:
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            destination = (target_dir / member.name).resolve()
            if not str(destination).startswith(str(target_dir.resolve())):
                raise AssetError(f"unsafe tar entry: {member.name}")
        tf.extractall(target_dir)


def _verify_inner_sha256s(install_dir: Path) -> None:
    sums = install_dir / "SHA256SUMS.txt"
    if not sums.exists():
        return
    for raw_line in sums.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.replace("*", " ").split()
        if len(parts) < 2 or len(parts[0]) != 64:
            continue
        expected, relative_name = parts[0].lower(), parts[1]
        candidate = (install_dir / relative_name).resolve()
        if not str(candidate).startswith(str(install_dir.resolve())):
            raise AssetError(f"unsafe SHA256SUMS entry: {relative_name}")
        if not candidate.exists() or candidate.is_dir():
            raise AssetError(f"SHA256SUMS entry missing: {relative_name}")
        actual = sha256_file(candidate)
        if actual != expected:
            raise AssetError(f"SHA256SUMS mismatch for {relative_name}: expected {expected}, got {actual}")


def ensure_installed(settings: XraySettings, cache_dir: Optional[Path] = None) -> InstalledAsset:
    if settings.release_tag != FIXED_RELEASE_TAG:
        raise AssetError(f"only {FIXED_RELEASE_TAG} is supported in the first version")

    platform_asset = detect_platform()
    install_dir = settings.install_root / settings.release_tag / platform_asset.platform_id
    executable = install_dir / platform_asset.executable_name
    if executable.exists():
        return InstalledAsset(platform_asset=platform_asset, install_dir=install_dir, executable=executable)

    if not settings.auto_download:
        raise AssetError(f"xray executable missing and autoDownload is false: {executable}")

    work_dir = cache_dir or (settings.install_root / "_downloads")
    archive_path = work_dir / platform_asset.archive_name
    sha_path = work_dir / f"{platform_asset.archive_name}.sha256"

    if not archive_path.exists():
        _download(asset_url(platform_asset.archive_name, settings.release_tag), archive_path)
    if not sha_path.exists():
        try:
            _download(asset_url(f"{platform_asset.archive_name}.sha256", settings.release_tag), sha_path)
        except AssetError:
            if platform_asset.archive_name not in KNOWN_ARCHIVE_SHA256:
                raise

    if sha_path.exists():
        expected_hash = parse_sha256_text(sha_path.read_text(encoding="utf-8", errors="replace"), platform_asset.archive_name)
    else:
        expected_hash = KNOWN_ARCHIVE_SHA256[platform_asset.archive_name]

    actual_hash = sha256_file(archive_path)
    if actual_hash != expected_hash:
        try:
            archive_path.unlink()
        except OSError:
            pass
        raise AssetError(
            f"archive sha256 mismatch for {archive_path}: expected {expected_hash}, got {actual_hash}"
        )

    tmp_parent = install_dir.parent
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=str(tmp_parent)) as tmp:
        tmp_dir = Path(tmp)
        if platform_asset.archive_name.endswith(".zip"):
            _safe_extract_zip(archive_path, tmp_dir)
        else:
            _safe_extract_tar(archive_path, tmp_dir)
        if install_dir.exists():
            shutil.rmtree(install_dir)
        shutil.move(str(tmp_dir), str(install_dir))

    _verify_inner_sha256s(install_dir)
    if not executable.exists():
        raise AssetError(f"xray executable missing after extraction: {executable}")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    return InstalledAsset(platform_asset=platform_asset, install_dir=install_dir, executable=executable)
