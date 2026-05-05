#!/usr/bin/env python3
"""
aquarium.py — ASCII Aquarium, Phase 4
• Fish sprites loaded from fish.txt  (add your own without touching this file)
• All tunable parameters read from aquarium.cfg
• Day / night colour cycle shifts the water from bright day-blue to deep navy
• Full colour theming for every scene element
• Theme packs: drop a folder into themes/ to create a new preset

Controls:
  q / ESC   Quit
  p         Pause / unpause
  +         Add a fish
  -         Remove a fish
  r         Reload fish.txt and aquarium.cfg on the fly
  t         Cycle to the next theme pack
  T         Cycle to the previous theme pack

CLI:
  python aquarium.py --theme coral_reef
  python aquarium.py --list-themes
"""

from __future__ import annotations

import argparse
import curses
import time
import random
import math
import os
import sys
from pathlib import Path

from theme_loader import ThemeManager, apply_theme

# ── Locate data files (same directory as this script) ─────────────────────────

_HERE      = Path(__file__).parent
FISH_FILE  = _HERE / "fish.txt"
CFG_FILE   = _HERE / "aquarium.cfg"

# ── Color name → curses constant ──────────────────────────────────────────────

_COLOR_NAMES = {
    "black":   curses.COLOR_BLACK,
    "red":     curses.COLOR_RED,
    "green":   curses.COLOR_GREEN,
    "yellow":  curses.COLOR_YELLOW,
    "blue":    curses.COLOR_BLUE,
    "magenta": curses.COLOR_MAGENTA,
    "cyan":    curses.COLOR_CYAN,
    "white":   curses.COLOR_WHITE,
}

def _named_color(name: str, default: int = curses.COLOR_WHITE) -> int:
    return _COLOR_NAMES.get(name.strip().lower(), default)

# ── Color pair IDs ─────────────────────────────────────────────────────────────

CP_WATER   = 1
CP_FISH    = [2, 3, 4, 5, 6, 7]
CP_BORDER  = 8
CP_STATUS  = 9
CP_BUBBLE  = 10
CP_SEAWEED = 11
CP_ROCK    = 12
CP_CORAL   = 13
CP_SAND    = 14
CP_CHEST   = 15

_FISH_PALETTE = [
    curses.COLOR_YELLOW,
    curses.COLOR_WHITE,
    curses.COLOR_GREEN,
    curses.COLOR_CYAN,
    curses.COLOR_MAGENTA,
    curses.COLOR_RED,
]

# ── Seaweed animation frames ───────────────────────────────────────────────────

SEAWEED_FRAMES = [
    ["/", "¦", "/", "¦"],
    ["|", "|", "|", "|"],
    ["\\","¦","\\","¦"],
    ["|", "|", "|", "|"],
]
SEAWEED_CYCLE = len(SEAWEED_FRAMES)

BUBBLE_CHARS = [".", "o", "O", "0", "*"]


# ══════════════════════════════════════════════════════════════════════════════
#  Config loader
# ══════════════════════════════════════════════════════════════════════════════

class Config:
    DEFAULTS = {
        "fps":                 24,
        "fish_start":          5,
        "fish_max":            30,
        "fish_speed_min":      0.08,
        "fish_speed_max":      0.22,
        "bubble_fish_chance":  0.015,
        "bubble_floor_chance": 0.008,
        "bubble_max":          60,
        "day_night_cycle":     True,
        "day_night_period":    120,
        "color_border":        "white",
        "color_seaweed":       "green",
        "color_bubble":        "cyan",
        "color_rock":          "white",
        "color_coral":         "magenta",
        "color_sand":          "yellow",
        "color_chest":         "yellow",
        "color_status_fg":     "black",
        "color_status_bg":     "white",
    }

    def __init__(self, path: Path):
        self._data = dict(self.DEFAULTS)
        self._load(path)

    def _load(self, path: Path):
        if not path.exists():
            return
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lower()
                val = val.strip()
                if key in self._data:
                    orig = self.DEFAULTS[key]
                    try:
                        if isinstance(orig, bool):
                            self._data[key] = val.lower() in ("true", "1", "yes")
                        elif isinstance(orig, int):
                            self._data[key] = int(val)
                        elif isinstance(orig, float):
                            self._data[key] = float(val)
                        else:
                            self._data[key] = val
                    except ValueError:
                        pass

    def __getattr__(self, name: str):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)


# ══════════════════════════════════════════════════════════════════════════════
#  Fish sprite loader
# ══════════════════════════════════════════════════════════════════════════════

class SpriteLibrary:
    BUILTIN = [
        {"rows_right": ["><>"],    "rows_left": ["<><"],    "color_idx": 0},
        {"rows_right": ["><((°>"], "rows_left": ["<°))><"], "color_idx": 3},
    ]

    def __init__(self, path: Path):
        self.sprites = []
        self._load(path)
        if not self.sprites:
            self.sprites = list(self.BUILTIN)

    def _load(self, path: Path):
        if not path.exists():
            return
        current = {}
        color_keys = list(_COLOR_NAMES.keys())
        with path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("[") and stripped.endswith("]"):
                    if current.get("right") is not None and current.get("left") is not None:
                        self._commit(current)
                    current = {}
                    continue
                if "=" not in stripped:
                    continue

                # Key is always the stripped left side
                eq  = stripped.index("=")
                key = stripped[:eq].strip().lower()

                # Value: take everything after the '=' in the STRIPPED line so
                # that indentation of the key is ignored, but any spaces that
                # are part of the sprite value (including leading spaces in the
                # value itself) are kept.
                raw_val = stripped[eq + 1:]
                # Strip exactly one optional leading space (the separator space
                # between '=' and the value), then keep the rest verbatim.
                val = raw_val[1:] if raw_val.startswith(" ") else raw_val

                if key == "right" or (key.startswith("right") and key[5:].isdigit()):
                    current[key] = val
                elif key == "left" or (key.startswith("left") and key[4:].isdigit()):
                    current[key] = val
                elif key == "color" and val.strip().lower() in color_keys:
                    current["color_idx"] = color_keys.index(val.strip().lower()) % len(CP_FISH)

        if current.get("right") is not None and current.get("left") is not None:
            self._commit(current)

    @staticmethod
    def _collect_rows(d: dict, prefix: str) -> list[str]:
        """
        Collect rows for 'right' or 'left' into a contiguous ordered list.

        Supports two conventions:

        A) New sequential (1-indexed suffixes from 1):
               right  = top row
               right1 = second row
               right2 = third row ...

        B) Legacy (2-indexed from 2, matching old right2/right3 style):
               right  = top row
               right2 = second row
               right3 = third row ...

        Both are reduced to a simple [row0, row1, row2, ...] list with no gaps.
        The bare key is always row 0. Numbered keys are sorted and appended in order.
        """
        bare = d.get(prefix)
        numbered: list[tuple[int, str]] = []

        for k, v in d.items():
            if k == prefix:
                continue
            suffix = k[len(prefix):]
            if suffix.isdigit():
                numbered.append((int(suffix), v))

        # Sort by numeric suffix; discard the suffix — we only care about order
        numbered.sort(key=lambda t: t[0])
        sorted_vals = [v for _, v in numbered]

        if bare is not None:
            return [bare] + sorted_vals
        return sorted_vals

    def _commit(self, d: dict):
        rows_right = self._collect_rows(d, "right")
        rows_left  = self._collect_rows(d, "left")

        if not rows_right or not rows_left:
            return   # malformed block — skip

        # Pad to equal height
        while len(rows_right) < len(rows_left):
            rows_right.append("")
        while len(rows_left) < len(rows_right):
            rows_left.append("")

        self.sprites.append({
            "rows_right": rows_right,
            "rows_left":  rows_left,
            "color_idx":  d.get("color_idx", random.randrange(len(CP_FISH))),
        })

    def random_sprite(self) -> dict:
        return random.choice(self.sprites)


# ══════════════════════════════════════════════════════════════════════════════
#  Day / Night colour manager
# ══════════════════════════════════════════════════════════════════════════════

class DayNight:
    DAY_FG   = (400, 800, 1000)
    DAY_BG   = (0,   200,  600)
    NIGHT_FG = (0,   100,  300)
    NIGHT_BG = (0,    50,  150)

    def __init__(self, cfg: Config):
        self.enabled   = cfg.day_night_cycle
        self.period    = max(10, cfg.day_night_period)
        self._start    = time.monotonic()
        self._extended = curses.can_change_color() and curses.COLORS >= 256
        self._slot_fg  = 240
        self._slot_bg  = 241

        if self._extended and self.enabled:
            curses.init_color(self._slot_fg, *self.DAY_FG)
            curses.init_color(self._slot_bg, *self.DAY_BG)
            curses.init_pair(CP_WATER, self._slot_fg, self._slot_bg)

    @staticmethod
    def _lerp(a: tuple, b: tuple, t: float) -> tuple:
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def phase(self) -> float:
        if not self.enabled:
            return 0.0
        elapsed = (time.monotonic() - self._start) % self.period
        return (1.0 - math.cos(2 * math.pi * elapsed / self.period)) / 2.0

    def update(self):
        if not (self.enabled and self._extended):
            return
        t = self.phase()
        curses.init_color(self._slot_fg, *self._lerp(self.DAY_FG, self.NIGHT_FG, t))
        curses.init_color(self._slot_bg, *self._lerp(self.DAY_BG, self.NIGHT_BG, t))

    def water_attr(self) -> int:
        return curses.color_pair(CP_WATER)


# ══════════════════════════════════════════════════════════════════════════════
#  Entities
# ══════════════════════════════════════════════════════════════════════════════

class Fish:
    def __init__(self, x: float, y: int, height: int, width: int,
                 lib: SpriteLibrary, cfg: Config):
        spr               = lib.random_sprite()
        self.rows_right   = spr["rows_right"]
        self.rows_left    = spr["rows_left"]
        self.color_idx    = spr["color_idx"]
        self.direction    = random.choice([-1, 1])
        self.sprite_rows  = self.rows_right if self.direction == 1 else self.rows_left
        self.num_rows     = len(self.rows_right)
        # Width = widest row across both directions, counting every character
        # including leading/trailing spaces (they are part of the sprite shape)
        all_rows = self.rows_right + self.rows_left
        self.length = max((len(r) for r in all_rows if r), default=1)
        self.x            = float(x)
        self.y            = y
        self.speed        = random.uniform(cfg.fish_speed_min, cfg.fish_speed_max)

    def update(self, height: int, width: int):
        self.x += self.speed * self.direction
        if self.direction == 1 and self.x + self.length >= width - 1:
            self.direction   = -1
            self.sprite_rows = self.rows_left
        elif self.direction == -1 and self.x <= 1:
            self.direction   = 1
            self.sprite_rows = self.rows_right
        if random.random() < 0.008:
            self.y += random.choice([-1, 1])
        # Keep entire fish body (all rows) inside the tank walls
        self.y = max(1, min(max(1, height - 2 - self.num_rows), self.y))

    @property
    def ix(self) -> int:
        return int(self.x)


class Bubble:
    LIFESPAN = 28

    def __init__(self, x: int, y: int):
        self.x      = x
        self.y      = float(y)
        self.age    = 0
        self.wobble = 0.0
        self.rise   = random.uniform(0.12, 0.22)

    def update(self) -> bool:
        self.age    += 1
        self.y      -= self.rise
        self.wobble += random.uniform(-0.4, 0.4)
        self.wobble  = max(-1.0, min(1.0, self.wobble))
        return self.age < self.LIFESPAN

    @property
    def char(self) -> str:
        idx = min(self.age * len(BUBBLE_CHARS) // self.LIFESPAN, len(BUBBLE_CHARS) - 1)
        return BUBBLE_CHARS[idx]

    @property
    def ix(self) -> int:
        return int(self.x + self.wobble)

    @property
    def iy(self) -> int:
        return int(self.y)


class Seaweed:
    def __init__(self, x: int, floor_y: int):
        self.x       = x
        self.floor_y = floor_y
        self.height  = random.randint(3, 7)
        self.phase   = random.randrange(SEAWEED_CYCLE)
        self.tick    = 0
        self.speed   = random.choice([6, 8, 10])

    def update(self):
        self.tick += 1
        if self.tick >= self.speed:
            self.tick  = 0
            self.phase = (self.phase + 1) % SEAWEED_CYCLE

    def segments(self):
        frame = SEAWEED_FRAMES[self.phase]
        for i in range(self.height):
            yield self.floor_y - i, frame[i % len(frame)]


# ══════════════════════════════════════════════════════════════════════════════
#  Scenery
# ══════════════════════════════════════════════════════════════════════════════

class Scenery:
    LAYOUT = [
        ("seaweed", 0.08), ("seaweed", 0.18), ("seaweed", 0.32),
        ("seaweed", 0.55), ("seaweed", 0.68), ("seaweed", 0.82),
        ("seaweed", 0.91),
        ("rock",  0.12), ("rock",  0.45), ("rock",  0.75),
        ("coral", 0.25), ("coral", 0.60), ("coral", 0.88),
        ("chest", 0.38),
    ]
    ROCK_SPRITE   = ["▄▄▄▄", "████", "▀▀▀▀"]
    CORAL_SPRITES = [
        ["\\*/", "|/|", " | "],
        [" /|\\", " |||", "  |  "],
    ]
    CHEST_SPRITE = ["╔══╗", "║()║", "╚══╝"]

    def __init__(self, height: int, width: int,
                 layout: list = None):
        self.seaweeds         = []
        self.static           = []
        self.height           = self.width = 0
        self._layout_override = layout   # None → use class-level LAYOUT
        self._build(height, width)

    def _build(self, height: int, width: int):
        self.height  = height
        self.width   = width
        inner_w      = max(1, width - 2)
        floor_y      = height - 2
        self.floor_y = floor_y
        self.static  = []
        self.seaweeds = []

        for x in range(1, width - 1):
            self.static.append((floor_y, x, "~", CP_SAND))

        # Use theme-supplied layout when available, else the class default
        active_layout = self._layout_override if self._layout_override is not None \
                        else self.LAYOUT

        for kind, xf in active_layout:
            x = max(1, min(width - 6, 1 + int(xf * (inner_w - 1))))

            if kind == "seaweed":
                self.seaweeds.append(Seaweed(x, floor_y - 1))
            elif kind == "rock":
                for ri, row in enumerate(self.ROCK_SPRITE):
                    y = floor_y - ri
                    if y >= 1:
                        for ci, ch in enumerate(row):
                            self.static.append((y, x + ci, ch, CP_ROCK))
            elif kind == "coral":
                sprite = random.choice(self.CORAL_SPRITES)
                for ri, row in enumerate(sprite):
                    y = floor_y - ri
                    if y >= 1:
                        for ci, ch in enumerate(row):
                            if ch != " ":
                                self.static.append((y, x + ci, ch, CP_CORAL))
            elif kind == "chest":
                for ri, row in enumerate(self.CHEST_SPRITE):
                    y = floor_y - ri
                    if y >= 1:
                        for ci, ch in enumerate(row):
                            self.static.append((y, x + ci, ch, CP_CHEST))

    def rebuild_if_resized(self, height: int, width: int):
        if height != self.height or width != self.width:
            self._build(height, width)

    def set_layout(self, layout: list = None):
        """Hot-swap the scenery layout (called on theme switch) then rebuild."""
        self._layout_override = layout
        self._build(self.height, self.width)

    def update(self):
        for sw in self.seaweeds:
            sw.update()

    def draw_static(self, buf: "DoubleBuffer"):
        for y, x, ch, pair in self.static:
            buf.put(y, x, ch, curses.color_pair(pair))

    def draw_seaweed(self, buf: "DoubleBuffer"):
        attr = curses.color_pair(CP_SEAWEED) | curses.A_BOLD
        for sw in self.seaweeds:
            for y, ch in sw.segments():
                if 1 <= y < buf.h - 1:
                    buf.put(y, sw.x, ch, attr)


# ══════════════════════════════════════════════════════════════════════════════
#  Double-buffer renderer
# ══════════════════════════════════════════════════════════════════════════════

class DoubleBuffer:
    # Sentinel stored in front buffer cells that have never been drawn.
    # Using a dedicated object means it can never equal any real (ch, attr) pair.
    _UNDRAWN = object()

    def __init__(self, height: int, width: int):
        self.h = height
        self.w = width
        self._blank = (" ", 0)
        self.front = [[self._UNDRAWN] * width for _ in range(height)]
        self.back  = [[self._blank]   * width for _ in range(height)]

    def resize(self, height: int, width: int):
        self.h = height
        self.w = width
        self.front = [[self._UNDRAWN] * width for _ in range(height)]
        self.back  = [[self._blank]   * width for _ in range(height)]

    def clear(self):
        blank = self._blank
        for row in self.back:
            for i in range(len(row)):
                row[i] = blank

    def put(self, y: int, x: int, ch: str, attr: int = 0):
        if 0 <= y < self.h and 0 <= x < self.w:
            self.back[y][x] = (ch, attr)

    def puts(self, y: int, x: int, text: str, attr: int = 0,
             transparent: bool = False):
        """Write a string into the back buffer.

        When transparent=True (fish sprites):
          - Leading spaces are positional — they are written as water-background
            spaces so the sprite row is correctly offset from fish.ix.
          - Interior/trailing spaces are skipped so the water background already
            drawn beneath the fish shows through the body.

        This correctly handles tall multi-row sprites like the stingray where
        rows such as '           /\\' rely on leading spaces for alignment.
        """
        if not transparent:
            for i, ch in enumerate(text):
                self.put(y, x + i, ch, attr)
            return

        # Find where leading spaces end
        leading = len(text) - len(text.lstrip(" "))
        for i, ch in enumerate(text):
            if ch == " " and i >= leading:
                continue   # interior/trailing space — transparent
            self.put(y, x + i, ch, attr)

    def invalidate(self):
        """Reset the front buffer so the next flush redraws every cell.
        Call this whenever stdscr.clear() is called so the diff stays in sync."""
        for row in self.front:
            for i in range(len(row)):
                row[i] = self._UNDRAWN

    def flush(self, stdscr):
        for y in range(self.h):
            for x in range(self.w):
                cell = self.back[y][x]
                if cell != self.front[y][x]:
                    try:
                        stdscr.addch(y, x, cell[0], cell[1])
                    except curses.error:
                        pass
                    self.front[y][x] = cell
        self.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  Drawing helpers
# ══════════════════════════════════════════════════════════════════════════════

def draw_background(buf: DoubleBuffer, water_attr: int):
    for y in range(1, buf.h - 1):
        for x in range(1, buf.w - 1):
            buf.put(y, x, " ", water_attr)


def draw_border(buf: DoubleBuffer, attr: int):
    h, w = buf.h, buf.w
    for x in range(w):
        buf.put(0,     x, "~", attr)
        buf.put(h - 1, x, "_", attr)
    for y in range(1, h - 1):
        buf.put(y, 0,     "|", attr)
        buf.put(y, w - 1, "|", attr)


def draw_fish(buf: DoubleBuffer, fish: Fish):
    attr = curses.color_pair(CP_FISH[fish.color_idx]) | curses.A_BOLD
    for i, row in enumerate(fish.sprite_rows):
        if row:
            buf.puts(fish.y + i, fish.ix, row, attr, transparent=True)


def draw_bubble(buf: DoubleBuffer, bubble: Bubble):
    buf.put(bubble.iy, bubble.ix, bubble.char, curses.color_pair(CP_BUBBLE))


def draw_status(buf: DoubleBuffer, fish_list: list, paused: bool,
                dn: DayNight, theme_label: str = "default"):
    attr  = curses.color_pair(CP_STATUS)
    phase = "night" if dn.phase() > 0.5 else "day"
    msg   = (f"  fish:{len(fish_list)}  |  +/- add/remove  |  "
             f"p pause  |  t theme:{theme_label}  |  r reload  |  q quit  |  {phase}")
    if paused:
        msg = "  PAUSED  " + msg
    buf.puts(buf.h - 1, 0, msg[:buf.w], attr)


# ══════════════════════════════════════════════════════════════════════════════
#  Color initialisation
# ══════════════════════════════════════════════════════════════════════════════

def init_colors(cfg: Config, dn: DayNight):
    curses.start_color()
    curses.use_default_colors()

    if not (dn.enabled and dn._extended):
        curses.init_pair(CP_WATER, curses.COLOR_CYAN, curses.COLOR_BLUE)
    
    bg_color = dn._slot_bg if (dn.enabled and dn._extended) else curses.COLOR_BLUE
    for i, fg in enumerate(_FISH_PALETTE):
        curses.init_pair(CP_FISH[i], fg, curses.COLOR_BLUE)

    curses.init_pair(CP_BORDER,  _named_color(cfg.color_border),  curses.COLOR_BLUE)
    curses.init_pair(CP_BUBBLE,  _named_color(cfg.color_bubble),  curses.COLOR_BLUE)
    curses.init_pair(CP_SEAWEED, _named_color(cfg.color_seaweed), curses.COLOR_BLUE)
    curses.init_pair(CP_ROCK,    _named_color(cfg.color_rock),    curses.COLOR_BLUE)
    curses.init_pair(CP_CORAL,   _named_color(cfg.color_coral),   curses.COLOR_BLUE)
    curses.init_pair(CP_SAND,    _named_color(cfg.color_sand),    curses.COLOR_BLUE)
    curses.init_pair(CP_CHEST,   _named_color(cfg.color_chest),   curses.COLOR_BLUE)
    curses.init_pair(CP_STATUS,
                     _named_color(cfg.color_status_fg, curses.COLOR_BLACK),
                     _named_color(cfg.color_status_bg, curses.COLOR_WHITE))


# ══════════════════════════════════════════════════════════════════════════════
#  Theme application helper
# ══════════════════════════════════════════════════════════════════════════════

def _build_active_config(base_cfg_path: Path,
                         base_fish_path: Path,
                         theme_mgr: ThemeManager) -> tuple:
    """
    Return (cfg, lib, fish_path, scenery_layout) with the current theme
    merged on top of the base files.
    """
    cfg  = Config(base_cfg_path)
    pack = theme_mgr.current()
    apply_theme(cfg, pack)                          # overrides cfg in-place

    fish_path = pack.fish_path if (pack and pack.fish_path) else base_fish_path
    lib       = SpriteLibrary(fish_path)

    layout    = pack.layout if pack else None       # None → Scenery uses default

    return cfg, lib, layout


# ══════════════════════════════════════════════════════════════════════════════
#  Spawn helpers
# ══════════════════════════════════════════════════════════════════════════════

def spawn_fish(height: int, width: int, lib: SpriteLibrary, cfg: Config) -> Fish:
    x = random.randint(1, max(1, width - 14))
    y = random.randint(1, max(1, height - 5))
    return Fish(x, y, height, width, lib, cfg)


def maybe_spawn_bubble(fish_list: list, bubbles: list,
                       height: int, width: int, floor_y: int, cfg: Config):
    for fish in fish_list:
        if random.random() < cfg.bubble_fish_chance:
            bx = fish.ix + random.randint(0, max(1, fish.length - 1))
            bx = max(1, min(width - 2, bx))
            by = max(1, fish.y - 1)
            bubbles.append(Bubble(bx, by))
    if random.random() < cfg.bubble_floor_chance:
        bubbles.append(Bubble(random.randint(1, width - 2), floor_y - 1))


# ══════════════════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════════════════

def main(stdscr, initial_theme: str = ""):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    # ── Theme manager ─────────────────────────────────────────────────────────
    theme_mgr = ThemeManager()

    if initial_theme:
        if not theme_mgr.select(initial_theme):
            # Theme not found — write a warning, continue with default
            stdscr.addstr(0, 0, f"Warning: theme '{initial_theme}' not found. "
                                 "Press any key to continue with default.")
            stdscr.nodelay(False)
            stdscr.getch()
            stdscr.nodelay(True)
            stdscr.clear()

    # ── Initial config + sprites (with theme applied) ─────────────────────────
    cfg, lib, layout = _build_active_config(CFG_FILE, FISH_FILE, theme_mgr)
    dn               = DayNight(cfg)
    init_colors(cfg, dn)

    height, width = stdscr.getmaxyx()
    buf     = DoubleBuffer(height, width)
    scenery = Scenery(height, width, layout=layout)

    fish_list = [spawn_fish(height, width, lib, cfg) for _ in range(cfg.fish_start)]
    bubbles   = []

    frame_time = 1.0 / max(1, min(60, cfg.fps))
    paused     = False
    last_frame = time.monotonic()

    while True:
        # ── Input ─────────────────────────────────────────────────────────────
        key = stdscr.getch()

        if key in (ord("q"), ord("Q"), 27):
            break

        elif key in (ord("p"), ord("P")):
            paused = not paused

        elif key == ord("+") and len(fish_list) < cfg.fish_max:
            fish_list.append(spawn_fish(height, width, lib, cfg))

        elif key == ord("-") and fish_list:
            fish_list.pop()

        elif key in (ord("r"), ord("R")):
            # Hot-reload base files and re-apply current theme
            cfg, lib, layout = _build_active_config(CFG_FILE, FISH_FILE, theme_mgr)
            dn               = DayNight(cfg)
            frame_time       = 1.0 / max(1, min(60, cfg.fps))
            init_colors(cfg, dn)
            scenery.set_layout(layout)

        elif key == ord("t"):
            # Advance to next theme
            theme_mgr.next()
            cfg, lib, layout = _build_active_config(CFG_FILE, FISH_FILE, theme_mgr)
            dn               = DayNight(cfg)
            frame_time       = 1.0 / max(1, min(60, cfg.fps))
            init_colors(cfg, dn)
            scenery.set_layout(layout)
            # Respawn fish so they pick up the new sprites
            fish_list = [spawn_fish(height, width, lib, cfg)
                         for _ in range(len(fish_list))]
            bubbles   = []
            stdscr.clear()
            buf.invalidate()

        elif key == ord("T"):
            # Step backward through themes
            theme_mgr.prev()
            cfg, lib, layout = _build_active_config(CFG_FILE, FISH_FILE, theme_mgr)
            dn               = DayNight(cfg)
            frame_time       = 1.0 / max(1, min(60, cfg.fps))
            init_colors(cfg, dn)
            scenery.set_layout(layout)
            fish_list = [spawn_fish(height, width, lib, cfg)
                         for _ in range(len(fish_list))]
            bubbles   = []
            stdscr.clear()
            buf.invalidate()

        # ── Resize ────────────────────────────────────────────────────────────
        new_h, new_w = stdscr.getmaxyx()
        if new_h != height or new_w != width:
            height, width = new_h, new_w
            buf.resize(height, width)
            scenery.rebuild_if_resized(height, width)
            stdscr.clear()
            buf.invalidate()

        floor_y = height - 2

        # ── Frame timing ──────────────────────────────────────────────────────
        now   = time.monotonic()
        delta = now - last_frame
        if delta < frame_time:
            time.sleep(frame_time - delta)
        last_frame = time.monotonic()

        # ── Update ────────────────────────────────────────────────────────────
        if not paused:
            dn.update()
            for fish in fish_list:
                fish.update(height, width)
            scenery.update()
            maybe_spawn_bubble(fish_list, bubbles, height, width, floor_y, cfg)
            bubbles = [b for b in bubbles if b.update()]
            if len(bubbles) > cfg.bubble_max:
                bubbles = bubbles[-cfg.bubble_max:]

        # ── Render ────────────────────────────────────────────────────────────
        water_attr  = dn.water_attr()
        border_attr = curses.color_pair(CP_BORDER) | curses.A_BOLD

        draw_background(buf, water_attr)
        scenery.draw_static(buf)
        scenery.draw_seaweed(buf)
        for b in bubbles:
            if 1 <= b.iy < height - 1 and 1 <= b.ix < width - 1:
                draw_bubble(buf, b)
        for fish in fish_list:
            draw_fish(buf, fish)
        draw_border(buf, border_attr)
        draw_status(buf, fish_list, paused, dn,
                    theme_label=theme_mgr.current_label())
        buf.flush(stdscr)
        stdscr.refresh()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args():
    parser = argparse.ArgumentParser(
        description="ASCII Aquarium — a peaceful terminal fish tank.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Controls while running:\n"
            "  q / ESC  quit          p  pause\n"
            "  +  add fish            -  remove fish\n"
            "  t  next theme          T  previous theme\n"
            "  r  reload config files"
        ),
    )
    parser.add_argument(
        "--theme", metavar="NAME",
        help="Start with a specific theme (e.g. coral_reef).",
    )
    parser.add_argument(
        "--list-themes", action="store_true",
        help="Print available theme names and exit.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.list_themes:
        mgr    = ThemeManager()
        themes = mgr.names()
        if themes:
            print("Available themes:")
            for name in themes:
                pack = mgr.select(name)
                blurb = f"  — {pack.blurb}" if pack and pack.blurb else ""
                print(f"  {name}{blurb}")
        else:
            print("No themes found. Create a folder inside themes/ to get started.")
        sys.exit(0)

    try:
        curses.wrapper(main, initial_theme=args.theme or "")
    except KeyboardInterrupt:
        pass
