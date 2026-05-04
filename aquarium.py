#!/usr/bin/env python3
"""
aquarium.py — ASCII Aquarium, Phase 1
Terminal setup, game loop, double-buffer renderer, and basic fish movement.

Controls:
  q / ESC   Quit
  p         Pause / unpause
  +         Add a fish
  -         Remove a fish
"""

import curses
import time
import random
import sys

# ── Constants ─────────────────────────────────────────────────────────────────

FPS          = 24
FRAME_TIME   = 1.0 / FPS

# Fish sprites: [facing-right, facing-left]
FISH_SPRITES = [
    ["><o>", "<o><"],
    [">->", "<-<"],
    ["}-{", "{-}"],
    ["><((°>", "<°))<"],
    ["°><>",  "<><°"],
]

# Color pair IDs (defined in init_colors)
COLOR_WATER_BG  = 1
COLOR_FISH      = [2, 3, 4, 5, 6]   # one per fish colour
COLOR_BORDER    = 7
COLOR_STATUS    = 8

FISH_COLORS_FG = [
    curses.COLOR_YELLOW,
    curses.COLOR_WHITE,
    curses.COLOR_GREEN,
    curses.COLOR_CYAN,
    curses.COLOR_MAGENTA,
]


# ── Data classes ──────────────────────────────────────────────────────────────

class Fish:
    """A single fish entity."""

    def __init__(self, x: float, y: int, height: int, width: int):
        self.sprite_idx = random.randrange(len(FISH_SPRITES))
        self.color_idx  = random.randrange(len(COLOR_FISH))
        sprites         = FISH_SPRITES[self.sprite_idx]
        self.direction  = random.choice([-1, 1])          # -1 left, +1 right
        self.sprite     = sprites[0] if self.direction == 1 else sprites[1]
        self.length     = max(len(sprites[0]), len(sprites[1]))
        self.x          = float(x)
        self.y          = y
        self.speed      = random.uniform(0.08, 0.22)      # cells per frame
        self._height    = height
        self._width     = width

    def update(self, height: int, width: int):
        """Advance position; bounce/wrap at edges."""
        self._height = height
        self._width  = width
        self.x += self.speed * self.direction

        sprites = FISH_SPRITES[self.sprite_idx]

        # Horizontal bounce: flip direction when hitting walls
        if self.direction == 1 and self.x + self.length >= width - 1:
            self.direction = -1
            self.sprite    = sprites[1]
        elif self.direction == -1 and self.x <= 1:
            self.direction = 1
            self.sprite    = sprites[0]

        # Vertical wrap (fish occasionally drift up/down)
        if random.random() < 0.008:
            self.y += random.choice([-1, 1])
        self.y = max(1, min(height - 2, self.y))

    @property
    def ix(self) -> int:
        return int(self.x)


# ── Renderer ──────────────────────────────────────────────────────────────────

class DoubleBuffer:
    """Two char/attr grids; only flush cells that changed."""

    def __init__(self, height: int, width: int):
        self.h = height
        self.w = width
        self._blank = (' ', 0)
        self.front = [[self._blank] * width for _ in range(height)]
        self.back  = [[self._blank] * width for _ in range(height)]

    def resize(self, height: int, width: int):
        self.h = height
        self.w = width
        self.front = [[self._blank] * width for _ in range(height)]
        self.back  = [[self._blank] * width for _ in range(height)]

    def clear(self):
        for row in self.back:
            for i in range(len(row)):
                row[i] = self._blank

    def put(self, y: int, x: int, ch: str, attr: int = 0):
        if 0 <= y < self.h and 0 <= x < self.w:
            self.back[y][x] = (ch, attr)

    def puts(self, y: int, x: int, text: str, attr: int = 0):
        """Write a string, clipping at buffer edges."""
        for i, ch in enumerate(text):
            self.put(y, x + i, ch, attr)

    def flush(self, stdscr):
        """Write only changed cells to the terminal."""
        for y in range(self.h):
            for x in range(self.w):
                cell = self.back[y][x]
                if cell != self.front[y][x]:
                    try:
                        stdscr.addch(y, x, cell[0], cell[1])
                    except curses.error:
                        pass   # ignore writes to bottom-right corner
                    self.front[y][x] = cell
        self.clear()


# ── Scene drawing helpers ─────────────────────────────────────────────────────

def draw_border(buf: DoubleBuffer, attr: int):
    h, w = buf.h, buf.w
    # Top and bottom
    for x in range(w):
        buf.put(0,     x, '~', attr)
        buf.put(h - 1, x, '_', attr)
    # Sides
    for y in range(1, h - 1):
        buf.put(y, 0,     '|', attr)
        buf.put(y, w - 1, '|', attr)


def draw_background(buf: DoubleBuffer, water_attr: int):
    """Fill interior with water colour."""
    for y in range(1, buf.h - 1):
        for x in range(1, buf.w - 1):
            buf.put(y, x, ' ', water_attr)


def draw_fish(buf: DoubleBuffer, fish: Fish):
    attr = curses.color_pair(COLOR_FISH[fish.color_idx]) | curses.A_BOLD
    buf.puts(fish.y, fish.ix, fish.sprite, attr)


def draw_status(buf: DoubleBuffer, fish_list: list, paused: bool):
    attr   = curses.color_pair(COLOR_STATUS)
    msg    = f"  fish: {len(fish_list)}  |  +/- add/remove  |  p pause  |  q quit"
    if paused:
        msg = "  *** PAUSED ***" + msg
    buf.puts(buf.h - 1, 0, msg[:buf.w], attr)


# ── Color init ────────────────────────────────────────────────────────────────

def init_colors():
    curses.start_color()
    curses.use_default_colors()

    # Water background — dark blue bg, cyan fg
    curses.init_pair(COLOR_WATER_BG, curses.COLOR_CYAN,   curses.COLOR_BLUE)

    # Fish colours
    for i, fg in enumerate(FISH_COLORS_FG):
        curses.init_pair(COLOR_FISH[i], fg, curses.COLOR_BLUE)

    # Border — white on blue
    curses.init_pair(COLOR_BORDER, curses.COLOR_WHITE, curses.COLOR_BLUE)

    # Status bar — black on white
    curses.init_pair(COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE)


# ── Main game loop ────────────────────────────────────────────────────────────

def spawn_fish(height: int, width: int) -> Fish:
    x = random.randint(1, max(1, width - 12))
    y = random.randint(1, max(1, height - 2))
    return Fish(x, y, height, width)


def main(stdscr):
    # Terminal setup
    curses.curs_set(0)          # hide cursor
    stdscr.nodelay(True)        # non-blocking getch
    stdscr.keypad(True)

    init_colors()

    height, width = stdscr.getmaxyx()
    buf = DoubleBuffer(height, width)

    water_attr  = curses.color_pair(COLOR_WATER_BG)
    border_attr = curses.color_pair(COLOR_BORDER) | curses.A_BOLD

    # Seed the tank with a handful of fish
    fish_list: list[Fish] = [spawn_fish(height, width) for _ in range(5)]

    paused     = False
    last_frame = time.monotonic()

    while True:
        # ── Input ──────────────────────────────────────────────────────────
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):          # q or ESC
            break
        elif key in (ord('p'), ord('P')):
            paused = not paused
        elif key == ord('+') and len(fish_list) < 30:
            fish_list.append(spawn_fish(height, width))
        elif key == ord('-') and fish_list:
            fish_list.pop()

        # ── Terminal resize ────────────────────────────────────────────────
        new_h, new_w = stdscr.getmaxyx()
        if new_h != height or new_w != width:
            height, width = new_h, new_w
            buf.resize(height, width)
            stdscr.clear()

        # ── Frame timing ───────────────────────────────────────────────────
        now   = time.monotonic()
        delta = now - last_frame
        if delta < FRAME_TIME:
            time.sleep(FRAME_TIME - delta)
        last_frame = time.monotonic()

        # ── Update ─────────────────────────────────────────────────────────
        if not paused:
            for fish in fish_list:
                fish.update(height, width)

        # ── Render ─────────────────────────────────────────────────────────
        draw_background(buf, water_attr)
        draw_border(buf, border_attr)
        for fish in fish_list:
            draw_fish(buf, fish)
        draw_status(buf, fish_list, paused)
        buf.flush(stdscr)
        stdscr.refresh()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("Thanks for visiting the aquarium! 🐟")
