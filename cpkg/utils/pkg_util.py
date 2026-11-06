"""
Most important util, unpack .pkg, pack .pkg, generate .pkg and many more.

.pkg is a format which uses Gzip compression, it is like arch-linux or python .tar.gz-based files.

.pkg format:

INFO.md :: Short info about the package + Version + What does it provide
PKG_NAME
|-> src
|-> Makefile OR .abuild
LICENSE :: License file
CHECKSUM
DEPENDENCIES :: List of dependencies


.pkg naming format:
<OS>_<ARCH>_<PKG_NAME>_<VERSION>.pkg
Example:

- win_x86_64_mypkg_v1.0.0.pkg
- universal_x86_64_mypkg2_1.0.0.pkg

"""

from pathlib import Path
import hashlib
import re
import tarfile
from .color import Color

c = Color()


_PKG_FILE_RE = re.compile(
    r"^(?P<os>win|universal|linux|macos)_(?P<arch>x86_64|x86|arm|aarch64)_(?P<name>.+)_(?P<version>[^_]+)\.pkg$",
    re.IGNORECASE,
)


def parse_pkg_filename(filename: str):
    """
    Split `<OS>_<ARCH>_<PKG_NAME>_<VERSION>.pkg` into (os, arch, name, version).
    Returns None if the name doesn't follow the format. (Arch can contain `_`, e.g. x86_64,
    so a plain split("_") is not enough.)
    """
    m = _PKG_FILE_RE.match(Path(filename).name)
    if not m:
        return None
    return (
        m.group("os").lower(),
        m.group("arch").lower(),
        m.group("name"),
        m.group("version"),
    )


class OSNameInvalidError(Exception): ...


class ArchInputInvalidError(Exception): ...


class NoFileFoundError(Exception): ...


class PackageGenerationError(Exception): ...


class ChecksumVerificationError(Exception): ...


class PackageExtractionError(Exception): ...


class PackageFilenameError(Exception): ...


class Generate:
    def __init__(self, pkg_file_dir: str | Path):
        self.pkgf = Path(pkg_file_dir)

    def _calculate_src_checksum(self, src_path: Path) -> str:
        sha256 = hashlib.sha256()
        if src_path.is_file():
            with open(src_path, "rb") as f:
                while chunk := f.read(8192):
                    sha256.update(chunk)
        elif src_path.is_dir():
            for path in sorted(src_path.rglob("*")):
                if path.is_file():
                    sha256.update(path.relative_to(src_path.parent).as_posix().encode())
                    with open(path, "rb") as f:
                        while chunk := f.read(8192):
                            sha256.update(chunk)
        return sha256.hexdigest()

    def gen(self, name: str, vs: str, os_name: str, arch: str, src_dir: str):
        if os_name.lower() not in ["win", "universal", "linux", "macos"]:
            raise OSNameInvalidError(
                f"{c.RED}OS name: {os_name} is not supported (only `win`, `universal`, `macos` and `linux` supported)!{c.RESET}"
            )
        if arch.upper() not in ["X86", "X86_64", "ARM", "AARCH64"]:
            raise ArchInputInvalidError(
                f"{c.RED}Arch: {arch} is not supported (only `x86`, `x86_64`, `ARM`, `AARCH64` supported)!{c.RESET}"
            )

        if not self.pkgf.exists():
            raise NoFileFoundError(
                f"{c.RED}The root package directory '{self.pkgf}' does not exist.{c.RESET}"
            )

        required_root_files = ["INFO.md", "CHECKSUM"]
        required_inner_files = [f"{name}/LICENSE", f"{name}/{src_dir}"]
        optional_root_file = "DEPENDENCIES"

        missing_files = []
        files_to_pack = []

        for file_name in required_root_files:
            file_path = self.pkgf / file_name
            if file_name != "CHECKSUM" and not file_path.exists():
                missing_files.append(file_name)

        for file_name in required_inner_files:
            file_path = self.pkgf / file_name
            if file_path.exists():
                files_to_pack.append((file_path, file_name))
            else:
                missing_files.append(file_name)

        if missing_files:
            missing_str = ", ".join(missing_files)
            raise FileNotFoundError(
                f"{c.RED}Generation stopped. Missing required files/folders: {missing_str}{c.RESET}"
            )

        src_path = self.pkgf / f"{name}/{src_dir}"
        calculated_checksum = self._calculate_src_checksum(src_path)
        checksum_path = self.pkgf / "CHECKSUM"

        if checksum_path.exists() and checksum_path.stat().st_size > 0:
            existing_checksum = checksum_path.read_text().strip()
            if existing_checksum != calculated_checksum:
                raise ChecksumVerificationError(
                    f"{c.RED}Checksum mismatch! Expected: {existing_checksum}, Calculated from data: {calculated_checksum}{c.RESET}"
                )
            print(f"{c.GREEN}Checksum verified successfully.{c.RESET}")
        else:
            checksum_path.write_text(calculated_checksum)
            print(f"{c.YELLOW}Generated new checksum: {calculated_checksum}{c.RESET}")

        for file_name in required_root_files:
            files_to_pack.append((self.pkgf / file_name, file_name))

        opt_path = self.pkgf / optional_root_file
        if opt_path.exists():
            files_to_pack.append((opt_path, optional_root_file))

        filename = f"{os_name.lower()}_{arch.lower()}_{name}_{vs.lower()}.pkg"
        output_pkg_path = self.pkgf / filename

        try:
            print(f"{c.CYAN}Creating package: {filename}...{c.RESET}")
            with tarfile.open(output_pkg_path, "w:gz") as tar:
                for physical_path, arc_name in files_to_pack:
                    tar.add(physical_path, arcname=arc_name)

            print(f"{c.GREEN}{c.BOLD}Package successfully generated!{c.RESET}")
            return output_pkg_path

        except tarfile.CompressionError as e:
            raise PackageGenerationError(
                f"{c.RED}Gzip compression engine failed: {e}{c.RESET}"
            )
        except Exception as e:
            raise PackageGenerationError(
                f"{c.RED}An unexpected error occurred during build: {e}{c.RESET}"
            )


class Unpack:
    def __init__(self, pkg_file_path: str | Path):
        self.pkg_path = Path(pkg_file_path)

    def _calculate_src_checksum(self, src_path: Path) -> str:
        sha256 = hashlib.sha256()
        if src_path.is_file():
            with open(src_path, "rb") as f:
                while chunk := f.read(8192):
                    sha256.update(chunk)
        elif src_path.is_dir():
            for path in sorted(src_path.rglob("*")):
                if path.is_file():
                    sha256.update(path.relative_to(src_path.parent).as_posix().encode())
                    with open(path, "rb") as f:
                        while chunk := f.read(8192):
                            sha256.update(chunk)
        return sha256.hexdigest()

    def unpack(self, dest_dir: str | Path, src_dir: str = "src"):
        if not self.pkg_path.exists():
            raise FileNotFoundError(
                f"{c.RED}Package file '{self.pkg_path}' not found.{c.RESET}"
            )

        parsed = parse_pkg_filename(self.pkg_path.name)
        if parsed is None:
            raise PackageFilenameError(
                f"{c.RED}Invalid package naming convention for '{self.pkg_path.name}'.{c.RESET}"
            )

        pkg_name = parsed[2]
        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)

        try:
            print(f"{c.CYAN}Extracting package archive...{c.RESET}")
            with tarfile.open(self.pkg_path, "r:gz") as tar:
                tar.extractall(path=dest_path, filter="data")
        except Exception as e:
            raise PackageExtractionError(
                f"{c.RED}Failed to extract package archive: {e}{c.RESET}"
            )

        checksum_file = dest_path / "CHECKSUM"
        if not checksum_file.exists():
            raise ChecksumVerificationError(
                f"{c.RED}Verification failed. Embedded CHECKSUM file is missing inside archive.{c.RESET}"
            )

        embedded_checksum = checksum_file.read_text().strip()
        extracted_src_path = dest_path / pkg_name / src_dir

        if not extracted_src_path.exists():
            raise NoFileFoundError(
                f"{c.RED}Extracted payload source directory '{extracted_src_path}' not found.{c.RESET}"
            )

        calculated_checksum = self._calculate_src_checksum(extracted_src_path)
        if embedded_checksum != calculated_checksum:
            raise ChecksumVerificationError(
                f"{c.RED}Extracted package checksum mismatch! Expected: {embedded_checksum}, Extracted Data Hash: {calculated_checksum}{c.RESET}"
            )

        print(f"{c.GREEN}{c.BOLD}Package unpacked and verified successfully.{c.RESET}")
        return dest_path
