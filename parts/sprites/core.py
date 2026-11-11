"""RPG Maker MV character-grid inspection and a local animated preview."""
import hashlib
import io
import os
import stat
from pathlib import Path
import uuid

PRIVATE = {'.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config', '.hermes'}
DIRECTIONS = ('down', 'left', 'right', 'up')


def load(value):
    from PIL import Image
    p = Path(value).expanduser()
    if p.is_symlink() or any(x.casefold() in PRIVATE for x in p.parts):
        raise ValueError('Private paths and symlink inputs are unsupported')
    p = p.resolve(strict=True)
    if any(x.casefold() in PRIVATE for x in p.parts) or not p.is_file() or p.suffix.lower() != '.png':
        raise ValueError('Select a PNG outside private configuration')
    fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode): raise ValueError('Choose a regular PNG file')
        data = f.read(32 * 1024**2 + 1)
        after = os.fstat(f.fileno())
    if len(data) > 32 * 1024**2:
        raise ValueError('PNG exceeds 32 MiB')
    current = p.lstat()
    identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns)
    if identity(before) != identity(after) or identity(after) != identity(current) or not stat.S_ISREG(current.st_mode):
        raise ValueError('PNG changed while reading')
    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as exc:
        raise ValueError('Image dimensions exceed safe limits') from exc
    if image.format != 'PNG' or image.width * image.height > 16_000_000:
        raise ValueError('Unsupported image format or dimensions')
    image.load()
    return p, image.convert('RGBA'), hashlib.sha256(data).hexdigest()


def grid(path, image):
    prefix = path.name[:2]
    big = '$' in prefix and all(x in '!$' for x in prefix[:prefix.index('$')])
    cols, rows = (3, 4) if big else (12, 8)
    if image.width % cols or image.height % rows:
        raise ValueError(f'Image dimensions must divide evenly into a {cols} by {rows} grid for this filename')
    return big, image.width // cols, image.height // rows


class Sprites:
    def __init__(self, root):
        self.root = Path(root)

    def inspect_mv(self, source_path):
        path, image, sha = load(source_path)
        big, w, h = grid(path, image)
        cells = []
        channel = image.getchannel('A')
        for slot in range(1 if big else 8):
            base_x, base_y = (0, 0) if big else ((slot % 4) * 3, (slot // 4) * 4)
            for row, direction in enumerate(DIRECTIONS):
                for frame in range(3):
                    x, y = (base_x + frame) * w, (base_y + row) * h
                    alpha = channel.crop((x, y, x+w, y+h))
                    cells.append({'slot': slot, 'direction': direction, 'frame': frame,
                                  'empty': alpha.getbbox() is None, 'bounds': alpha.getbbox()})
        return {'fingerprint': sha, 'single_character': big, 'frame_width': w, 'frame_height': h,
                'object_prefix': path.name.startswith('!') or path.name.startswith('$!'), 'cells': cells,
                'notice': 'Empty cells may be intentional. Grid and alpha checks cannot judge artwork, animation quality, or in-game appearance.'}

    def preview_mv(self, source_path, fingerprint, slot, direction, frame_ms=150):
        from PIL import Image
        path, image, sha = load(source_path)
        if sha != fingerprint:
            raise ValueError('Source changed; inspect again')
        big, w, h = grid(path, image)
        if type(slot) is not int or not 0 <= slot < (1 if big else 8) or direction not in DIRECTIONS:
            raise ValueError('Invalid slot or direction')
        if type(frame_ms) is not int or not 50 <= frame_ms <= 2000:
            raise ValueError('frame_ms must be between 50 and 2000')
        base_x, base_y = (0, 0) if big else ((slot % 4) * 3, (slot // 4) * 4)
        y = (base_y + DIRECTIONS.index(direction)) * h
        frames = [image.crop(((base_x + n)*w, y, (base_x+n+1)*w, y+h)) for n in (1, 0, 1, 2)]
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        out = self.root / (uuid.uuid4().hex + '.gif')
        try:
            frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:], duration=frame_ms, loop=0, disposal=2)
            with Image.open(out) as preview:
                if preview.format != 'GIF': raise ValueError('Preview was not saved as GIF')
                encoded_frames = preview.n_frames
        except BaseException:
            out.unlink(missing_ok=True)
            raise
        return {'output_path': str(out), 'frames': encoded_frames, 'sequence_frames': len(frames),
                'encoded_frames': encoded_frames, 'source_fingerprint': sha,
                'notice': 'The GIF encoder may merge identical frames. Previews approximate transparency and timing; visually inspect and test in the actual game.'}


MAX_SHEET_BYTES = 8 * 1024**2


def check_bytes(name, data):
    """Report-only grid check for one PNG held in memory (used by ModLab before a mod is applied).

    Never raises: a problem is returned as text so the caller can report it without blocking anything.
    """
    out = {'file': name}
    try:
        from PIL import Image
        if len(data) > MAX_SHEET_BYTES:
            return {**out, 'grid_ok': None, 'note': 'Skipped: file larger than 8 MiB.'}
        image = Image.open(io.BytesIO(data))
        if image.format != 'PNG' or image.width * image.height > 16_000_000:
            return {**out, 'grid_ok': None, 'note': 'Skipped: not a PNG or dimensions beyond the safe limit.'}
        image.load()
        base = name.replace('\\', '/').rsplit('/', 1)[-1]
        big, w, h = grid(Path(base), image)
        return {**out, 'grid_ok': True, 'single_character': big, 'frame_width': w, 'frame_height': h,
                'note': f'Grid divides evenly: {w} by {h} pixel frames.'}
    except ValueError as exc:
        return {**out, 'grid_ok': False, 'note': str(exc)}
    except Exception as exc:  # report only, never block the mod
        return {**out, 'grid_ok': None, 'note': 'Could not check: ' + type(exc).__name__}
