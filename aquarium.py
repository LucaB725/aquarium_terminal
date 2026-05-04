#!/usr/bin/env python3
"""
aquarium.py — ASCII Aquarium, Phase 3
• Fish sprites loaded from fish.txt  (add your own without touching this file)
• All tunable parameters read from aquarium.cfg
• Day / night colour cycle shifts the water from bright day-blue to deep navy
• Full colour theming for every scene element

Controls:
  q / ESC   Quit
  p         Pause / unpause
  +         Add a fish
  -         Remove a fish
  r         Reload fish.txt and aquarium.cfg on the fly
"""

from __future__ import annotations

import curses
import time
import random
import math
import os
import sys
from pathlib import Path

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
        {"right": "><>",    "left": "<><",    "color_idx": 0},
        {"right": "><((°>", "left": "<°))><", "color_idx": 3},
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
                line = raw.rstrip("\n").strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    if current.get("right") and current.get("left"):
                        self._commit(current)
                    current = {}
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip().lower()
                val = val.strip()
                if key in ("right", "left"):
                    current[key] = val
                elif key == "color" and val.lower() in color_keys:
                    current["color_idx"] = color_keys.index(val.lower()) % len(CP_FISH)
        if current.get("right") and current.get("left"):
            self._commit(current)

    def _commit(self, d: dict):
        self.sprites.append({
            "right":     d["right"],
            "left":      d["left"],
            "color_idx": d.get("color_idx", random.randrange(len(CP_FISH))),
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
        spr            = lib.random_sprite()
        self.right     = spr["right"]
        self.left      = spr["left"]
        self.color_idx = spr["color_idx"]
        self.direction = random.choice([-1, 1])
        self.sprite    = self.right if self.direction == 1 else self.left
        self.length    = max(len(self.right), len(self.left))
        self.x         = float(x)
        self.y         = y
        self.speed     = random.uniform(cfg.fish_speed_min, cfg.fish_speed_max)

    def update(self, height: int, width: int):
        self.x += self.speed * self.direction
        if self.direction == 1 and self.x + self.length >= width - 1:
            self.direction = -1
            self.sprite    = self.left
        elif self.direction == -1 and self.x <= 1:
            self.direction = 1
            self.sprite    = self.right
        if random.random() < 0.008:
            self.y += random.choice([-1, 1])
        self.y = max(1, min(height - 4, self.y))

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

    def __init__(self, height: int, width: int):
        self.seaweeds = []
        self.static   = []
        self.height = self.width = 0
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

        for kind, xf in self.LAYOUT:
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
    def __init__(self, height: int, width: int):
        self.h = height
        self.w = width
        self._blank = (" ", 0)
        self.front = [[self._blank] * width for _ in range(height)]
        self.back  = [[self._blank] * width for _ in range(height)]

    def resize(self, height: int, width: int):
        self.h = height
        self.w = width
        self.front = [[self._blank] * width for _ in range(height)]
        self.back  = [[self._blank] * width for _ in range(height)]

    def clear(self):
        blank = self._blank
        for row in self.back:
            for i in range(len(row)):
                row[i] = blank

    def put(self, y: int, x: int, ch: str, attr: int = 0):
        if 0 <= y < self.h and 0 <= x < self.w:
            self.back[y][x] = (ch, attr)

    def puts(self, y: int, x: int, text: str, attr: int = 0):
        for i, ch in enumerate(text):
            self.put(y, x + i, ch, attr)

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
    buf.puts(fish.y, fish.ix, fish.sprite, attr)


def draw_bubble(buf: DoubleBuffer, bubble: Bubble):
    buf.put(bubble.iy, bubble.ix, bubble.char, curses.color_pair(CP_BUBBLE))


def draw_status(buf: DoubleBuffer, fish_list: list, paused: bool, dn: DayNight):
    attr  = curses.color_pair(CP_STATUS)
    phase = "night" if dn.phase() > 0.5 else "day"
    msg   = (f"  fish:{len(fish_list)}  |  +/- add/remove  |  "
             f"p pause  |  r reload  |  q quit  |  {phase}")
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

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    cfg = Config(CFG_FILE)
    lib = SpriteLibrary(FISH_FILE)
    dn  = DayNight(cfg)
    init_colors(cfg, dn)

    height, width = stdscr.getmaxyx()
    buf     = DoubleBuffer(height, width)
    scenery = Scenery(height, width)

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
            cfg        = Config(CFG_FILE)
            lib        = SpriteLibrary(FISH_FILE)
            dn         = DayNight(cfg)
            frame_time = 1.0 / max(1, min(60, cfg.fps))
            init_colors(cfg, dn)

        # ── Resize ────────────────────────────────────────────────────────────
        new_h, new_w = stdscr.getmaxyx()
        if new_h != height or new_w != width:
            height, width = new_h, new_w
            buf.resize(height, width)
            scenery.rebuild_if_resized(height, width)
            stdscr.clear()

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
        draw_status(buf, fish_list, paused, dn)
        buf.flush(stdscr)
        stdscr.refresh()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("Thanks for visiting the aquarium! 🐟")
