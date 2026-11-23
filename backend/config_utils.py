"""Path mapping utility — extracted from config.py for size management.

config.py re-exports map_path for backwards compatibility.
"""

import re

# "D:\..." or UNC "\\server\share\..." — what Sonarr/Radarr on Windows report.
_WINDOWS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def is_under_folder(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it.

    A plain prefix test lets "/media/movies" match "/media/movies-4k/...": with
    several pairs that maps a library onto another library's root.
    """
    if not folder or not path.startswith(folder):
        return False
    rest = path[len(folder) :]
    return not rest or folder.endswith(("/", "\\")) or rest.startswith(("/", "\\"))


def _under_folder(path: str, folder: str, ignore_case: bool) -> bool:
    """Whole-folder containment, optionally case-insensitive.

    Lowering is applied only where it keeps the string length, so a caller that
    slices ``path`` at ``len(prefix)`` stays aligned with the original.
    """
    if (
        ignore_case
        and len(path.lower()) == len(path)
        and len(folder.lower()) == len(folder)
    ):
        return is_under_folder(path.lower(), folder.lower())
    return is_under_folder(path, folder)


def map_path(path: str) -> str:
    """Map a remote file path to a local path using configured path mappings.

    Path mapping is configured via the SUBLARR_PATH_MAPPING setting:
    Format: "remote_prefix=local_prefix" (multiple pairs separated by semicolons)
    Example: "/data/media=/mnt/media;/anime=/share/anime"

    A pair matches whole folders only ("/data/movies" never rewrites
    "/data/movies-4k/..."), and the pair with the longest remote prefix wins,
    so a specific pair beats a general one in any order.

    A Windows remote path ("D:\\TV\\...", "\\\\nas\\tv\\...") matches its pair
    with either separator, and elsewhere its backslashes become "/". The
    result's separator style follows the local prefix, not the host: a
    Windows-shaped local ("D:\\tv", "\\\\nas\\share") joins in backslashes
    wherever Sublarr runs; a POSIX local stays "/" even on a Windows host.
    Callers compare through normcase/normpath and the OS accepts either spelling.

    SECURITY NOTE: This function performs prefix replacement only.
    Callers that serve or delete files MUST validate the mapped result with
    ``security_utils.is_safe_path(mapped, media_path)`` before using it,
    to guard against path traversal after mapping.
    """
    from config import get_settings  # local import — prevents circular dep

    s = get_settings()
    mapping = s.path_mapping
    if not mapping:
        return path

    windows = bool(_WINDOWS_PATH_RE.match(path))
    probe = path.replace("\\", "/") if windows else path
    best = None
    for pair in mapping.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        remote_prefix, local_prefix = pair.split("=", 1)
        remote_prefix = remote_prefix.strip()
        local_prefix = local_prefix.strip()
        if not remote_prefix or not local_prefix:
            continue
        # Windows paths ignore case: Sonarr may report d:\tv for D:\TV.
        if windows:
            remote_prefix = remote_prefix.replace("\\", "/")
            if not _under_folder(probe, remote_prefix, True):
                continue
        elif not _under_folder(probe, remote_prefix, False):
            continue
        if best is None or len(remote_prefix) > len(best[0]):
            best = (remote_prefix, local_prefix)

    if best is None:
        return path

    # Idempotent: a path already sitting under the winning local prefix is a
    # result of this mapping, not a remote path still waiting for it. Nested
    # pairs ("/media=/media/library") otherwise rewrite an already-resolved
    # path into "/media/library/library/...", so every second hop through a
    # path the scanner had mapped once — the editor's GET /tools/content, the
    # HI/modifier tools — reported "File not found" for a file that exists.
    if _under_folder(probe, best[1].replace("\\", "/"), windows):
        return path
    remote_prefix, local_prefix = best
    # Join at the folder boundary whichever side spells the trailing separator.
    mapped = local_prefix.rstrip("/\\") + probe[len(remote_prefix.rstrip("/\\")) :]
    if _WINDOWS_PATH_RE.match(local_prefix):
        mapped = mapped.replace("/", "\\")
    return mapped
