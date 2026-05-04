from __future__ import annotations
#!/usr/bin/env python3
"""
aquarium.py — ASCII Aquarium, Phase 2
Adds bubbles, static scenery (rocks, coral, treasure chest),
and animated seaweed that sways each frame.

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
import math
# ── Constants ─────────────────────────────────────────────────────────────────

FPS          = 24
FRAME_TIME   = 1.0 / FPS

# Fish sprites: [facing-right, facing-left]
FISH_SPRITES = [
    ["><>", "<><"],
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
COLOR_BUBBLE    = 9
COLOR_SEAWEED   = 10
COLOR_ROCK      = 11
COLOR_CORAL     = 12
COLOR_SAND      = 13
COLOR_CHEST     = 14

FISH_COLORS_FG = [
    curses.COLOR_YELLOW,
    curses.COLOR_WHITE,
    curses.COLOR_GREEN,
    curses.COLOR_CYAN,
    curses.COLOR_MAGENTA,
]

# Seaweed sway animation: three frames cycling left → centre → right → centre
SEAWEED_FRAMES = [
    ["/", "¦", "/", "¦"],   # lean left
    ["|", "|", "|", "|"],   # upright
    ["\\","¦","\\","¦"],    # lean right
    ["|", "|", "|", "|"],   # upright
]
SEAWEED_CYCLE = len(SEAWEED_FRAMES)   # 4 frames per full sway

# Bubble characters by age (young → old → pop)
BUBBLE_CHARS = [".", "o", "O", "0", "*"]


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


# ── Bubble entity ─────────────────────────────────────────────────────────────

class Bubble:
    """A single bubble that rises from a fish or the floor."""

    LIFESPAN = 28   # frames before popping at the surface

    def __init__(self, x: int, y: int):
        self.x        = x
        self.y        = float(y)
        self.age      = 0
        self.wobble   = 0.0             # horizontal drift phase
        self.rise     = random.uniform(0.12, 0.22)   # cells/frame upward

    def update(self) -> bool:
        """Return True while the bubble is alive."""
        self.age   += 1
        self.y     -= self.rise
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


# ── Seaweed entity ────────────────────────────────────────────────────────────

class Seaweed:
    """
    A column of seaweed anchored to the sea floor.
    Each stalk sways through SEAWEED_FRAMES, offset by a random phase
    so neighbouring stalks don't move in lock-step.
    """

    def __init__(self, x: int, floor_y: int, height: int = None):
        self.x        = x
        self.floor_y  = floor_y
        self.height   = height if height is not None else random.randint(3, 7)
        self.phase    = random.randrange(SEAWEED_CYCLE)   # frame offset
        self.tick     = 0
        # how many game frames per sway frame (slower = lazier sway)
        self.speed    = random.choice([6, 8, 10])

    def update(self):
        self.tick += 1
        if self.tick >= self.speed:
            self.tick  = 0
            self.phase = (self.phase + 1) % SEAWEED_CYCLE

    def segments(self):
        """Yield (y, char) pairs from tip to base."""
        frame = SEAWEED_FRAMES[self.phase]
        for i in range(self.height):
            y   = self.floor_y - i
            ch  = frame[i % len(frame)]
            yield y, ch


# ── Static scenery ────────────────────────────────────────────────────────────

class Scenery:
    """
    Manages static and animated background decorations:
    rocks, coral clusters, a treasure chest, and seaweed stalks.
    All positions are expressed as fractions of terminal width/height
    so the scene re-tiles nicely on resize.
    """

    # (x_frac, y_rows_from_floor, element_type)
    # x_frac: 0.0–1.0 relative to interior width
    LAYOUT = [
        # seaweed columns (x_frac)
        ("seaweed", 0.08),
        ("seaweed", 0.18),
        ("seaweed", 0.32),
        ("seaweed", 0.55),
        ("seaweed", 0.68),
        ("seaweed", 0.82),
        ("seaweed", 0.91),
        # rocks
        ("rock",    0.12),
        ("rock",    0.45),
        ("rock",    0.75),
        # coral
        ("coral",   0.25),
        ("coral",   0.60),
        ("coral",   0.88),
        # chest
        ("chest",   0.38),
    ]

    # Multi-line sprites: list of strings, drawn bottom-up from floor_y
    ROCK_SPRITE   = ["▄▄▄▄", "████", "▀▀▀▀"]   # 3 rows tall
    CORAL_SPRITES = [
        ["\\*/", "|/|", " | "],
        [" /|\\", " |||", "  |  "],
    ]
    CHEST_SPRITE  = [
        "╔══╗",
        "║()║",
        "╚══╝",
    ]

    def __init__(self, height: int, width: int):
        self.seaweeds: list[Seaweed] = []
        self._build(height, width)

    def _build(self, height: int, width: int):
        """Reconstruct all scenery for current terminal dimensions."""
        inner_w  = max(1, width - 2)
        floor_y  = height - 2        # last interior row

        self.floor_y = floor_y
        self.width   = width
        self.height  = height

        # Bake static elements as (y, x, char, color_pair_id) tuples
        self.static: list[tuple] = []
        self.seaweeds = []

        # Sand floor strip
        for x in range(1, width - 1):
            self.static.append((floor_y, x, '~', COLOR_SAND))

        for kind, x_frac in self.LAYOUT:
            x = 1 + int(x_frac * (inner_w - 1))
            x = max(1, min(width - 6, x))

            if kind == "seaweed":
                sw = Seaweed(x, floor_y - 1)
                self.seaweeds.append(sw)

            elif kind == "rock":
                for row_i, row_str in enumerate(self.ROCK_SPRITE):
                    y = floor_y - row_i
                    if y >= 1:
                        for ci, ch in enumerate(row_str):
                            self.static.append((y, x + ci, ch, COLOR_ROCK))

            elif kind == "coral":
                sprite = random.choice(self.CORAL_SPRITES)
                for row_i, row_str in enumerate(sprite):
                    y = floor_y - row_i
                    if y >= 1:
                        for ci, ch in enumerate(row_str):
                            if ch != ' ':
                                self.static.append((y, x + ci, ch, COLOR_CORAL))

            elif kind == "chest":
                for row_i, row_str in enumerate(self.CHEST_SPRITE):
                    y = floor_y - row_i
                    if y >= 1:
                        for ci, ch in enumerate(row_str):
                            self.static.append((y, x + ci, ch, COLOR_CHEST))

    def rebuild_if_resized(self, height: int, width: int):
        if height != self.height or width != self.width:
            self._build(height, width)

    def update(self):
        for sw in self.seaweeds:
            sw.update()

    def draw_static(self, buf: "DoubleBuffer"):
        for y, x, ch, pair_id in self.static:
            buf.put(y, x, ch, curses.color_pair(pair_id))

    def draw_seaweed(self, buf: "DoubleBuffer"):
        attr = curses.color_pair(COLOR_SEAWEED) | curses.A_BOLD
        for sw in self.seaweeds:
            for y, ch in sw.segments():
                if 1 <= y < buf.h - 1:
                    buf.put(y, sw.x, ch, attr)


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


def draw_bubble(buf: DoubleBuffer, bubble: Bubble):
    attr = curses.color_pair(COLOR_BUBBLE)
    buf.put(bubble.iy, bubble.ix, bubble.char, attr)


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

    # Bubbles — cyan on blue
    curses.init_pair(COLOR_BUBBLE,  curses.COLOR_CYAN,  curses.COLOR_BLUE)

    # Seaweed — green on blue
    curses.init_pair(COLOR_SEAWEED, curses.COLOR_GREEN, curses.COLOR_BLUE)

    # Rocks — white on blue (dim gives a grey feel)
    curses.init_pair(COLOR_ROCK,    curses.COLOR_WHITE, curses.COLOR_BLUE)

    # Coral — magenta on blue
    curses.init_pair(COLOR_CORAL,   curses.COLOR_MAGENTA, curses.COLOR_BLUE)

    # Sand floor — yellow on blue
    curses.init_pair(COLOR_SAND,    curses.COLOR_YELLOW,  curses.COLOR_BLUE)

    # Treasure chest — yellow on blue, bold gives gold feel
    curses.init_pair(COLOR_CHEST,   curses.COLOR_YELLOW,  curses.COLOR_BLUE)


# ── Main game loop ────────────────────────────────────────────────────────────

def spawn_fish(height: int, width: int) -> Fish:
    x = random.randint(1, max(1, width - 12))
    y = random.randint(1, max(1, height - 4))   # keep fish above the floor scenery
    return Fish(x, y, height, width)


def maybe_spawn_bubble(fish_list: list[Fish], bubbles: list[Bubble],
                        height: int, width: int, floor_y: int):
    """Randomly emit bubbles from fish and occasionally from the floor."""
    # From fish (low probability per fish per frame)
    for fish in fish_list:
        if random.random() < 0.015:
            bx = fish.ix + random.randint(0, max(1, fish.length - 1))
            bx = max(1, min(width - 2, bx))
            by = max(1, fish.y - 1)
            bubbles.append(Bubble(bx, by))

    # Occasional floor bubble
    if random.random() < 0.008:
        bx = random.randint(1, width - 2)
        bubbles.append(Bubble(bx, floor_y - 1))


def main(stdscr):
    # Terminal setup
    curses.curs_set(0)          # hide cursor
    stdscr.nodelay(True)        # non-blocking getch
    stdscr.keypad(True)

    init_colors()

    height, width = stdscr.getmaxyx()
    buf     = DoubleBuffer(height, width)
    scenery = Scenery(height, width)

    water_attr  = curses.color_pair(COLOR_WATER_BG)
    border_attr = curses.color_pair(COLOR_BORDER) | curses.A_BOLD

    # Seed the tank with a handful of fish
    fish_list: list[Fish]     = [spawn_fish(height, width) for _ in range(5)]
    bubbles:   list[Bubble]   = []

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
            scenery.rebuild_if_resized(height, width)
            stdscr.clear()

        floor_y = height - 2

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

            scenery.update()

            maybe_spawn_bubble(fish_list, bubbles, height, width, floor_y)

            # Advance bubbles; remove dead ones
            bubbles = [b for b in bubbles if b.update()]

            # Cap bubble count so we don't flood the screen
            if len(bubbles) > 60:
                bubbles = bubbles[-60:]

        # ── Render (back-to-front layer order) ─────────────────────────────
        draw_background(buf, water_attr)        # 1. water fill
        scenery.draw_static(buf)                # 2. sand, rocks, coral, chest
        scenery.draw_seaweed(buf)               # 3. animated seaweed
        for b in bubbles:                       # 4. bubbles (behind fish)
            if 1 <= b.iy < height - 1 and 1 <= b.ix < width - 1:
                draw_bubble(buf, b)
        for fish in fish_list:                  # 5. fish
            draw_fish(buf, fish)
        draw_border(buf, border_attr)           # 6. border (on top)
        draw_status(buf, fish_list, paused)     # 7. status bar
        buf.flush(stdscr)
        stdscr.refresh()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("Thanks for visiting the aquarium! 🐟")
