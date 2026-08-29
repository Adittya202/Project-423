from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
import math
import random
import os
import colorsys

# ============================================================
#  CONFIG / GLOBAL STATE
# ============================================================

WINDOW_W, WINDOW_H = 1000, 800
GRID_LENGTH = 200
FOVY = 90

camera_orbit_angle = 90.0
camera_height = 500
CAMERA_RADIUS = 650
ORBIT_SPEED = 3
HEIGHT_SPEED = 15
HEIGHT_MIN, HEIGHT_MAX = 200, 900

_saved_orbit_angle = None
_saved_height = None

# ---- game states ----
STATE_NORMAL = "normal"
STATE_ROBBER_CHOICE = "robber_choice"
STATE_RPS = "rps"
STATE_CAKE_EATING = "cake_eating"
STATE_WIN = "win"

game_state = STATE_NORMAL
paused = False

# ---- economy ----
money = 0
target = random.randint(400, 700)
police_calls = 3
next_milestone = 150

# ---- cake definitions ----
SHAPES = ["square", "rectangle", "round"]
FLAVORS = {
    "vanilla": (0.95, 0.92, 0.80),
    "chocolate": (0.36, 0.20, 0.09),
    "strawberry": (0.95, 0.55, 0.70),
}
FLAVOR_LIST = list(FLAVORS.keys())


def new_order():
    return {
        "shape": random.choice(SHAPES),
        "flavor": random.choice(FLAVOR_LIST),
        "tiers": random.choice([1, 2]),
        "topping": random.choice([None, "cherry", "chocobar"]),
    }


current_order = new_order()

# ---- cake the player is currently assembling ----
build_phase = 0  # 0 shape, 1 flavor, 2 tiers, 3 topping, then confirm submits
build = {"shape_idx": 0, "flavor_idx": 0, "tiers": 1, "topping_idx": 0}

# ---- order lifecycle: "taking" (player is free to build) or "delivering"
# (order just submitted, player is walking the cake to the register) ----
order_stage = "taking"
carried_cake = None  # snapshot dict of the cake while it's being walked over
ORDER_HANDOFF_DELAY = 420  # frames before a new order actually starts
order_handoff_timer = 0

# ---- the player's own on-screen position: they shuttle between the
# register and the cake table ----
PLAYER_REGISTER_POS = (-250.0, 0.0)
PLAYER_TABLE_POS = (280.0, -20.0)
PLAYER_SPEED = 2.0
player_x, player_y = PLAYER_REGISTER_POS
player_target_x, player_target_y = PLAYER_REGISTER_POS


def send_player_to(pos):
    global player_target_x, player_target_y
    player_target_x, player_target_y = pos


# ---- HUD feedback (icon + optional number, no text) ----
# message_kind identifies which icon/number combo draw_hud() should flash.
message_kind = None
message_value = None
message_timer = 0

# ---- coins scattered on the floor ----
coins = []  # each: {"x":.., "y":..}
pending_coin_respawns = []  # each: {"timer": frames_left}
MAX_COINS = 8
COIN_RESPAWN_DELAY = 100  # frames (~a couple of seconds) before a picked coin returns
frame_count = 0

# ---- robber event ----
robber_timer = 0
ROBBER_TIME_LIMIT = 3000  # frames, ~ a few seconds of idle() calls
ROBBER_SPAWN_INTERVAL = 30  # larger value = robber appears less often
ROBBER_SPAWN_CHANCE = 0.01   # chance per interval

# ---- rock paper scissors ----
RPS_OPTIONS = ["rock", "paper", "scissors"]

# ---- cake eating duel ----
player_cake_amt = 100.0
robber_cake_amt = 100.0
DUEL_CAKE_PRICE = 15

# ---- shop shell: 4 walls / roof / two sliding doors ----
ROOM_LEFT, ROOM_RIGHT, ROOM_BACK, ROOM_FRONT = -1000, 1000, 1000, -1000
ROOF_Z = 520

# entrance door (left wall) — customers, robber, and police all walk IN here
DOOR_X = ROOM_LEFT
DOOR_Y = -280
DOOR_HALF = 95
door_anim = 1.0  # 0 = fully closed, 1 = fully open

# exit door (front wall — the side that used to be left open) — customers
# walk OUT here once their order is finished or refused
EXIT_DOOR_Y = ROOM_FRONT
EXIT_DOOR_X = 480
EXIT_DOOR_HALF = 95
exit_door_anim = 1.0

# ---- actor colours ----
PLAYER_COLOR = (0.6, 0.2, 0.4)     # pink
ROBBER_COLOR = (0.55, 0.35, 0.85)     # violet
POLICE_COLOR = (0.05, 0.35, 0.18)     # dark green

# ---- customer queue (visual only — order logic still lives in current_order) ----
QUEUE_SLOTS_X = [-280, -450, -620, -790]
QUEUE_Y = -280
CUSTOMER_SPEED = 2
customer_queue = []      # list of {"x","y","target_x","target_y","color"}
leaving_customers = []   # customers walking out through the exit door

# ---- robber / police stage positions & entrance-exit animation (still use
# the entrance door on the left) ----
ROBBER_STAND_X = 320
POLICE_STAND_X = 160
robber_x = DOOR_X
robber_target_x = DOOR_X
robber_visible = False
police_x = DOOR_X
police_target_x = DOOR_X
police_visible = False
police_visit_timer = 0

# ---- random chatter / order notifications (custom quad font, no glutBitmapCharacter) ----
notif_text = None
notif_color = (1, 1, 1)
notif_timer = 0
notif_persistent = False  # True while a customer's chatter line should stay up indefinitely
NOTIF_DURATION = 260
ORDER_RESULT_DURATION = 240

CUSTOMER_LINES = [
    "ITS SUCH A SUNNY DAY",
    "THE CAKES LOOK DELICIOUS",
    "GOOD MORNING",
    "I AM GETTING MARRIED",
    "TODAY IS MY BIRTHDAY",
    "I AM TURNING 40 TODAY",
    "OMG!! YIZHAN!!!",
    "I LOVE REDVELVET",
    "SHENG MING JIE SHU LE",
    "WO SHI BAOBEI",
    "FANG YILUN IS THE MOST BEAUTIFUL",
    "I hope the cakes are fresh"
]

ROBBER_LINES = [
    "THIS IS A ROBBERY",
    "GIVE ME ALL YOUR MONEY",
    "GIVE YOUR EVERYTHING TO ME, PLEASE?",
    "AIN'T I THE PRETTIEST? GIVE YOUR EVERYTHING TO ME PLEASE?",
    "You earn so much money. Please give me some?"
]


# ============================================================
#  DRAWING HELPERS
# ============================================================

def draw_cake(shape, flavor, tiers, topping, x, y, base_size=60, z_offset=0):
    """Draws one cake using only glutSolidCube / gluCylinder / gluSphere.
    z_offset lifts the whole cake up (e.g. to look like it's being carried)."""
    color = FLAVORS[flavor]
    glPushMatrix()
    glTranslatef(x, y, z_offset)

    top_h = 0
    glColor3f(*color)

    if shape == "square":
        glPushMatrix()
        glTranslatef(0, 0, base_size / 2)
        glutSolidCube(base_size)
        glPopMatrix()
        top_h = base_size
        if tiers == 2:
            top_size = base_size * 0.6
            glPushMatrix()
            glTranslatef(0, 0, base_size + top_size / 2)
            glutSolidCube(top_size)
            glPopMatrix()
            top_h += top_size

    elif shape == "rectangle":
        glPushMatrix()
        glTranslatef(0, 0, base_size * 0.4)
        glScalef(1.6, 1.0, 0.8)
        glutSolidCube(base_size)
        glPopMatrix()
        top_h = base_size * 0.8
        if tiers == 2:
            glPushMatrix()
            glTranslatef(0, 0, top_h + base_size * 0.15)
            glScalef(1.0, 0.6, 0.5)
            glutSolidCube(base_size * 0.6)
            glPopMatrix()
            top_h += base_size * 0.3

    elif shape == "round":
        quad = gluNewQuadric()
        glPushMatrix()
        gluCylinder(quad, base_size * 0.5, base_size * 0.5, base_size * 0.6, 16, 4)
        glPopMatrix()
        top_h = base_size * 0.6
        if tiers == 2:
            glPushMatrix()
            glTranslatef(0, 0, top_h)
            gluCylinder(quad, base_size * 0.32, base_size * 0.32, base_size * 0.5, 16, 4)
            glPopMatrix()
            top_h += base_size * 0.5

    if topping == "cherry":
        glColor3f(0.8, 0.05, 0.15)
        glPushMatrix()
        glTranslatef(0, 0, top_h + 10)
        gluSphere(gluNewQuadric(), 9, 8, 8)
        glPopMatrix()
    elif topping == "chocobar":
        glColor3f(0.25, 0.12, 0.05)
        glPushMatrix()
        glTranslatef(0, 0, top_h + 6)
        glScalef(0.6, 0.25, 0.25)
        glutSolidCube(22)
        glPopMatrix()

    glPopMatrix()


def draw_person(x, y, color, height=140):
    """A very simple humanoid stand-in for a customer, the player, a
    robber, or a police officer."""
    glPushMatrix()
    glTranslatef(x, y, 0)
    glColor3f(*color)
    glPushMatrix()
    glTranslatef(0, 0, height * 0.4)
    glScalef(0.5, 0.3, 0.8)
    glutSolidCube(height)
    glPopMatrix()

    glColor3f(0.93, 0.78, 0.65)
    glPushMatrix()
    glTranslatef(0, 0, height * 0.8 + 16)
    gluSphere(gluNewQuadric(), 16, 10, 10)
    glPopMatrix()
    glPopMatrix()


def draw_shop():
    """Counter, register and a hanging shop sign (with a pictorial cake icon)."""
    # counter
    glColor3f(0.45, 0.28, 0.15)
    glPushMatrix()
    glTranslatef(0, -150, 30)
    glScalef(6.0, 1.4, 0.6)
    glutSolidCube(100)
    glPopMatrix()

    # cash register
    glColor3f(0.2, 0.2, 0.25)
    glPushMatrix()
    glTranslatef(250, -150, 90)
    glScalef(0.7, 0.7, 0.6)
    glutSolidCube(60)
    glPopMatrix()

    # small table under the cake the player is assembling
    glColor3f(0.55, 0.4, 0.25)
    glPushMatrix()
    glTranslatef(280, 60, 10)
    glScalef(1.4, 1.4, 0.25)
    glutSolidCube(90)
    glPopMatrix()

    # hanging shop sign (small homage to the starter's spinning cube) with
    # a tiny cake icon on it instead of a text logo
    # glColor3f(0.85, 0.65, 0.2)
    # glPushMatrix()
    # glTranslatef(0, 350, 260)
    # glScalef(2.2, 0.3, 0.6)
    # glutSolidCube(90)
    # glPopMatrix()
    # glColor3f(0.9, 0.85, 0.7)
    # glPushMatrix()
    # glTranslatef(0, 340, 300)
    # glutSolidCube(30)
    # glPopMatrix()
    # glColor3f(0.8, 0.05, 0.15)
    # glPushMatrix()
    # glTranslatef(0, 340, 320)
    # gluSphere(gluNewQuadric(), 6, 8, 8)
    # glPopMatrix()


def _wall_quad(x0, y0, z0, x1, y1, z1, x2, y2, z2, x3, y3, z3, color):
    glColor3f(*color)
    glBegin(GL_QUADS)
    glVertex3f(x0, y0, z0)
    glVertex3f(x1, y1, z1)
    glVertex3f(x2, y2, z2)
    glVertex3f(x3, y3, z3)
    glEnd()


def draw_sliding_door(axis, fixed, center, half, anim):
    """Two leaves that part to open and meet to close. axis='x' means the
    wall this door sits in is a plane of constant x (like the left/right
    walls, door gap runs along y); axis='y' means constant y (the
    back/front walls, door gap runs along x)."""
    leaf_color = (0.32, 0.2, 0.1)
    offset = anim * (half + 15)

    if axis == "x":
        y0 = center - half - offset
        y1 = y0 + half
        _wall_quad(fixed, y0, 0, fixed, y1, 0, fixed, y1, 240, fixed, y0, 240, leaf_color)
        y0b = center + offset
        y1b = y0b + half
        _wall_quad(fixed, y0b, 0, fixed, y1b, 0, fixed, y1b, 240, fixed, y0b, 240, leaf_color)
    else:
        x0 = center - half - offset
        x1 = x0 + half
        _wall_quad(x0, fixed, 0, x1, fixed, 0, x1, fixed, 240, x0, fixed, 240, leaf_color)
        x0b = center + offset
        x1b = x0b + half
        _wall_quad(x0b, fixed, 0, x1b, fixed, 0, x1b, fixed, 240, x0b, fixed, 240, leaf_color)


def draw_environment():
    """Back, left, right and front walls (the left carries the entrance
    door, the front carries the exit door), a couple of windows, and a
    flat roof — built entirely from GL_QUADS."""
    wall_color = (0.87, 0.8, 0.68)
    wall_color2 = (0.8, 0.6, 0.7)

    # back wall
    _wall_quad(ROOM_LEFT, ROOM_BACK, 0, ROOM_RIGHT, ROOM_BACK, 0,
               ROOM_RIGHT, ROOM_BACK, ROOF_Z, ROOM_LEFT, ROOM_BACK, ROOF_Z, wall_color2)
    glColor3f(0.6, 0.85, 0.95)
    for wx in (-450, 450):
        glBegin(GL_QUADS)
        glVertex3f(wx - 80, ROOM_BACK - 2, 160)
        glVertex3f(wx + 80, ROOM_BACK - 2, 160)
        glVertex3f(wx + 80, ROOM_BACK - 2, 320)
        glVertex3f(wx - 80, ROOM_BACK - 2, 320)
        glEnd()

    # right wall (with one window)
    _wall_quad(ROOM_RIGHT, ROOM_FRONT, 0, ROOM_RIGHT, ROOM_BACK, 0,
               ROOM_RIGHT, ROOM_BACK, ROOF_Z, ROOM_RIGHT, ROOM_FRONT, ROOF_Z, wall_color)
    glColor3f(0.6, 0.85, 0.95)
    glBegin(GL_QUADS)
    glVertex3f(ROOM_RIGHT - 2, 550, 160)
    glVertex3f(ROOM_RIGHT - 2, 700, 160)
    glVertex3f(ROOM_RIGHT - 2, 700, 320)
    glVertex3f(ROOM_RIGHT - 2, 550, 320)
    glEnd()

    # left wall, split above/below/beside the entrance door gap
    _wall_quad(ROOM_LEFT, ROOM_FRONT, 0, ROOM_LEFT, DOOR_Y - DOOR_HALF, 0,
               ROOM_LEFT, DOOR_Y - DOOR_HALF, ROOF_Z, ROOM_LEFT, ROOM_FRONT, ROOF_Z, wall_color)
    _wall_quad(ROOM_LEFT, DOOR_Y + DOOR_HALF, 0, ROOM_LEFT, ROOM_BACK, 0,
               ROOM_LEFT, ROOM_BACK, ROOF_Z, ROOM_LEFT, DOOR_Y + DOOR_HALF, ROOF_Z, wall_color)
    _wall_quad(ROOM_LEFT, DOOR_Y - DOOR_HALF, 260, ROOM_LEFT, DOOR_Y + DOOR_HALF, 260,
               ROOM_LEFT, DOOR_Y + DOOR_HALF, ROOF_Z, ROOM_LEFT, DOOR_Y - DOOR_HALF, ROOF_Z, wall_color)

    # front wall (previously the open side), split beside the exit door gap
    _wall_quad(ROOM_LEFT, ROOM_FRONT, 0, EXIT_DOOR_X - EXIT_DOOR_HALF, ROOM_FRONT, 0,
               EXIT_DOOR_X - EXIT_DOOR_HALF, ROOM_FRONT, ROOF_Z, ROOM_LEFT, ROOM_FRONT, ROOF_Z, wall_color2)
    _wall_quad(EXIT_DOOR_X + EXIT_DOOR_HALF, ROOM_FRONT, 0, ROOM_RIGHT, ROOM_FRONT, 0,
               ROOM_RIGHT, ROOM_FRONT, ROOF_Z, EXIT_DOOR_X + EXIT_DOOR_HALF, ROOM_FRONT, ROOF_Z, wall_color2)
    _wall_quad(EXIT_DOOR_X - EXIT_DOOR_HALF, ROOM_FRONT, 260, EXIT_DOOR_X + EXIT_DOOR_HALF, ROOM_FRONT, 260,
               EXIT_DOOR_X + EXIT_DOOR_HALF, ROOM_FRONT, ROOF_Z, EXIT_DOOR_X - EXIT_DOOR_HALF, ROOM_FRONT, ROOF_Z,
               wall_color2)
    # a small green "exit" marker strip above the exit door
    glColor3f(1, 0, 0)
    glBegin(GL_QUADS)
    glVertex3f(EXIT_DOOR_X - EXIT_DOOR_HALF + 10, ROOM_FRONT + 1, 268)
    glVertex3f(EXIT_DOOR_X + EXIT_DOOR_HALF - 10, ROOM_FRONT + 1, 268)
    glVertex3f(EXIT_DOOR_X + EXIT_DOOR_HALF - 10, ROOM_FRONT + 1, 290)
    glVertex3f(EXIT_DOOR_X - EXIT_DOOR_HALF + 10, ROOM_FRONT + 1, 290)
    glEnd()

    # roof
    _wall_quad(ROOM_LEFT, ROOM_FRONT, ROOF_Z, ROOM_RIGHT, ROOM_FRONT, ROOF_Z,
               ROOM_RIGHT, ROOM_BACK, ROOF_Z, ROOM_LEFT, ROOM_BACK, ROOF_Z, (0.5, 0.3, 0.22))

    draw_sliding_door("x", ROOM_LEFT, DOOR_Y, DOOR_HALF, door_anim)
    draw_sliding_door("y", ROOM_FRONT, EXIT_DOOR_X, EXIT_DOOR_HALF, exit_door_anim)



def draw_floor():
    glBegin(GL_QUADS)
    BOARD_SIZE = 11
    HALF = BOARD_SIZE // 2
    for row in range(-HALF, HALF + 1):
        for col in range(-HALF, HALF + 1):
            if (row + col) % 2 == 0:
                glColor3f(0.93, 0.88, 0.80)
            else:
                glColor3f(0.55, 0.35, 0.45)
            x = col * GRID_LENGTH
            y = row * GRID_LENGTH
            glVertex3f(x, y, 0)
            glVertex3f(x + GRID_LENGTH, y, 0)
            glVertex3f(x + GRID_LENGTH, y + GRID_LENGTH, 0)
            glVertex3f(x, y + GRID_LENGTH, 0)
    glEnd()


def draw_coins():
    glColor3f(1.0, 0.85, 0.1)
    for c in coins:
        glPushMatrix()
        glTranslatef(c["x"], c["y"], 14)
        gluSphere(gluNewQuadric(), 10, 8, 8)
        glPopMatrix()
    if coins:
        glPointSize(4)
        glBegin(GL_POINTS)
        for c in coins:
            glVertex3f(c["x"], c["y"], 30)
        glEnd()


# ============================================================
#  DECISION TILES (2D overlay, drawn "in front of" the 3D scene)
# ============================================================
#
# _begin_2d()/_end_2d() push an orthographic projection over the 3D scene
# (same push/pop-matrix idea the starter script used), and every shape
# drawn inside it is GL_QUADS / glVertex3f only — a circle is a fan of
# degenerate quads (two of the four vertices coincide at the centre), and
# a "line" (for the scissors icon) is a thin quad. No text/font call of
# any kind is used anywhere in this file.

TILE_W, TILE_H = 150, 170
TILE_ROW_CY = 150


def _begin_2d():
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WINDOW_W, 0, WINDOW_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()


def _end_2d():
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)


def draw_2d_rect(cx, cy, w, h, r, g, b):
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    glVertex3f(cx - w / 2, cy - h / 2, 0)
    glVertex3f(cx + w / 2, cy - h / 2, 0)
    glVertex3f(cx + w / 2, cy + h / 2, 0)
    glVertex3f(cx - w / 2, cy + h / 2, 0)
    glEnd()


def draw_2d_circle(cx, cy, radius, r, g, b, segments=20):
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        x0, y0 = cx + radius * math.cos(a0), cy + radius * math.sin(a0)
        x1, y1 = cx + radius * math.cos(a1), cy + radius * math.sin(a1)
        glVertex3f(cx, cy, 0)
        glVertex3f(x0, y0, 0)
        glVertex3f(x1, y1, 0)
        glVertex3f(cx, cy, 0)
    glEnd()


def draw_2d_line(x1, y1, x2, y2, thickness, r, g, b):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    glVertex3f(x1 + nx, y1 + ny, 0)
    glVertex3f(x2 + nx, y2 + ny, 0)
    glVertex3f(x2 - nx, y2 - ny, 0)
    glVertex3f(x1 - nx, y1 - ny, 0)
    glEnd()


# ---- seven-segment digits, built purely from draw_2d_rect (GL_QUADS) ----
# segment names: a=top, b=top-right, c=bottom-right, d=bottom,
#                e=bottom-left, f=top-left, g=middle
_DIGIT_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd",
    "4": "fgbc", "5": "afgcd", "6": "afgecd", "7": "abc",
    "8": "abcdefg", "9": "abcdfg",
}


def draw_digit(cx, cy, w, h, digit, color):
    segs = _DIGIT_SEGMENTS.get(digit, "")
    th = min(w, h) * 0.22
    hw, hh = w / 2, h / 2
    vh = hh - th
    if "a" in segs:
        draw_2d_rect(cx, cy + hh - th / 2, w - th, th, *color)
    if "g" in segs:
        draw_2d_rect(cx, cy, w - th, th, *color)
    if "d" in segs:
        draw_2d_rect(cx, cy - hh + th / 2, w - th, th, *color)
    if "f" in segs:
        draw_2d_rect(cx - hw + th / 2, cy + hh / 2, th, vh, *color)
    if "b" in segs:
        draw_2d_rect(cx + hw - th / 2, cy + hh / 2, th, vh, *color)
    if "e" in segs:
        draw_2d_rect(cx - hw + th / 2, cy - hh / 2, th, vh, *color)
    if "c" in segs:
        draw_2d_rect(cx + hw - th / 2, cy - hh / 2, th, vh, *color)


def draw_number(x, y, w, h, number, color, gap=6, minus=False):
    """Draws a non-negative int's digits left-to-right starting at x (the
    left edge), vertically centred on y. Returns the x just past the last
    digit, so callers can chain an icon or another number after it."""
    s = str(abs(int(number)))
    cx = x + w / 2
    if minus or number < 0:
        draw_2d_rect(cx, y, w * 0.55, h * 0.16, *color)
        cx += w * 0.7 + gap
    for ch in s:
        draw_digit(cx, y, w, h, ch, color)
        cx += w + gap
    return cx - gap + w / 2


def draw_progress_bar(cx, cy, w, h, frac, color_full=(0.25, 0.8, 0.3),
                       color_empty=(0.25, 0.25, 0.25)):
    frac = max(0.0, min(1.0, frac))
    draw_2d_rect(cx, cy, w, h, *color_empty)
    if frac > 0:
        fw = w * frac
        draw_2d_rect(cx - w / 2 + fw / 2, cy, fw, h, *color_full)


# ---- small HUD icons (coin, flag, badge, pause, check, cross, star) ----

def icon_coin_hud(cx, cy, r=13):
    draw_2d_circle(cx, cy, r, 1.0, 0.85, 0.1)
    draw_2d_circle(cx, cy, r * 0.55, 0.85, 0.65, 0.05)


def icon_flag_hud(cx, cy):
    draw_2d_rect(cx - 12, cy, 4, 32, 0.3, 0.3, 0.3)
    glColor3f(0.8, 0.1, 0.15)
    glBegin(GL_QUADS)
    glVertex3f(cx - 10, cy + 16, 0)
    glVertex3f(cx - 10, cy + 2, 0)
    glVertex3f(cx + 12, cy + 9, 0)
    glVertex3f(cx + 12, cy + 9, 0)
    glEnd()


def icon_badge_hud(cx, cy, r=11):
    draw_2d_circle(cx, cy, r, 0.85, 0.85, 0.9)
    draw_2d_circle(cx, cy, r * 0.6, 0.15, 0.35, 0.85)


def icon_pause_hud(cx, cy):
    draw_2d_rect(cx - 10, cy, 8, 40, 0.95, 0.95, 0.95)
    draw_2d_rect(cx + 10, cy, 8, 40, 0.95, 0.95, 0.95)


def icon_check_hud(cx, cy, color=(0.2, 0.85, 0.25)):
    draw_2d_line(cx - 15, cy, cx - 3, cy - 13, 6, *color)
    draw_2d_line(cx - 3, cy - 13, cx + 17, cy + 15, 6, *color)


def icon_cross_hud(cx, cy, color=(0.9, 0.2, 0.2)):
    draw_2d_line(cx - 14, cy - 14, cx + 14, cy + 14, 6, *color)
    draw_2d_line(cx - 14, cy + 14, cx + 14, cy - 14, 6, *color)


def icon_star_hud(cx, cy, r_out=24, r_in=10, color=(1.0, 0.85, 0.1)):
    glColor3f(*color)
    glBegin(GL_QUADS)
    for i in range(10):
        a0 = math.pi / 2 + i * math.pi / 5
        a1 = math.pi / 2 + (i + 1) * math.pi / 5
        r0 = r_out if i % 2 == 0 else r_in
        r1 = r_out if (i + 1) % 2 == 0 else r_in
        x0, y0 = cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)
        x1, y1 = cx + r1 * math.cos(a1), cy + r1 * math.sin(a1)
        glVertex3f(cx, cy, 0)
        glVertex3f(x0, y0, 0)
        glVertex3f(x1, y1, 0)
        glVertex3f(cx, cy, 0)
    glEnd()


# ---- custom dot-matrix font for the notification tile (still no
# glutBitmapCharacter / glRasterPos2f — every letter is a 5x7 grid of
# GL_QUADS rectangles). Text is always shown upper-case. ----

_FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10001", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "01010", "00100", "00100", "00100", "01010", "10001"],
    "Y": ["10001", "01010", "00100", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    ",": ["00000", "00000", "00000", "00000", "00000", "00100", "01000"],
    "'": ["00100", "00100", "00000", "00000", "00000", "00000", "00000"],
}


def draw_char(x_left, y_top, cell, ch, color):
    """Draws one glyph. (x_left, y_top) is the top-left corner of its cell."""
    rows = _FONT_5X7.get(ch.upper(), _FONT_5X7[" "])
    for row_i, row in enumerate(rows):
        for col_i, px in enumerate(row):
            if px == "1":
                dot_cx = x_left + col_i * cell + cell / 2
                dot_cy = y_top - row_i * cell - cell / 2
                draw_2d_rect(dot_cx, dot_cy, cell * 0.9, cell * 0.9, *color)


def draw_string(x_left, y_top, cell, text, color, gap=1):
    cx = x_left
    for ch in text:
        draw_char(cx, y_top, cell, ch, color)
        cx += cell * (5 + gap)
    return cx


def wrap_text(text, max_chars):
    words = text.split(" ")
    lines = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---- icon drawers: each takes the tile's centre (cx, cy) ----

def icon_square(cx, cy):
    draw_2d_rect(cx, cy, 52, 52, 0.96, 0.93, 0.85)


def icon_rectangle(cx, cy):
    draw_2d_rect(cx, cy, 72, 36, 0.96, 0.93, 0.85)


def icon_round(cx, cy):
    draw_2d_circle(cx, cy, 27, 0.96, 0.93, 0.85)


def make_icon_tier(n):
    def _icon(cx, cy):
        if n == 1:
            draw_2d_rect(cx, cy - 4, 52, 38, 0.96, 0.9, 0.78)
        else:
            draw_2d_rect(cx, cy - 16, 58, 30, 0.96, 0.9, 0.78)
            draw_2d_rect(cx, cy + 14, 36, 24, 0.99, 0.95, 0.85)
    return _icon


def icon_topping_none(cx, cy):
    draw_2d_circle(cx, cy, 22, 0.85, 0.85, 0.85)


def icon_topping_cherry(cx, cy):
    draw_2d_circle(cx, cy, 24, 0.96, 0.9, 0.78)
    draw_2d_circle(cx, cy, 13, 0.8, 0.05, 0.15)


def icon_topping_chocobar(cx, cy):
    draw_2d_circle(cx, cy, 24, 0.96, 0.9, 0.78)
    draw_2d_rect(cx, cy, 40, 16, 0.25, 0.12, 0.05)


def icon_police(cx, cy):
    draw_2d_circle(cx, cy, 26, 0.15, 0.35, 0.85)
    draw_2d_rect(cx, cy - 2, 20, 22, 0.9, 0.9, 0.95)


def icon_rps_bundle(cx, cy):
    draw_2d_circle(cx - 20, cy, 12, 0.8, 0.8, 0.82)
    draw_2d_rect(cx, cy, 20, 20, 0.8, 0.8, 0.82)
    icon_scissors_small(cx + 22, cy)


def icon_cake_duel(cx, cy):
    draw_2d_rect(cx, cy - 6, 46, 26, 0.9, 0.85, 0.6)
    draw_2d_circle(cx, cy + 12, 8, 0.8, 0.05, 0.15)


def icon_rock(cx, cy):
    draw_2d_circle(cx, cy, 28, 0.75, 0.75, 0.78)


def icon_paper(cx, cy):
    draw_2d_rect(cx, cy, 52, 52, 0.96, 0.96, 0.9)


def icon_scissors_small(cx, cy):
    draw_2d_circle(cx - 8, cy - 8, 6, 0.7, 0.7, 0.73)
    draw_2d_circle(cx + 8, cy - 8, 6, 0.7, 0.7, 0.73)
    draw_2d_line(cx - 8, cy - 8, cx + 10, cy + 11, 3, 0.55, 0.55, 0.6)
    draw_2d_line(cx + 8, cy - 8, cx - 10, cy + 11, 3, 0.55, 0.55, 0.6)


def icon_scissors(cx, cy):
    draw_2d_circle(cx - 13, cy - 15, 11, 0.75, 0.75, 0.78)
    draw_2d_circle(cx + 13, cy - 15, 11, 0.75, 0.75, 0.78)
    draw_2d_line(cx - 13, cy - 15, cx + 17, cy + 20, 5, 0.6, 0.6, 0.65)
    draw_2d_line(cx + 13, cy - 15, cx - 17, cy + 20, 5, 0.6, 0.6, 0.65)


def draw_tile(index, cx, cy, bg, icon_fn, active=False, digit_color=(0.08, 0.08, 0.08)):
    border = (1.0, 0.85, 0.15) if active else (0.2, 0.15, 0.1)
    draw_2d_rect(cx, cy, TILE_W + 10, TILE_H + 10, *border)
    draw_2d_rect(cx, cy, TILE_W, TILE_H, *bg)
    if icon_fn is not None:
        icon_fn(cx, cy + 20)
    # the "[1]/[2]/[3]" badge is a seven-segment digit, not text
    draw_2d_rect(cx - TILE_W / 2 + 24, cy + TILE_H / 2 - 24, 34, 34, 0.97, 0.97, 0.95)
    draw_digit(cx - TILE_W / 2 + 24, cy + TILE_H / 2 - 24, 16, 24, str(index), digit_color)


def draw_tile_row(tiles, active_index=None):
    """tiles: list of dicts with keys bg, icon, digit_color(optional)."""
    n = len(tiles)
    spacing = TILE_W + 40
    total_w = spacing * (n - 1)
    start_x = WINDOW_W / 2 - total_w / 2
    for i, t in enumerate(tiles):
        cx = start_x + i * spacing
        active = (active_index is not None and active_index == i)
        draw_tile(i + 1, cx, TILE_ROW_CY, t["bg"], t.get("icon"), active,
                  t.get("digit_color", (0.08, 0.08, 0.08)))


def build_shape_tiles():
    return [
        {"bg": (0.55, 0.35, 0.2), "icon": icon_square},
        {"bg": (0.55, 0.35, 0.2), "icon": icon_rectangle},
        {"bg": (0.55, 0.35, 0.2), "icon": icon_round},
    ]


def build_flavor_tiles():
    return [
        {"bg": FLAVORS["vanilla"], "icon": None},
        {"bg": FLAVORS["chocolate"], "icon": None},
        {"bg": FLAVORS["strawberry"], "icon": None},
    ]


def build_tier_tiles():
    return [
        {"bg": (0.55, 0.35, 0.2), "icon": make_icon_tier(1)},
        {"bg": (0.55, 0.35, 0.2), "icon": make_icon_tier(2)},
    ]


def build_topping_tiles():
    return [
        {"bg": (0.55, 0.35, 0.2), "icon": icon_topping_none},
        {"bg": (0.55, 0.35, 0.2), "icon": icon_topping_cherry},
        {"bg": (0.55, 0.35, 0.2), "icon": icon_topping_chocobar},
    ]


def build_robber_tiles():
    return [
        {"bg": (0.75, 0.78, 0.85), "icon": icon_police},
        {"bg": (0.75, 0.78, 0.85), "icon": icon_rps_bundle},
        {"bg": (0.75, 0.78, 0.85), "icon": icon_cake_duel},
    ]


def build_rps_tiles():
    return [
        {"bg": (0.85, 0.85, 0.88), "icon": icon_rock},
        {"bg": (0.85, 0.85, 0.88), "icon": icon_paper},
        {"bg": (0.85, 0.85, 0.88), "icon": icon_scissors},
    ]


def draw_decision_tiles():
    """Chooses which set of 3 (or 2) tiles to show, based on game state."""
    if paused or game_state == STATE_WIN or game_state == STATE_CAKE_EATING:
        return
    if game_state == STATE_NORMAL and order_stage != "taking":
        return  # the player is walking the finished cake to the register

    _begin_2d()
    if game_state == STATE_NORMAL:
        if build_phase == 0:
            draw_tile_row(build_shape_tiles(), active_index=build["shape_idx"])
        elif build_phase == 1:
            draw_tile_row(build_flavor_tiles(), active_index=build["flavor_idx"])
        elif build_phase == 2:
            draw_tile_row(build_tier_tiles(), active_index=build["tiers"] - 1)
        elif build_phase == 3:
            draw_tile_row(build_topping_tiles(), active_index=build["topping_idx"])
    elif game_state == STATE_ROBBER_CHOICE:
        draw_tile_row(build_robber_tiles())
    elif game_state == STATE_RPS:
        draw_tile_row(build_rps_tiles())
    _end_2d()


NOTIF_CX, NOTIF_CY = 830, 610
NOTIF_W, NOTIF_H = 300, 190
NOTIF_MAX_CHARS = 15
NOTIF_CELL = 3


def draw_notification_tile():
    """Speech-bubble-style tile that flashes random customer chatter,
    robber lines, or the order result, in the custom quad font."""
    if not notif_text or (not notif_persistent and notif_timer <= 0):
        return
    _begin_2d()
    draw_2d_rect(NOTIF_CX, NOTIF_CY, NOTIF_W + 10, NOTIF_H + 10, 0.15, 0.12, 0.1)
    draw_2d_rect(NOTIF_CX, NOTIF_CY, NOTIF_W, NOTIF_H, 0.98, 0.97, 0.92)
    draw_2d_rect(NOTIF_CX, NOTIF_CY + NOTIF_H / 2 - 10, NOTIF_W, 18, *notif_color)

    lines = wrap_text(notif_text, NOTIF_MAX_CHARS)[:6]
    line_h = NOTIF_CELL * 9
    total_h = len(lines) * line_h
    start_y = NOTIF_CY + total_h / 2 - NOTIF_CELL * 4
    for i, line in enumerate(lines):
        line_w = len(line) * NOTIF_CELL * 6
        x0 = NOTIF_CX - line_w / 2
        y0 = start_y - i * line_h
        draw_string(x0, y0, NOTIF_CELL, line, (0.1, 0.1, 0.1))
    _end_2d()


# ============================================================
#  GAME LOGIC HELPERS
# ============================================================

def set_message(kind, value=None, frames=500):
    """kind identifies which icon combo draw_hud() flashes; value is an
    optional number shown next to it (e.g. money gained/lost)."""
    global message_kind, message_value, message_timer
    message_kind = kind
    message_value = value
    message_timer = frames


def check_milestones():
    global police_calls, next_milestone
    while money >= next_milestone:
        police_calls += 1
        set_message("milestone", next_milestone, 180)
        next_milestone += 150


# ---- notifications (random chatter / order details, custom quad font) ----

def show_notification(kind):
    global notif_text, notif_color, notif_timer, notif_persistent
    if kind == "customer_line":
        notif_text = random.choice(CUSTOMER_LINES)
        notif_color = (0.65, 0.82, 0.95)
        notif_persistent = True
        notif_timer = 1
    elif kind == "robber":
        notif_text = random.choice(ROBBER_LINES)
        notif_color = (0.75, 0.55, 0.9)
        notif_persistent = False
        notif_timer = NOTIF_DURATION
    elif kind == "order_result_success":
        notif_text = "ORDER DELIVERED SUCCESSFULLY"
        notif_color = (0.2, 0.8, 0.35)
        notif_persistent = False
        notif_timer = ORDER_RESULT_DURATION
    elif kind == "order_result_fail":
        notif_text = "THE ORDER IS UNSUCCESSFUL"
        notif_color = (0.9, 0.25, 0.25)
        notif_persistent = False
        notif_timer = ORDER_RESULT_DURATION


def resume_customer_chatter():
    """Called after a robber encounter ends — if the player was still in
    the middle of taking an order, put the chatter line back up."""
    if order_stage == "taking":
        show_notification("customer_line")


def _lerp_toward(current, target, speed):
    if current < target:
        return min(target, current + speed)
    if current > target:
        return max(target, current - speed)
    return current


# ---- customer queue: purely visual — current_order still drives the
# actual gameplay logic; this just animates bodies through the doors ----

def make_pastel():
    r, g, b = colorsys.hsv_to_rgb(random.random(), 0.35, 0.95)
    return (r, g, b)


def init_customer_queue():
    global customer_queue
    customer_queue = [
        {"x": x, "y": QUEUE_Y, "target_x": x, "target_y": QUEUE_Y, "color": make_pastel()}
        for x in QUEUE_SLOTS_X
    ]


def start_customer_exit(carrying_cake=None):
    """Front customer's order is finished (or refused): they walk out
    through the exit door in the front wall, optionally carrying the cake
    they were just handed. Everyone behind them steps forward and a new
    customer walks in through the entrance door."""
    global customer_queue
    if not customer_queue:
        init_customer_queue()
        return
    front = customer_queue.pop(0)
    front["target_x"] = EXIT_DOOR_X
    front["target_y"] = EXIT_DOOR_Y - 90
    front["carried_cake"] = carrying_cake
    leaving_customers.append(front)
    for i, c in enumerate(customer_queue):
        c["target_x"] = QUEUE_SLOTS_X[i]
        c["target_y"] = QUEUE_Y
    customer_queue.append({
        "x": DOOR_X - 60, "y": QUEUE_Y,
        "target_x": QUEUE_SLOTS_X[-1], "target_y": QUEUE_Y,
        "color": make_pastel(),
    })


def update_customers():
    for c in customer_queue:
        c["x"] = _lerp_toward(c["x"], c["target_x"], CUSTOMER_SPEED)
        c["y"] = _lerp_toward(c.get("y", QUEUE_Y), c["target_y"], CUSTOMER_SPEED)
    for c in leaving_customers[:]:
        c["x"] = _lerp_toward(c["x"], c["target_x"], CUSTOMER_SPEED)
        c["y"] = _lerp_toward(c.get("y", QUEUE_Y), c["target_y"], CUSTOMER_SPEED)
        if c["y"] <= EXIT_DOOR_Y - 80:
            leaving_customers.remove(c)


# ---- robber / police entrance-exit animation through the entrance door ----

def robber_enter():
    global robber_visible, robber_x, robber_target_x
    robber_visible = True
    robber_x = DOOR_X - 60
    robber_target_x = ROBBER_STAND_X


def robber_leave():
    global robber_target_x
    robber_target_x = DOOR_X - 60


def police_enter():
    global police_visible, police_x, police_target_x, police_visit_timer
    police_visible = True
    police_x = DOOR_X - 60
    police_target_x = POLICE_STAND_X
    police_visit_timer = 90


def update_actors():
    global robber_visible, police_visible, police_visit_timer
    global robber_x, police_x, police_target_x

    robber_x = _lerp_toward(robber_x, robber_target_x, 14)
    if robber_visible and robber_target_x <= DOOR_X - 55 and robber_x <= DOOR_X - 55:
        robber_visible = False

    if police_visible:
        police_x = _lerp_toward(police_x, police_target_x, 14)
        if police_visit_timer > 0:
            police_visit_timer -= 1
        else:
            police_target_x = DOOR_X - 60
            if police_x <= DOOR_X - 55:
                police_visible = False


def update_player():
    global player_x, player_y
    player_x = _lerp_toward(player_x, player_target_x, PLAYER_SPEED)
    player_y = _lerp_toward(player_y, player_target_y, PLAYER_SPEED)


def player_arrived():
    return abs(player_x - player_target_x) < 2 and abs(player_y - player_target_y) < 2


def begin_order_taking():
    """Starts a brand new order: fresh current_order, persistent chatter
    line, and the player heads over to the cake table."""
    global current_order, order_stage
    current_order = new_order()
    order_stage = "taking"
    show_notification("customer_line")
    send_player_to(PLAYER_TABLE_POS)


def advance_build_phase():
    global build_phase
    if game_state != STATE_NORMAL or order_stage != "taking":
        return
    if build_phase < 3:
        build_phase += 1
    else:
        submit_cake()


def submit_cake():
    global money, build_phase, build, order_stage, carried_cake

    shape = SHAPES[build["shape_idx"]]
    flavor = FLAVOR_LIST[build["flavor_idx"]]
    tiers = build["tiers"]
    topping = [None, "cherry", "chocobar"][build["topping_idx"]]

    core_match = (
        shape == current_order["shape"]
        and flavor == current_order["flavor"]
        and tiers == current_order["tiers"]
    )
    topping_ok = (current_order["topping"] is None) or (topping == current_order["topping"])

    if core_match and topping_ok:
        base = {"square": 40, "rectangle": 45, "round": 50}[shape]
        reward = int(base * (1.6 if tiers == 2 else 1.0))
        if current_order["topping"] is not None and topping == current_order["topping"]:
            reward += 15
        money += reward
        set_message("success", reward)
        show_notification("order_result_success")
    elif core_match and not topping_ok:
        reward = 10
        money += reward
        set_message("partial", reward)
        show_notification("order_result_success")
    else:
        set_message("fail")
        show_notification("order_result_fail")

    check_milestones()

    carried_cake = {"shape": shape, "flavor": flavor, "tiers": tiers, "topping": topping}
    order_stage = "delivering"
    send_player_to(PLAYER_REGISTER_POS)

    build_phase = 0
    build["shape_idx"] = 0
    build["flavor_idx"] = 0
    build["tiers"] = 1
    build["topping_idx"] = 0


def reset_order():
    """The 'A' key: refuse the current customer outright. They leave empty
    -handed through the exit door and a new customer's order begins."""
    global money
    money = max(0, money - 10)
    set_message("refuse", 10)
    start_customer_exit(carrying_cake=None)
    begin_order_taking()


def spawn_robber():
    global game_state, robber_timer
    game_state = STATE_ROBBER_CHOICE
    robber_timer = ROBBER_TIME_LIMIT
    robber_enter()
    show_notification("robber")


def resolve_robber_timeout():
    global game_state, money
    steal = min(money, random.randint(20, 60))
    money -= steal
    game_state = STATE_NORMAL
    robber_leave()
    set_message("robbed", steal)
    resume_customer_chatter()


def resolve_police_call():
    global game_state, police_calls
    if police_calls > 0:
        police_calls -= 1
        game_state = STATE_NORMAL
        police_enter()
        robber_leave()
        set_message("police_ok")
        resume_customer_chatter()
    else:
        set_message("police_none", frames=90)


def resolve_rps(player_choice):
    global game_state, money
    robber_choice = random.choice(RPS_OPTIONS)
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

    if player_choice == robber_choice:
        set_message("rps_draw", frames=90)
        return  # stay in RPS state for another round

    if beats[player_choice] == robber_choice:
        set_message("rps_win")
        game_state = STATE_NORMAL
        robber_leave()
    else:
        steal = random.randint(20, 50)
        money = max(0, money - steal)
        set_message("rps_lose", steal)
        game_state = STATE_NORMAL
        robber_leave()
    resume_customer_chatter()


def start_cake_duel():
    global game_state, player_cake_amt, robber_cake_amt
    global _saved_orbit_angle, _saved_height, camera_orbit_angle, camera_height
    game_state = STATE_CAKE_EATING
    player_cake_amt = 100.0
    robber_cake_amt = 100.0
    _saved_orbit_angle = camera_orbit_angle
    _saved_height = camera_height
    camera_orbit_angle = 0.0
    camera_height = 260
    # no message needed — the two progress bars are the prompt


def end_cake_duel(player_won):
    global game_state, money, camera_orbit_angle, camera_height
    money = max(0, money - DUEL_CAKE_PRICE)
    if player_won:
        set_message("duel_win")
    else:
        lost = money
        set_message("duel_lose", lost)
        money = 0
    if _saved_orbit_angle is not None:
        camera_orbit_angle = _saved_orbit_angle
        camera_height = _saved_height
    game_state = STATE_NORMAL
    robber_leave()
    resume_customer_chatter()


def reset_game():
    """Wipes every piece of run state back to a fresh game (the 'R' key)."""
    global money, target, police_calls, next_milestone
    global build_phase, build, order_stage, carried_cake, order_handoff_timer
    global message_kind, message_value, message_timer
    global coins, pending_coin_respawns, frame_count, robber_timer, game_state
    global player_cake_amt, robber_cake_amt
    global door_anim, exit_door_anim
    global robber_visible, robber_x, robber_target_x
    global police_visible, police_x, police_target_x, police_visit_timer
    global player_x, player_y
    global leaving_customers, paused

    money = 0
    target = random.randint(400, 700)
    police_calls = 3
    next_milestone = 300

    build_phase = 0
    build = {"shape_idx": 0, "flavor_idx": 0, "tiers": 1, "topping_idx": 0}
    carried_cake = None
    order_handoff_timer = 0

    message_kind = None
    message_value = None
    message_timer = 0

    coins = []
    pending_coin_respawns = []
    frame_count = 0
    robber_timer = 0
    game_state = STATE_NORMAL
    paused = False

    player_cake_amt = 100.0
    robber_cake_amt = 100.0

    door_anim = 1.0
    exit_door_anim = 1.0
    robber_visible = False
    robber_x = DOOR_X
    robber_target_x = DOOR_X
    police_visible = False
    police_x = DOOR_X
    police_target_x = DOOR_X
    police_visit_timer = 0

    leaving_customers = []
    init_customer_queue()

    player_x, player_y = PLAYER_REGISTER_POS
    begin_order_taking()


# ============================================================
#  INPUT CALLBACKS
# ============================================================

def keyboardListener(key, x, y):
    global paused, game_state, player_cake_amt

    if key == b'r':
        reset_game()
        return

    if key == b'p':
        paused = not paused
        return

    if key == b'e':
        os._exit(0)

    if paused or game_state == STATE_WIN:
        return

    if game_state == STATE_NORMAL:
        if order_stage != "taking":
            return
        if key == b'1':
            if build_phase == 0:
                build["shape_idx"] = 0
            elif build_phase == 1:
                build["flavor_idx"] = 0
            elif build_phase == 2:
                build["tiers"] = 1
            elif build_phase == 3:
                build["topping_idx"] = 0
        elif key == b'2':
            if build_phase == 0:
                build["shape_idx"] = 1
            elif build_phase == 1:
                build["flavor_idx"] = 1
            elif build_phase == 2:
                build["tiers"] = 2
            elif build_phase == 3:
                build["topping_idx"] = 1
        elif key == b'3':
            if build_phase == 0:
                build["shape_idx"] = 2
            elif build_phase == 1:
                build["flavor_idx"] = 2
            elif build_phase == 3:
                build["topping_idx"] = 2
        elif key == b'x':
            reset_order()

    elif game_state == STATE_ROBBER_CHOICE:
        if key == b'1':
            resolve_police_call()
        elif key == b'2':
            game_state = STATE_RPS
        elif key == b'3':
            start_cake_duel()

    elif game_state == STATE_RPS:
        choice_map = {b'1': "rock", b'2': "paper", b'3': "scissors"}
        if key in choice_map:
            resolve_rps(choice_map[key])

    elif game_state == STATE_CAKE_EATING:
        if key == b'x':
            player_cake_amt = max(0, player_cake_amt - 12)


def specialKeyListener(key, x, y):
    global camera_orbit_angle, camera_height, player_cake_amt, robber_cake_amt

    if game_state == STATE_WIN:
        return

    if key == GLUT_KEY_LEFT:
        if paused:
            camera_orbit_angle -= ORBIT_SPEED
        elif game_state == STATE_CAKE_EATING:
            return

    elif key == GLUT_KEY_RIGHT:
        if paused:
            camera_orbit_angle += ORBIT_SPEED
        elif game_state == STATE_NORMAL and order_stage == "taking":
            advance_build_phase()

    elif key == GLUT_KEY_UP:
        if paused:
            camera_height = min(HEIGHT_MAX, camera_height + HEIGHT_SPEED)
        elif game_state == STATE_CAKE_EATING:
            robber_cake_amt = min(160, robber_cake_amt + 10)
        else:
            camera_height = min(HEIGHT_MAX, camera_height + HEIGHT_SPEED)

    elif key == GLUT_KEY_DOWN:
        if paused:
            camera_height = max(HEIGHT_MIN, camera_height - HEIGHT_SPEED)
        elif game_state == STATE_CAKE_EATING:
            player_cake_amt = max(0, player_cake_amt - 10)
        else:
            camera_height = max(HEIGHT_MIN, camera_height - HEIGHT_SPEED)


def mouseListener(button, state, x, y):
    global money
    if button == GLUT_LEFT_BUTTON and state == GLUT_DOWN and not paused:
        if coins:
            # so a click just grabs the coin closest to the counter.
            coins.sort(key=lambda c: c["y"])
            coins.pop(0)  # gone immediately — it reappears later, elsewhere
            money_gain = 5
            money += money_gain
            set_message("coin", money_gain, 90)
            check_milestones()
            pending_coin_respawns.append({"timer": COIN_RESPAWN_DELAY})


# ============================================================
#  CAMERA
# ============================================================

def setupCamera():
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(FOVY, WINDOW_W / WINDOW_H, 0.1, 3000)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()

    rad = math.radians(camera_orbit_angle)
    cx = CAMERA_RADIUS * math.cos(rad)
    cy = CAMERA_RADIUS * math.sin(rad) - 200
    cz = camera_height
    gluLookAt(cx, cy, cz, 0, -150, 60, 0, 0, 1)


# ============================================================
#  IDLE / GAME LOOP LOGIC
# ============================================================

def idle():
    global frame_count, game_state, robber_timer
    global player_cake_amt, robber_cake_amt, door_anim, exit_door_anim, notif_timer
    global order_stage, carried_cake, order_handoff_timer

    frame_count += 1

    if not paused:
        update_customers()
        update_actors()
        update_player()

        door_target = 0.0 if game_state == STATE_WIN else 1.0
        door_anim = _lerp_toward(door_anim, door_target, 0.02)
        exit_door_anim = _lerp_toward(exit_door_anim, door_target, 0.02)

        if notif_timer > 0 and not notif_persistent:
            notif_timer -= 1

        # coins waiting to reappear somewhere new
        for entry in pending_coin_respawns[:]:
            entry["timer"] -= 1
            if entry["timer"] <= 0:
                pending_coin_respawns.remove(entry)
                if len(coins) < MAX_COINS:
                    coins.append({
                        "x": random.randint(-450, 450),
                        "y": random.randint(-400, 150),
                    })

        # the player just delivered the cake to the register: keep a longer
        # pause before the next order begins so the handoff feels intentional.
        if order_stage == "delivering" and player_arrived():
            if order_handoff_timer == 0:
                start_customer_exit(carrying_cake=carried_cake)
                carried_cake = None
                order_handoff_timer = ORDER_HANDOFF_DELAY
            else:
                order_handoff_timer -= 1
                if order_handoff_timer <= 0:
                    begin_order_taking()
        elif order_stage == "delivering":
            order_handoff_timer = 0

        if game_state == STATE_NORMAL:
            if frame_count % ROBBER_SPAWN_INTERVAL == 0 and random.random() < ROBBER_SPAWN_CHANCE:
                spawn_robber()
            if frame_count % 220 == 0 and random.random() < 0.6 and len(coins) < MAX_COINS:
                coins.append({
                    "x": random.randint(-450, 450),
                    "y": random.randint(-400, 150),
                })

        elif game_state == STATE_ROBBER_CHOICE:
            robber_timer -= 1
            if frame_count % 200 == 0 and random.random() < 0.4 and notif_timer <= 0:
                show_notification("robber")
            if robber_timer <= 0:
                resolve_robber_timeout()

        elif game_state == STATE_CAKE_EATING:
            robber_cake_amt -= 0.12
            if random.random() < 0.01:
                player_cake_amt = min(160, player_cake_amt + 8)
            if player_cake_amt <= 0:
                end_cake_duel(player_won=True)
            elif robber_cake_amt <= 0:
                end_cake_duel(player_won=False)

        if money >= target and game_state != STATE_WIN:
            game_state = STATE_WIN

    glutPostRedisplay()


# ============================================================
#  HUD  (all icons + seven-segment digits — no text/font calls at all)
# ============================================================

WHITE = (0.95, 0.95, 0.95)
DARK = (0.15, 0.15, 0.15)

# each entry: icon function, colour used for its number/flash
_MESSAGE_ICONS = {
    "milestone": (icon_badge_hud, (0.15, 0.35, 0.85)),
    "success": (icon_check_hud, (0.2, 0.85, 0.25)),
    "partial": (icon_check_hud, (0.9, 0.7, 0.1)),
    "fail": (icon_cross_hud, (0.9, 0.2, 0.2)),
    "robbed": (icon_cross_hud, (0.9, 0.2, 0.2)),
    "police_ok": (icon_badge_hud, (0.15, 0.35, 0.85)),
    "police_none": (icon_cross_hud, (0.6, 0.6, 0.6)),
    "rps_draw": (icon_rps_bundle, (0.6, 0.6, 0.6)),
    "rps_win": (icon_check_hud, (0.2, 0.85, 0.25)),
    "rps_lose": (icon_cross_hud, (0.9, 0.2, 0.2)),
    "duel_win": (icon_check_hud, (0.2, 0.85, 0.25)),
    "duel_lose": (icon_cross_hud, (0.9, 0.2, 0.2)),
    "refuse": (icon_cross_hud, (0.9, 0.55, 0.15)),
    "coin": (icon_coin_hud, (0.9, 0.7, 0.1)),
}


def draw_hud():
    _begin_2d()

    # ---- top-left status row: coin+money, flag+target, badges = police calls
    icon_coin_hud(35, 765)
    draw_number(55, 765, 18, 26, money, DARK)

    icon_flag_hud(230, 765)
    draw_number(255, 765, 18, 26, target, DARK)

    bx = 430
    shown = min(police_calls, 6)
    for i in range(shown):
        icon_badge_hud(bx + i * 26, 765)
    if police_calls > 6:
        draw_number(bx + 6 * 26 + 4, 765, 14, 20, police_calls, DARK)

    # ---- order ticket: what the customer wants, laid out step by step
    # (shape -> flavour -> tiers -> topping) on one big orange tile ----
    ticket_cx, ticket_cy = 130, 690
    TICKET_W, TICKET_H = 260, 100
    draw_2d_rect(ticket_cx, ticket_cy, TICKET_W + 8, TICKET_H + 8, 0.55, 0.28, 0.05)
    draw_2d_rect(ticket_cx, ticket_cy, TICKET_W, TICKET_H, 0.93, 0.88, 0.80)
    slot_w = TICKET_W / 4
    slot_x0 = ticket_cx - TICKET_W / 2 + slot_w / 2
    shape_icons = {"square": icon_square, "rectangle": icon_rectangle, "round": icon_round}
    topping_icons = {None: icon_topping_none, "cherry": icon_topping_cherry, "chocobar": icon_topping_chocobar}
    for i in range(4):
        sx = slot_x0 + i * slot_w
        draw_2d_rect(sx, ticket_cy, slot_w - 8, TICKET_H - 16, 0.55, 0.35, 0.45)
    shape_icons[current_order["shape"]](slot_x0, ticket_cy)
    draw_2d_circle(slot_x0 + slot_w, ticket_cy, 20, *FLAVORS[current_order["flavor"]])
    draw_digit(slot_x0 + slot_w * 2, ticket_cy, 18, 26, str(current_order["tiers"]), DARK)
    topping_icons[current_order["topping"]](slot_x0 + slot_w * 3, ticket_cy)

    # ---- robber countdown as a shrinking, colour-shifting bar ----
    if game_state == STATE_ROBBER_CHOICE:
        frac = robber_timer / ROBBER_TIME_LIMIT
        bar_color = (0.85, 0.2, 0.2) if frac < 0.3 else (0.85, 0.65, 0.15)
        draw_progress_bar(WINDOW_W / 2, 260, 300, 22, frac, color_full=bar_color)

    # ---- cake-eating duel: two progress bars ----
    if game_state == STATE_CAKE_EATING:
        draw_progress_bar(WINDOW_W / 2 - 180, 260, 220, 22, player_cake_amt / 100.0,
                           color_full=(0.2, 0.45, 0.85))
        draw_progress_bar(WINDOW_W / 2 + 180, 260, 220, 22, robber_cake_amt / 100.0,
                           color_full=(0.85, 0.2, 0.2))

    # ---- transient feedback: icon + optional number, bottom-left ----
    if message_timer > 0 and message_kind in _MESSAGE_ICONS:
        icon_fn, color = _MESSAGE_ICONS[message_kind]
        draw_2d_rect(60, 60, 110, 90, 0.98, 0.98, 0.95)
        icon_fn(60, 78)
        if message_value is not None:
            minus = message_kind in ("robbed", "LOST", "refuse", "fail", "duel_lose", "OH!NO!")
            draw_number(30, 42, 12, 18, message_value, color, minus=minus)

    if paused:
        icon_pause_hud(WINDOW_W / 2, WINDOW_H / 2)

    if game_state == STATE_WIN:
        icon_star_hud(WINDOW_W / 2, WINDOW_H / 2, r_out=40, r_in=17)

    _end_2d()


# ============================================================
#  MAIN DISPLAY
# ============================================================

def showScreen():
    global message_timer
    if message_timer > 0:
        message_timer -= 1

    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glLoadIdentity()
    glViewport(0, 0, WINDOW_W, WINDOW_H)

    setupCamera()

    draw_floor()
    draw_environment()
    draw_shop()
    draw_coins()

    # the player shuttles between the register and the cake table, wearing pink
    draw_person(player_x, player_y, PLAYER_COLOR)
    if carried_cake is not None:
        draw_cake(carried_cake["shape"], carried_cake["flavor"], carried_cake["tiers"],
                   carried_cake["topping"], player_x, player_y - 25, base_size=26, z_offset=115)

    # customer queue: several pastel-coloured customers lined up, entering
    # through the left door and (once served) leaving through the front door
    if game_state in (STATE_NORMAL,):
        for c in customer_queue:
            draw_person(c["x"], c.get("y", QUEUE_Y), c["color"])
    for c in leaving_customers:
        draw_person(c["x"], c.get("y", QUEUE_Y), c["color"])
        cake = c.get("carried_cake")
        if cake is not None:
            draw_cake(cake["shape"], cake["flavor"], cake["tiers"], cake["topping"],
                       c["x"], c.get("y", QUEUE_Y) - 25, base_size=26, z_offset=115)

    # robber (violet) and police (dark green), animated in/out through the entrance door
    if robber_visible:
        draw_person(robber_x, QUEUE_Y, ROBBER_COLOR)
    if police_visible:
        draw_person(police_x, QUEUE_Y, POLICE_COLOR)

    if game_state == STATE_CAKE_EATING:
        # duel cakes (shrink as they're eaten) — left is the player's, right the robber's
        draw_cake("round", "chocolate", 1, None, -180, -100,
                  base_size=max(20, player_cake_amt * 0.8))
        draw_cake("round", "strawberry", 1, None, 180, -100,
                  base_size=max(20, robber_cake_amt * 0.8))
        draw_person(-180, -260, PLAYER_COLOR)
        draw_person(180, -260, ROBBER_COLOR)
    elif order_stage == "taking":
        # reference cake for the order, on a little tray right beside
        # whichever customer is currently at the front of the queue
        front = customer_queue[0] if customer_queue else None
        front_x = front["x"] if front else QUEUE_SLOTS_X[0]
        front_y = front.get("y", QUEUE_Y) if front else QUEUE_Y
        glColor3f(0.55, 0.4, 0.25)
        glPushMatrix()
        glTranslatef(front_x + 65, front_y + 10, 8)
        glScalef(1.0, 1.0, 0.2)
        glutSolidCube(70)
        glPopMatrix()
        draw_cake(current_order["shape"], current_order["flavor"], current_order["tiers"],
                  current_order["topping"], front_x + 65, front_y + 10, base_size=45)

        # the cake the player is currently assembling, on its table
        draw_cake(SHAPES[build["shape_idx"]], FLAVOR_LIST[build["flavor_idx"]],
                   build["tiers"], [None, "cherry", "chocobar"][build["topping_idx"]],
                   280, 60)

    draw_hud()
    draw_decision_tiles()
    draw_notification_tile()

    glutSwapBuffers()


# ============================================================
#  MAIN
# ============================================================

def main():
    init_customer_queue()
    begin_order_taking()

    glutInit()
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)
    glutInitWindowSize(WINDOW_W, WINDOW_H)
    glutInitWindowPosition(0, 0)
    glutCreateWindow(b"Baker's Legacy")

    glutDisplayFunc(showScreen)
    glutKeyboardFunc(keyboardListener)
    glutSpecialFunc(specialKeyListener)
    glutMouseFunc(mouseListener)
    glutIdleFunc(idle)

    glutMainLoop()


if __name__ == "__main__":
    main()