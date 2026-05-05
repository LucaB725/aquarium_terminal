"""
theme_loader.py — ASCII Aquarium theme pack support

Responsibilities:
  • Discover theme folders under  <script_dir>/themes/
  • Load the four per-theme files (theme.cfg, fish.txt, scenery.txt, colors.cfg)
  • Merge them on top of a base Config, returning the combined result
  • Keep a cycling index so 't' in the main loop steps through themes

Theme folder layout
───────────────────
themes/
  <name>/
    theme.cfg      — fps, fish_start, fish_max, speed, bubble, day/night settings
    fish.txt       — replaces the global fish.txt entirely for this theme
    scenery.txt    — list of (kind  x_frac) lines driving Scenery.LAYOUT
    colors.cfg     — color_* keys, same names as aquarium.cfg
    description.txt — one-line display name  +  optional second line blurb

All files are optional; missing files fall back to base defaults gracefully.
"""

from __future__ import annotations

from pathlib import Path
from typing  import Optional

# ── Locate the themes folder relative to this file ────────────────────────────

_HERE        = Path(__file__).parent
THEMES_DIR   = _HERE / "themes"

# Keys that are allowed to come from a theme file.
# Kept in sync with Config.DEFAULTS in aquarium.py.
_CFG_KEYS = {
    "fps", "fish_start", "fish_max",
    "fish_speed_min", "fish_speed_max",
    "bubble_fish_chance", "bubble_floor_chance", "bubble_max",
    "day_night_cycle", "day_night_period",
}

_COLOR_KEYS = {
    "color_border", "color_seaweed", "color_bubble",
    "color_rock", "color_coral", "color_sand",
    "color_chest", "color_status_fg", "color_status_bg",
}

_ALL_KEYS = _CFG_KEYS | _COLOR_KEYS


# ══════════════════════════════════════════════════════════════════════════════
#  ThemePack  — a loaded, validated theme ready to be applied
# ══════════════════════════════════════════════════════════════════════════════

class ThemePack:
    """
    Holds everything read from one theme folder.

    Attributes
    ----------
    name         : folder name, e.g. "coral_reef"
    display_name : first line of description.txt, or the folder name
    blurb        : second line of description.txt, or ""
    overrides    : dict of config/color key→value strings to merge into Config
    fish_path    : Path to this theme's fish.txt, or None if absent
    layout       : list of (kind, x_frac) tuples from scenery.txt, or None
    """

    def __init__(self, folder: Path):
        self.name         = folder.name
        self.display_name = folder.name.replace("_", " ").title()
        self.blurb        = ""
        self.overrides: dict[str, str] = {}
        self.fish_path: Optional[Path] = None
        self.layout: Optional[list[tuple[str, float]]] = None

        self._load(folder)

    def _load(self, folder: Path):
        self._load_description(folder / "description.txt")
        self._load_cfg(folder / "theme.cfg")
        self._load_cfg(folder / "colors.cfg")      # same key=val format
        self._load_fish(folder / "fish.txt")
        self._load_scenery(folder / "scenery.txt")

    # ── individual file parsers ────────────────────────────────────────────────

    def _load_description(self, path: Path):
        if not path.exists():
            return
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
        if lines:
            self.display_name = lines[0]
        if len(lines) > 1:
            self.blurb = lines[1]

    def _load_cfg(self, path: Path):
        """Parse any key = value file; keep only recognised keys."""
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lower()
                val = val.rstrip("\n")
                if key in _ALL_KEYS:
                    self.overrides[key] = val

    def _load_fish(self, path: Path):
        if path.exists():
            self.fish_path = path

    def _load_scenery(self, path: Path):
        """
        Parse scenery.txt into a list of (kind, x_frac) tuples.

        Format (one entry per line, comment lines start with #):
            seaweed  0.08
            rock     0.25
            coral    0.60
            chest    0.40
            anemone  0.75   # unknown kinds are silently skipped
        """
        if not path.exists():
            return
        layout = []
        known  = {"seaweed", "rock", "coral", "chest"}
        with path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.partition("#")[0].strip()   # strip inline comments
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kind = parts[0].lower()
                if kind not in known:
                    continue                            # future-proof: skip unknowns
                try:
                    xf = float(parts[1])
                except ValueError:
                    continue
                xf = max(0.01, min(0.99, xf))          # clamp to interior
                layout.append((kind, xf))
        if layout:
            self.layout = layout

    def __repr__(self) -> str:
        return (f"ThemePack({self.name!r}, "
                f"overrides={len(self.overrides)}, "
                f"fish={'yes' if self.fish_path else 'no'}, "
                f"layout={'yes' if self.layout else 'no'})")


# ══════════════════════════════════════════════════════════════════════════════
#  ThemeManager  — discovery + cycling
# ══════════════════════════════════════════════════════════════════════════════

class ThemeManager:
    """
    Discovers all theme folders, loads them, and lets the caller cycle through
    them with next() / prev() or jump to one by name.

    Usage
    -----
        mgr = ThemeManager()
        pack = mgr.current()      # None if no themes found
        pack = mgr.next()         # advance and return the new pack
        pack = mgr.select("deep_sea")
        names = mgr.names()       # sorted list of available theme names
    """

    def __init__(self, themes_dir: Path = THEMES_DIR):
        self._packs: list[ThemePack] = []
        self._index: int = -1        # -1 means "no theme / use base config"
        self._discover(themes_dir)

    def _discover(self, themes_dir: Path):
        if not themes_dir.is_dir():
            return
        found = []
        for entry in sorted(themes_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                try:
                    pack = ThemePack(entry)
                    found.append(pack)
                except Exception:
                    pass   # malformed theme folder — skip silently
        self._packs = found

    # ── public API ────────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        """Sorted list of available theme names."""
        return [p.name for p in self._packs]

    def current(self) -> Optional[ThemePack]:
        """Active theme pack, or None when running with base config."""
        if self._index < 0 or not self._packs:
            return None
        return self._packs[self._index]

    def current_label(self) -> str:
        """Short string for the status bar, e.g. 'coral reef' or 'default'."""
        pack = self.current()
        return pack.display_name if pack else "default"

    def next(self) -> Optional[ThemePack]:
        """
        Advance to the next theme and return it.
        Cycles: default → theme[0] → theme[1] → … → default → …
        """
        if not self._packs:
            return None
        self._index = (self._index + 1) % len(self._packs)
        return self.current()

    def prev(self) -> Optional[ThemePack]:
        """Step backward through themes."""
        if not self._packs:
            return None
        # -1 wraps to the last theme (not to default), so we need explicit handling
        if self._index <= 0:
            self._index = len(self._packs) - 1
        else:
            self._index -= 1
        return self.current()

    def select(self, name: str) -> Optional[ThemePack]:
        """Jump directly to a theme by folder name. Returns None if not found."""
        for i, pack in enumerate(self._packs):
            if pack.name == name:
                self._index = i
                return pack
        return None

    def reset(self):
        """Return to base config (no active theme)."""
        self._index = -1

    def __len__(self) -> int:
        return len(self._packs)

    def __bool__(self) -> bool:
        return bool(self._packs)


# ══════════════════════════════════════════════════════════════════════════════
#  apply_theme  — merge a ThemePack onto an existing Config
# ══════════════════════════════════════════════════════════════════════════════

def apply_theme(config, pack: Optional[ThemePack]) -> None:
    """
    Merge pack.overrides into config._data in-place.
    Uses the same coercion logic as Config._load so types stay correct.
    Pass pack=None to be a no-op (base config unchanged).

    Parameters
    ----------
    config : aquarium.Config instance  (duck-typed — just needs ._data and .DEFAULTS)
    pack   : ThemePack or None
    """
    if pack is None:
        return

    for key, val in pack.overrides.items():
        if key not in config._data:
            continue
        orig = config.DEFAULTS.get(key)
        if orig is None:
            config._data[key] = val
            continue
        try:
            if isinstance(orig, bool):
                config._data[key] = val.lower() in ("true", "1", "yes")
            elif isinstance(orig, int):
                config._data[key] = int(val)
            elif isinstance(orig, float):
                config._data[key] = float(val)
            else:
                config._data[key] = val
        except (ValueError, AttributeError):
            pass   # keep whatever was there before
