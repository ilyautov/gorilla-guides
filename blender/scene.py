#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scene.py — оранжевый кубик-робот с экраном-лицом прыгает по трём крышам
низкополигонального ночного города, камера ведёт его сбоку, на три четверти
спереди, чтобы экран-лицо был виден.

Запуск (Blender 5.4, без интерфейса):

  Blender -b --factory-startup --python scene.py -- \
      --variant blockout|final --out <папка> [--start N --end N] [--scale 100]

  blockout — серый блокаут, Workbench, те же формы, без материалов.
  final    — EEVEE, материалы, ночное небо, свет, туман, неон без текста.

8 с, 30 fps (кадры 1–240), 1080×720, PNG-кадры <out>/0001.png … 0240.png.
Никаких внешних файлов и сети: вся геометрия, материалы и небо строятся кодом.
Скрипт пишет только в папку --out.

Анимация робота и камеры задана ОДНИМ блоком (раздел «1. АНИМАЦИЯ») и
одинакова в обоих вариантах; варианты меняют только внешний вид.
"""

import argparse
import math
import os
import random
import sys

import bpy
from mathutils import Vector

# ---------------------------------------------------------------------------
# 0. Константы сцены
# ---------------------------------------------------------------------------
FPS = 30
FRAME_START = 1
FRAME_END = 240
RES_X, RES_Y = 1080, 720
SEED = 20261027  # детерминированный город

# ---------------------------------------------------------------------------
# 1. АНИМАЦИЯ — единственное место, где задано движение робота и камеры
# ---------------------------------------------------------------------------

# Крыши, по которым идёт маршрут: (x, y, ширина по x, глубина по y, высота).
# Робот стартует на крыше 0 и делает три прыжка: 0→1, 1→2, 2→3.
ROOFS = [
    (0.0, 0.0, 5.0, 5.0, 10.0),
    (7.0, 0.3, 5.0, 5.0, 9.0),
    (14.0, -0.2, 5.0, 5.0, 11.0),
    (21.0, 0.2, 5.0, 5.0, 10.0),
]
N_JUMPS = 3

# Хронометраж в кадрах (0-based от начала ролика).
IDLE_IN = 14                      # робот стоит, дышит
T_CROUCH = 12                     # присед перед прыжком
T_AIR = 30                        # полёт
T_SQUASH = 8                      # сжатие при приземлении
T_RECOVER = 8                     # отскок обратно в форму
T_WALK = 14                       # перебежка к краю следующей крыши
T_JUMP = T_CROUCH + T_AIR + T_SQUASH + T_RECOVER + T_WALK   # 72
# 14 + 3*72 = 230, остаток 10 кадров — робот стоит на последней крыше.

EDGE = 1.6        # точка отрыва/приземления: отступ от центра крыши по x
APEX = 2.0        # подъём дуги над прямой между точками отрыва и приземления
CROUCH_DEPTH = 0.32
SQUASH_DEPTH = 0.40
BLINK_FRAMES = (48, 132, 205)     # моргание экрана

# Камера: смещение от сглаженной позиции робота и точка прицела.
# Робот смотрит в +X; камера сбоку (-Y) и спереди (+X) — три четверти спереди,
# экран-лицо видно. Дистанция ≈8 м при 35 мм даёт высоту кадра ≈5.5 м,
# робот (≈1.5 м) занимает около четверти высоты кадра.
CAM_OFFSET = Vector((5.4, -5.4, 2.6))
CAM_AIM = Vector((0.0, 0.0, 0.8))        # на уровень груди
CAM_SMOOTH_SIGMA = 6.0                   # гауссово сглаживание пути, кадры
CAM_AIM_RAW_MIX = 0.4                    # доля «сырой» позиции в прицеле
CAM_LENS = 35.0


def smoothstep(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3.0 - 2.0 * u)


def roof_top(k):
    x, y, _w, _d, h = ROOFS[k]
    return Vector((x, y, h))


def takeoff_point(k):
    p = roof_top(k)
    p.x += EDGE
    return p


def landing_point(k):
    p = roof_top(k + 1)
    p.x -= EDGE
    return p


def walk_end_point(k):
    p = roof_top(k + 1)
    if k + 1 < N_JUMPS:
        p.x += EDGE       # к краю следующей крыши — это точка отрыва k+1
    return p              # после последнего прыжка — в центр крыши


def robot_pose(frame):
    """(location, scale, наклон вокруг Y) робота для кадра 1..240."""
    t = frame - FRAME_START
    breathe = 1.0 + 0.015 * math.sin(t / FPS * 2 * math.pi * 0.8)

    if t < IDLE_IN:
        return takeoff_point(0), Vector((1.0, 1.0, breathe)), 0.0

    j = t - IDLE_IN
    if j >= N_JUMPS * T_JUMP:
        return walk_end_point(N_JUMPS - 1), Vector((1.0, 1.0, breathe)), 0.0

    k = j // T_JUMP
    s = j - k * T_JUMP
    P, L, W = takeoff_point(k), landing_point(k), walk_end_point(k)

    # --- присед ---
    if s < T_CROUCH:
        u = s / T_CROUCH
        if u < 0.75:
            c = smoothstep(u / 0.75)            # медленно вниз
        else:
            c = 1.0 - smoothstep((u - 0.75) / 0.25)   # резко выпрямляется
        sz = 1.0 - CROUCH_DEPTH * c
        sxy = 1.0 / math.sqrt(sz)
        return P, Vector((sxy, sxy, sz)), -0.10 * c
    s -= T_CROUCH

    # --- полёт ---
    if s < T_AIR:
        u = s / T_AIR
        pos = P.lerp(L, u)
        pos.z += APEX * 4.0 * u * (1.0 - u)
        stretch = 0.28 * max(0.0, 1.0 - u / 0.4)          # вытянут на отрыве
        stretch += 0.12 * max(0.0, (u - 0.8) / 0.2)       # вытянут перед касанием
        sz = 1.0 + stretch
        sxy = 1.0 / math.sqrt(sz)
        return pos, Vector((sxy, sxy, sz)), 0.35 * math.sin(math.pi * u)
    s -= T_AIR

    # --- сжатие при приземлении ---
    if s < T_SQUASH:
        u = s / T_SQUASH
        sz = 1.0 - SQUASH_DEPTH * math.sin(math.pi * u)
        sxy = 1.0 / math.sqrt(sz)
        return L, Vector((sxy, sxy, sz)), 0.12 * (1.0 - u)
    s -= T_SQUASH

    # --- отскок в форму ---
    if s < T_RECOVER:
        u = s / T_RECOVER
        sz = 1.0 + 0.08 * math.sin(math.pi * u)
        sxy = 1.0 / math.sqrt(sz)
        return L, Vector((sxy, sxy, sz)), 0.0
    s -= T_RECOVER

    # --- перебежка ---
    u = s / T_WALK
    pos = L.lerp(W, smoothstep(u))
    pos.z += 0.07 * abs(math.sin(u * math.pi * 3.0))
    return pos, Vector((1.0, 1.0, 1.0)), 0.06 * math.sin(u * math.pi * 6.0)


def camera_path():
    """Список (позиция камеры, точка прицела) на каждый кадр 1..240."""
    frames = list(range(FRAME_START, FRAME_END + 1))
    raw = [robot_pose(f)[0] for f in frames]
    n = len(raw)
    r = int(3 * CAM_SMOOTH_SIGMA)
    weights = [math.exp(-(d * d) / (2 * CAM_SMOOTH_SIGMA ** 2)) for d in range(-r, r + 1)]
    smooth = []
    for i in range(n):
        acc = Vector((0.0, 0.0, 0.0))
        wsum = 0.0
        for d, w in zip(range(-r, r + 1), weights):
            j = min(n - 1, max(0, i + d))
            acc += raw[j] * w
            wsum += w
        smooth.append(acc / wsum)
    out = []
    for i in range(n):
        cam = smooth[i] + CAM_OFFSET
        aim = smooth[i].lerp(raw[i], CAM_AIM_RAW_MIX) + CAM_AIM
        out.append((cam, aim))
    return out


def animate(robot_root, rig, cam, cam_target, eyes):
    """Ключует робота, световой риг, камеру и моргание. Одинаково для обоих вариантов.

    rig — пустышка, едущая за роботом без сжатия/наклона; к ней в финале
    цепляются ключевой и контровой свет.
    """
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    except Exception:
        pass

    path = camera_path()
    for i, f in enumerate(range(FRAME_START, FRAME_END + 1)):
        loc, scl, rot_y = robot_pose(f)
        robot_root.location = loc
        robot_root.scale = scl
        robot_root.rotation_euler = (0.0, rot_y, 0.0)
        robot_root.keyframe_insert("location", frame=f)
        robot_root.keyframe_insert("scale", frame=f)
        robot_root.keyframe_insert("rotation_euler", frame=f)
        rig.location = loc
        rig.keyframe_insert("location", frame=f)

        cam_pos, aim = path[i]
        cam.location = cam_pos
        cam.keyframe_insert("location", frame=f)
        cam_target.location = aim
        cam_target.keyframe_insert("location", frame=f)

    # Моргание: экран-глаза схлопываются по z.
    for eye in eyes:
        eye.scale = (1.0, 1.0, 1.0)
        eye.keyframe_insert("scale", frame=FRAME_START)
        for b in BLINK_FRAMES:
            for df, sz in ((-3, 1.0), (0, 0.08), (3, 1.0)):
                eye.scale = (1.0, 1.0, sz)
                eye.keyframe_insert("scale", frame=b + df)

    for ob in (robot_root, rig, cam, cam_target, *eyes):
        _set_linear(ob)


def _set_linear(ob):
    ad = ob.animation_data
    if not ad or not ad.action:
        return
    try:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
    except Exception:
        pass  # в новых версиях достаточно настройки preferences выше


# ---------------------------------------------------------------------------
# 2. Геометрия (общая для обоих вариантов) — только кубы и цилиндры
# ---------------------------------------------------------------------------

def _box_data(center, size, v0=0):
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    verts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    return verts, [tuple(i + v0 for i in f) for f in faces]


def _cyl_data(center, radius, height, v0=0, n=12):
    cx, cy, cz = center
    verts, faces = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), cz))
    for k in range(n):
        a = 2 * math.pi * k / n
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), cz + height))
    for k in range(n):
        k2 = (k + 1) % n
        faces.append((v0 + k, v0 + k2, v0 + n + k2, v0 + n + k))
    faces.append(tuple(v0 + k for k in reversed(range(n))))        # дно
    faces.append(tuple(v0 + n + k for k in range(n)))               # крышка
    return verts, faces


def make_mesh_object(name, parts, location=(0, 0, 0), parent=None, collection=None):
    """parts: список ('box', center, size) | ('cyl', center, radius, height)."""
    verts, faces = [], []
    for p in parts:
        if p[0] == 'box':
            v, f = _box_data(p[1], p[2], len(verts))
        else:
            v, f = _cyl_data(p[1], p[2], p[3], len(verts))
        verts += v
        faces += f
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    if parent is not None:
        ob.parent = parent
    (collection or bpy.context.scene.collection).objects.link(ob)
    return ob


def box(name, size, location, base=True, parent=None):
    """Коробка; base=True — начало координат в центре нижней грани."""
    cz = size[2] / 2.0 if base else 0.0
    return make_mesh_object(name, [('box', (0, 0, cz), size)], location, parent)


def build_robot():
    """Возвращает (корень, список глаз, словарь частей для материалов)."""
    root = bpy.data.objects.new("Robot", None)
    root.empty_display_type = 'CUBE'
    root.empty_display_size = 0.3
    bpy.context.scene.collection.objects.link(root)

    parts = {}
    # Корпус: куб 1×0.9×1 на «ножках», смотрит в +X.
    parts['body'] = box("Robot_Body", (1.0, 0.9, 1.0), (0, 0, 0.35), parent=root)
    parts['legs'] = make_mesh_object("Robot_Legs", [
        ('box', (0.0, -0.25, 0.175), (0.24, 0.24, 0.35)),
        ('box', (0.0, 0.25, 0.175), (0.24, 0.24, 0.35)),
    ], parent=root)
    parts['arms'] = make_mesh_object("Robot_Arms", [
        ('box', (0.0, -0.57, 0.85), (0.2, 0.2, 0.6)),
        ('box', (0.0, 0.57, 0.85), (0.2, 0.2, 0.6)),
    ], parent=root)
    # Экран-лицо на передней грани.
    parts['screen'] = make_mesh_object("Robot_Screen", [
        ('box', (0.51, 0.0, 0.85), (0.06, 0.72, 0.56)),
    ], parent=root)
    eyes = [
        make_mesh_object("Robot_EyeL", [('box', (0.55, -0.17, 0.87), (0.03, 0.15, 0.17))], parent=root),
        make_mesh_object("Robot_EyeR", [('box', (0.55, 0.17, 0.87), (0.03, 0.15, 0.17))], parent=root),
    ]
    parts['eyes'] = eyes
    parts['antenna'] = make_mesh_object("Robot_Antenna", [
        ('cyl', (-0.2, 0.0, 1.35), 0.04, 0.3),
    ], parent=root)
    parts['antenna_tip'] = make_mesh_object("Robot_AntennaTip", [
        ('box', (-0.2, 0.0, 1.72), (0.14, 0.14, 0.14)),
    ], parent=root)
    return root, eyes, parts


def build_city(rng):
    """Город. Возвращает словарь групп объектов и описаний вывесок."""
    city = {'buildings': [], 'roofs': [], 'props': [], 'signs': [], 'aabb': []}

    city['ground'] = box("Ground", (260.0, 260.0, 0.2), (10.0, 0.0, -0.2))

    # Основной ряд крыш.
    for k, (x, y, w, d, h) in enumerate(ROOFS):
        b = box(f"Roof{k}", (w, d, h), (x, y, 0.0))
        city['roofs'].append(b)
        city['aabb'].append((x - w / 2, x + w / 2, y - d / 2, y + d / 2, h))
        # Парапет по периметру (0.25 ширина, 0.3 высота).
        p = 0.25
        parapet = make_mesh_object(f"Roof{k}_Parapet", [
            ('box', (0.0, -d / 2 + p / 2, h + 0.15), (w, p, 0.3)),
            ('box', (0.0, d / 2 - p / 2, h + 0.15), (w, p, 0.3)),
            ('box', (-w / 2 + p / 2, 0.0, h + 0.15), (p, d, 0.3)),
            ('box', (w / 2 - p / 2, 0.0, h + 0.15), (p, d, 0.3)),
        ], (x, y, 0.0))
        city['props'].append(parapet)
        # Крышная мелочь в стороне от маршрута робота (маршрут идёт по y≈0).
        side = -1.0 if rng.random() < 0.5 else 1.0
        props = [
            ('box', (rng.uniform(-1.4, 1.4), side * 1.7, h + 0.3), (0.8, 0.7, 0.6)),
            ('cyl', (rng.uniform(-1.6, 1.6), -side * 1.75, h), 0.35, rng.uniform(0.8, 1.4)),
        ]
        city['props'].append(make_mesh_object(f"Roof{k}_Props", props, (x, y, 0.0)))

    # Заполняющие здания: случайно, без пересечений, с зонами ограничений.
    def allowed(x0, x1, y0, y1):
        # не трогаем ряд крыш
        if x1 > -6.0 and x0 < 28.0 and y1 > -4.5 and y0 < 4.5:
            return None
        for (ax0, ax1, ay0, ay1, _h) in city['aabb']:
            if x1 + 1.2 > ax0 and x0 - 1.2 < ax1 and y1 + 1.2 > ay0 and y0 - 1.2 < ay1:
                return None
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if -14.0 <= cy <= -4.5 and -12.0 <= cx <= 34.0:
            return 'corridor'       # коридор камеры: только низкие
        if cy > 4.5:
            return 'far'            # дальний план: высокие
        return 'other'

    placed = 0
    attempts = 0
    while placed < 75 and attempts < 1200:
        attempts += 1
        w = rng.uniform(3.0, 7.5)
        d = rng.uniform(3.0, 7.5)
        x = rng.uniform(-30.0, 50.0)
        y = rng.uniform(-36.0, 38.0)
        zone = allowed(x - w / 2, x + w / 2, y - d / 2, y + d / 2)
        if zone is None:
            continue
        if zone == 'corridor':
            h = rng.uniform(2.5, 5.0)
        elif zone == 'far':
            h = rng.uniform(6.0, 20.0) if rng.random() < 0.8 else rng.uniform(20.0, 28.0)
        else:
            h = rng.uniform(4.0, 14.0)
        b = box(f"Bld{placed:02d}", (w, d, h), (x, y, 0.0))
        city['buildings'].append(b)
        city['aabb'].append((x - w / 2, x + w / 2, y - d / 2, y + d / 2, h))
        placed += 1

        # Вывески на грани, обращённой к камере (-Y), без текста: полосы и рамки.
        if zone in ('far', 'corridor') and rng.random() < 0.55 and h > 3.0:
            _add_sign(city, rng, x, y - d / 2, w, h, name=f"Sign{len(city['signs']):02d}")

    # Вывески на фасадах крыш основного ряда (сторона камеры).
    for k, (x, y, w, d, h) in enumerate(ROOFS):
        for _ in range(rng.randint(1, 2)):
            _add_sign(city, rng, x, y - d / 2, w, h, name=f"Sign{len(city['signs']):02d}")

    return city


SIGN_PALETTE = [
    (1.0, 0.10, 0.50),   # маджента
    (0.10, 0.90, 1.00),  # циан
    (0.85, 1.00, 0.20),  # лайм
    (1.00, 0.45, 0.10),  # янтарь
    (0.60, 0.30, 1.00),  # фиолет
]


def _add_sign(city, rng, bx, face_y, bw, bh, name):
    """Неоновая вывеска на грани y=face_y здания; формы — полосы и рамки."""
    kind = rng.choice(['hbar', 'vbar', 'frame', 'stack'])
    thick = 0.12
    cy = face_y - thick / 2 - 0.02
    z = rng.uniform(2.5, max(2.6, bh - 1.5))
    cx = bx + rng.uniform(-bw * 0.3, bw * 0.3)
    parts = []
    if kind == 'hbar':
        w, h = rng.uniform(1.6, min(3.6, bw * 0.8)), rng.uniform(0.3, 0.55)
        parts.append(('box', (0.0, 0.0, 0.0), (w, thick, h)))
    elif kind == 'vbar':
        w, h = rng.uniform(0.3, 0.5), rng.uniform(1.8, min(3.5, bh * 0.5))
        parts.append(('box', (0.0, 0.0, 0.0), (w, thick, h)))
    elif kind == 'frame':
        w, h = rng.uniform(1.4, min(3.0, bw * 0.7)), rng.uniform(1.0, 1.8)
        t = 0.14
        parts += [
            ('box', (0.0, 0.0, h / 2 - t / 2), (w, thick, t)),
            ('box', (0.0, 0.0, -h / 2 + t / 2), (w, thick, t)),
            ('box', (-w / 2 + t / 2, 0.0, 0.0), (t, thick, h)),
            ('box', (w / 2 - t / 2, 0.0, 0.0), (t, thick, h)),
        ]
    else:  # три короткие полосы столбиком
        w = rng.uniform(1.0, 2.0)
        for i in range(3):
            parts.append(('box', (0.0, 0.0, (i - 1) * 0.5), (w * rng.uniform(0.6, 1.0), thick, 0.22)))
    ob = make_mesh_object(name, parts, (cx, cy, z))
    color = rng.randrange(len(SIGN_PALETTE))
    city['signs'].append({'obj': ob, 'color': color, 'pos': Vector((cx, cy, z))})


def build_camera():
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = CAM_LENS
    cam_data.sensor_fit = 'HORIZONTAL'
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 600.0
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    target = bpy.data.objects.new("CamTarget", None)
    target.empty_display_type = 'SPHERE'
    target.empty_display_size = 0.2
    bpy.context.scene.collection.objects.link(target)

    c = cam.constraints.new('TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    bpy.context.scene.camera = cam
    return cam, target


# ---------------------------------------------------------------------------
# 3. Внешний вид — blockout
# ---------------------------------------------------------------------------

def setopt(obj, name, value):
    """Безопасно выставить свойство (имена между версиями Blender плавают)."""
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False


def set_engine(scene, candidates):
    for c in candidates:
        try:
            scene.render.engine = c
            return c
        except Exception:
            continue
    raise RuntimeError(f"Не найден движок из {candidates}")


def look_blockout(scene):
    set_engine(scene, ['BLENDER_WORKBENCH'])
    sh = scene.display.shading
    setopt(sh, 'light', 'STUDIO')
    setopt(sh, 'color_type', 'SINGLE')
    setopt(sh, 'single_color', (0.55, 0.55, 0.55))
    setopt(sh, 'show_shadows', True)
    setopt(sh, 'shadow_intensity', 0.45)
    setopt(sh, 'show_cavity', True)
    setopt(sh, 'cavity_type', 'BOTH')
    setopt(sh, 'show_object_outline', True)
    setopt(sh, 'show_specular_highlight', False)
    setopt(sh, 'background_type', 'WORLD')
    setopt(scene.display, 'render_aa', '8')
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = False
    world.color = (0.16, 0.16, 0.16)
    try:
        scene.view_settings.view_transform = 'Standard'
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 4. Внешний вид — final (EEVEE)
# ---------------------------------------------------------------------------

def new_material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return m, nt


def warn(msg):
    print(f"[scene.py] предупреждение: {msg}")


def sock(sockets, key):
    """Сокет по identifier, имени или индексу; None, если такого нет.

    Имена сокетов между версиями Blender плавают (например, у Mix все входы
    называются A/B, различаются только identifier: A_Color, B_Float …), поэтому
    сначала ищем по identifier, затем по имени, затем по индексу.
    """
    if isinstance(key, int):
        return sockets[key] if 0 <= key < len(sockets) else None
    for s in sockets:
        if s.identifier == key:
            return s
    for s in sockets:
        if s.name == key:
            return s
    return None


def node(nt, type_, props=None, inputs=None):
    """Создать узел. type_ — id или кортеж кандидатов (старое/новое имя)."""
    candidates = (type_,) if isinstance(type_, str) else tuple(type_)
    n = None
    for cand in candidates:
        try:
            n = nt.nodes.new(cand)
            break
        except RuntimeError:
            continue
    if n is None:
        raise RuntimeError(f"Нет узла ни с одним из имён {candidates}")
    for k, v in (props or {}).items():
        if not setopt(n, k, v):
            warn(f"{n.bl_idname}: свойство {k}={v!r} не принято")
    for k, v in (inputs or {}).items():
        s = sock(n.inputs, k)
        if s is None:
            warn(f"{n.bl_idname}: нет входа {k!r}; есть {[i.identifier for i in n.inputs]}")
            continue
        try:
            s.default_value = v
        except Exception as exc:  # noqa: BLE001
            warn(f"{n.bl_idname}: вход {k!r} не принял {v!r}: {exc}")
    return n


def link(nt, a, ao, b, bi):
    so = sock(a.outputs, ao)
    si = sock(b.inputs, bi)
    if so is None:
        warn(f"{a.bl_idname}: нет выхода {ao!r}; есть {[o.identifier for o in a.outputs]}")
        return
    if si is None:
        warn(f"{b.bl_idname}: нет входа {bi!r}; есть {[i.identifier for i in b.inputs]}")
        return
    nt.links.new(so, si)


def mathn(nt, op, *ins, clamp=False):
    """Math-узел; аргументы — число или (узел, выход)."""
    n = node(nt, 'ShaderNodeMath', props={'operation': op, 'use_clamp': clamp})
    for i, v in enumerate(ins):
        if v is None:
            continue
        if isinstance(v, tuple):
            link(nt, v[0], v[1], n, i)
        else:
            n.inputs[i].default_value = v
    return n


def mix_rgb(nt, a, b, fac, blend='MIX'):
    """Mix (цвет). a, b, fac — цвет/число или (узел, выход). Выход: 'Result_Color'."""
    n = node(nt, ('ShaderNodeMix', 'ShaderNodeMixRGB'),
             props={'data_type': 'RGBA', 'blend_type': blend})
    for key, legacy, val in (('A_Color', 'Color1', a), ('B_Color', 'Color2', b),
                             ('Factor_Float', 'Fac', fac)):
        if isinstance(val, tuple) and len(val) == 2 and hasattr(val[0], 'outputs'):
            if sock(n.inputs, key) is not None:
                link(nt, val[0], val[1], n, key)
            else:
                link(nt, val[0], val[1], n, legacy)
        else:
            s = sock(n.inputs, key) or sock(n.inputs, legacy)
            if s is None:
                warn(f"{n.bl_idname}: нет входа {key}/{legacy}")
            elif isinstance(val, (int, float)):
                s.default_value = val
            else:
                s.default_value = (*val[:3], 1.0)
    return n


def mix_out(n):
    """Имя выхода Mix: 'Result_Color' у ShaderNodeMix, 'Color' у старого MixRGB."""
    return 'Result_Color' if sock(n.outputs, 'Result_Color') is not None else 'Color'


def mat_simple(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0):
    m, nt = new_material(name)
    out = node(nt, 'ShaderNodeOutputMaterial')
    inputs = {'Base Color': (*color, 1.0), 'Roughness': rough, 'Metallic': metal}
    if emit is not None:
        inputs['Emission Color'] = (*emit, 1.0)
        inputs['Emission Strength'] = emit_strength
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', inputs=inputs)
    link(nt, bsdf, 'BSDF', out, 'Surface')
    return m


def mat_emission(name, color, strength):
    m, nt = new_material(name)
    out = node(nt, 'ShaderNodeOutputMaterial')
    em = node(nt, 'ShaderNodeEmission', inputs={'Color': (*color, 1.0), 'Strength': strength})
    link(nt, em, 'Emission', out, 'Surface')
    return m


def mat_building(name, lit_threshold=0.82, emit_strength=0.8):
    """Тёмный фасад с процедурной сеткой окон; светится ~18 % окон, тускло."""
    m, nt = new_material(name)
    out = node(nt, 'ShaderNodeOutputMaterial')
    tc = node(nt, 'ShaderNodeTexCoord')
    sep = node(nt, 'ShaderNodeSeparateXYZ')
    link(nt, tc, 'Object', sep, 'Vector')          # меш построен в метрах → Object = метры
    geo = node(nt, 'ShaderNodeNewGeometry')
    nsep = node(nt, 'ShaderNodeSeparateXYZ')
    link(nt, geo, 'Normal', nsep, 'Vector')
    anx = mathn(nt, 'ABSOLUTE', (nsep, 'X'))
    anz = mathn(nt, 'ABSOLUTE', (nsep, 'Z'))

    # Горизонтальная координата вдоль фасада: x на гранях ±Y, y на гранях ±X.
    dxy = mathn(nt, 'SUBTRACT', (sep, 'Y'), (sep, 'X'))
    hcoord = mathn(nt, 'MULTIPLY_ADD', (anx, 0), (dxy, 0), (sep, 'X'))
    hs = mathn(nt, 'MULTIPLY', (hcoord, 0), 1.0 / 1.5)
    zs = mathn(nt, 'MULTIPLY_ADD', (sep, 'Z'), 1.0 / 1.15, 0.3)
    u = mathn(nt, 'FRACT', (hs, 0))
    v = mathn(nt, 'FRACT', (zs, 0))
    iu = mathn(nt, 'FLOOR', (hs, 0))
    iv = mathn(nt, 'FLOOR', (zs, 0))

    inside = mathn(nt, 'MULTIPLY',
                   (mathn(nt, 'GREATER_THAN', (u, 0), 0.26), 0),
                   (mathn(nt, 'LESS_THAN', (u, 0), 0.74), 0))
    inside = mathn(nt, 'MULTIPLY', (inside, 0), (mathn(nt, 'GREATER_THAN', (v, 0), 0.22), 0))
    inside = mathn(nt, 'MULTIPLY', (inside, 0), (mathn(nt, 'LESS_THAN', (v, 0), 0.72), 0))
    side = mathn(nt, 'LESS_THAN', (anz, 0), 0.5)      # крыша без окон
    inside = mathn(nt, 'MULTIPLY', (inside, 0), (side, 0))

    oi = node(nt, 'ShaderNodeObjectInfo')
    seed = mathn(nt, 'MULTIPLY', (oi, 'Random'), 97.0)
    cell = node(nt, 'ShaderNodeCombineXYZ')
    link(nt, iu, 0, cell, 'X')
    link(nt, iv, 0, cell, 'Y')
    link(nt, seed, 0, cell, 'Z')
    wn = node(nt, 'ShaderNodeTexWhiteNoise', props={'noise_dimensions': '3D'})
    link(nt, cell, 'Vector', wn, 'Vector')
    lit = mathn(nt, 'GREATER_THAN', (wn, 'Value'), lit_threshold)

    seed2 = mathn(nt, 'ADD', (seed, 0), 0.37)
    cell2 = node(nt, 'ShaderNodeCombineXYZ')
    link(nt, iu, 0, cell2, 'X')
    link(nt, iv, 0, cell2, 'Y')
    link(nt, seed2, 0, cell2, 'Z')
    wn2 = node(nt, 'ShaderNodeTexWhiteNoise', props={'noise_dimensions': '3D'})
    link(nt, cell2, 'Vector', wn2, 'Vector')
    warm = mathn(nt, 'GREATER_THAN', (wn2, 'Value'), 0.55)

    # Холодные окна / тёплые окна по второму шуму.
    mix = mix_rgb(nt, (0.55, 0.75, 1.0), (1.0, 0.72, 0.38), (warm, 0))

    strength = mathn(nt, 'MULTIPLY', (inside, 0), (lit, 0))
    strength = mathn(nt, 'MULTIPLY', (strength, 0), emit_strength)

    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', inputs={
        'Base Color': (0.035, 0.04, 0.06, 1.0), 'Roughness': 0.8, 'Metallic': 0.0,
    })
    link(nt, mix, mix_out(mix), bsdf, 'Emission Color')
    link(nt, strength, 0, bsdf, 'Emission Strength')
    link(nt, bsdf, 'BSDF', out, 'Surface')
    return m


FOG_H = 24.0


def mat_fog():
    """Туман: плотнее у земли, сходит на нет к высоте FOG_H."""
    m, nt = new_material("Fog")
    out = node(nt, 'ShaderNodeOutputMaterial')
    tc = node(nt, 'ShaderNodeTexCoord')
    sep = node(nt, 'ShaderNodeSeparateXYZ')
    link(nt, tc, 'Object', sep, 'Vector')
    t = mathn(nt, 'MULTIPLY', (sep, 'Z'), 1.0 / FOG_H, clamp=True)
    inv = mathn(nt, 'SUBTRACT', 1.0, (t, 0))
    p = mathn(nt, 'POWER', (inv, 0), 2.2)
    dens = mathn(nt, 'MULTIPLY', (p, 0), 0.045)
    vol = node(nt, 'ShaderNodeVolumePrincipled', inputs={
        'Color': (0.6, 0.7, 0.9, 1.0), 'Anisotropy': 0.25,
    })
    link(nt, dens, 0, vol, 'Density')
    link(nt, vol, 'Volume', out, 'Volume')
    return m


def world_night(scene):
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, 'ShaderNodeOutputWorld')
    bg = node(nt, 'ShaderNodeBackground', inputs={'Strength': 1.0})
    tc = node(nt, 'ShaderNodeTexCoord')
    sep = node(nt, 'ShaderNodeSeparateXYZ')
    link(nt, tc, 'Generated', sep, 'Vector')

    # Градиент неба по высоте направления z∈[-1,1] без Color Ramp (только Mix):
    #   горизонт — слабое лиловое зарево города, вверх — тёмно-синее, вниз — чёрное.
    glow = (0.06, 0.02, 0.05)
    upper = (0.012, 0.014, 0.035)
    zenith = (0.002, 0.002, 0.007)
    below = (0.004, 0.005, 0.010)
    fade_up = mathn(nt, 'MULTIPLY', (sep, 'Z'), 8.0, clamp=True)      # 0..1 на z 0..0.125
    fade_top = mathn(nt, 'MULTIPLY', (sep, 'Z'), 1.2, clamp=True)     # 0..1 на z 0..0.83
    fade_down = mathn(nt, 'MULTIPLY', (sep, 'Z'), -6.0, clamp=True)   # 0..1 на z 0..-0.17
    is_below = mathn(nt, 'LESS_THAN', (sep, 'Z'), 0.0)
    sky_up = mix_rgb(nt, glow, upper, (fade_up, 0))
    sky_up = mix_rgb(nt, (sky_up, mix_out(sky_up)), zenith, (fade_top, 0))
    sky_down = mix_rgb(nt, glow, below, (fade_down, 0))
    sky = mix_rgb(nt, (sky_up, mix_out(sky_up)), (sky_down, mix_out(sky_down)), (is_below, 0))

    # Звёзды: мелкие ячейки Вороного, только над горизонтом.
    vor = node(nt, 'ShaderNodeTexVoronoi', props={'voronoi_dimensions': '3D', 'feature': 'F1'},
               inputs={'Scale': 170.0, 'Randomness': 1.0})
    link(nt, tc, 'Generated', vor, 'Vector')
    star = mathn(nt, 'LESS_THAN', (vor, 'Distance'), 0.05)
    above = mathn(nt, 'GREATER_THAN', (sep, 'Z'), 0.03)
    star = mathn(nt, 'MULTIPLY', (star, 0), (above, 0))
    star = mathn(nt, 'MULTIPLY', (star, 0), 1.2)
    final = mix_rgb(nt, (sky, mix_out(sky)), (0.9, 0.95, 1.0), (star, 0), blend='ADD')
    link(nt, final, mix_out(final), bg, 'Color')
    link(nt, bg, 'Background', out, 'Surface')


def add_light(name, kind, location, energy, color, rotation=(0, 0, 0), radius=0.5,
              parent=None, track=None, spot_size=55.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind in ('POINT', 'SPOT'):
        # до 4.x — shadow_soft_size, в новых версиях может называться radius
        setopt(ld, 'shadow_soft_size', radius) or setopt(ld, 'radius', radius)
    if kind == 'SPOT':
        setopt(ld, 'spot_size', math.radians(spot_size))
        setopt(ld, 'spot_blend', 0.6)
    if kind == 'SUN':
        setopt(ld, 'angle', math.radians(2.0))
    ob = bpy.data.objects.new(name, ld)
    ob.location = location
    ob.rotation_euler = rotation
    if parent is not None:
        ob.parent = parent
    if track is not None:
        c = ob.constraints.new('TRACK_TO')
        c.target = track
        c.track_axis = 'TRACK_NEGATIVE_Z'
        c.up_axis = 'UP_Y'
    bpy.context.scene.collection.objects.link(ob)
    return ob


def inside_any(aabbs, x, y, z=0.0):
    for (x0, x1, y0, y1, h) in aabbs:
        if x0 - 0.3 <= x <= x1 + 0.3 and y0 - 0.3 <= y <= y1 + 0.3 and z <= h + 0.3:
            return True
    return False


def setup_glare(scene):
    """Мягкое свечение неона в композиторе.

    Blender 5.x: дерево лежит в scene.compositing_node_group с NodeGroupOutput;
    4.x: scene.use_nodes + CompositorNodeComposite. Если API не совпал,
    композитор выключаем целиком, чтобы рендер шёл без него, а не падал.
    """
    new_api = hasattr(scene, "compositing_node_group")
    try:
        if new_api:
            nt = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
            rl = nt.nodes.new("CompositorNodeRLayers")
            rl.scene = scene
            glare = nt.nodes.new("CompositorNodeGlare")
            nt.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
            outn = nt.nodes.new("NodeGroupOutput")
            nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
            nt.links.new(glare.outputs["Image"], outn.inputs[0])
        else:
            scene.use_nodes = True
            nt = scene.node_tree
            nt.nodes.clear()
            rl = nt.nodes.new("CompositorNodeRLayers")
            glare = nt.nodes.new("CompositorNodeGlare")
            comp = nt.nodes.new("CompositorNodeComposite")
            nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
            nt.links.new(glare.outputs["Image"], comp.inputs["Image"])
        # Только мягкое свечение. По умолчанию у Glare стоит STREAKS (крестовые
        # полосы): если ни BLOOM, ни FOG_GLOW не принялись — композитор выключаем.
        for gtype in ('BLOOM', 'FOG_GLOW'):
            setopt(glare, 'glare_type', gtype)
            if getattr(glare, 'glare_type', None) == gtype:
                break
        else:
            raise RuntimeError(f"Glare не принял BLOOM/FOG_GLOW, остался {glare.glare_type!r}")
        # В 4.5+ параметры Glare — сокеты, раньше — свойства узла.
        for sname, attr, val in (("Threshold", "threshold", 1.5),
                                 ("Strength", "mix", 0.15),
                                 ("Size", "size", 0.5)):
            s = sock(glare.inputs, sname)
            if s is not None:
                for v in (val, int(round(val * 14))):   # float; для FOG_GLOW размер целый
                    try:
                        s.default_value = v
                        break
                    except Exception:
                        continue
            else:
                setopt(glare, attr, val) or setopt(glare, attr, int(round(val * 14)))
        if new_api:
            scene.compositing_node_group = nt   # подключаем только собранное дерево
        setopt(scene.render, 'use_compositing', True)
    except Exception as exc:  # noqa: BLE001
        warn(f"glare пропущен: {exc}")
        if new_api:
            setopt(scene, 'compositing_node_group', None)
        else:
            setopt(scene, 'use_nodes', False)
        setopt(scene.render, 'use_compositing', False)


def look_final(scene, robot_parts, city, rng):
    set_engine(scene, ['BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'])
    # Бюджет ~3–4 с/кадр на 1080×720 (M1 Max): мало сэмплов, крупные тайлы
    # объёма, без трассировки лучей и объёмных теней; motion blur оставлен.
    ee = scene.eevee
    setopt(ee, 'taa_render_samples', 16)
    setopt(ee, 'use_shadows', True)
    setopt(ee, 'shadow_ray_count', 1)
    setopt(ee, 'shadow_step_count', 2)
    setopt(ee, 'use_raytracing', False)
    setopt(ee, 'use_fast_gi', False)
    setopt(ee, 'volumetric_tile_size', '16')
    setopt(ee, 'volumetric_samples', 24)
    setopt(ee, 'volumetric_start', 0.5)
    setopt(ee, 'volumetric_end', 80.0)
    setopt(ee, 'use_volumetric_shadows', False)
    setopt(ee, 'motion_blur_steps', 1)
    setopt(scene.render, 'use_motion_blur', True)
    setopt(scene.render, 'motion_blur_shutter', 0.25)
    for vt in ('AgX', 'Filmic', 'Standard'):
        if setopt(scene.view_settings, 'view_transform', vt):
            break
    for lk in ('AgX - Punchy', 'Punchy', 'None'):
        if setopt(scene.view_settings, 'look', lk):
            break
    setopt(scene.view_settings, 'exposure', 0.0)

    world_night(scene)

    # --- материалы робота ---
    m_body = mat_simple("RobotOrange", (1.0, 0.42, 0.06), rough=0.5, metal=0.0)
    m_dark = mat_simple("RobotDark", (0.10, 0.10, 0.12), rough=0.6, metal=0.3)
    m_screen = mat_simple("RobotScreen", (0.01, 0.02, 0.03), rough=0.2,
                          emit=(0.05, 0.30, 0.40), emit_strength=1.5)
    m_eyes = mat_emission("RobotEyes", (0.45, 1.0, 1.0), 14.0)
    m_tip = mat_emission("RobotTip", (1.0, 0.15, 0.1), 8.0)
    robot_parts['body'].data.materials.append(m_body)
    robot_parts['legs'].data.materials.append(m_dark)
    robot_parts['arms'].data.materials.append(m_dark)
    robot_parts['antenna'].data.materials.append(m_dark)
    robot_parts['antenna_tip'].data.materials.append(m_tip)
    robot_parts['screen'].data.materials.append(m_screen)
    for eye in robot_parts['eyes']:
        eye.data.materials.append(m_eyes)

    # --- город ---
    m_bld = mat_building("Building")
    m_roof = mat_building("RoofBuilding", lit_threshold=0.85, emit_strength=0.6)
    m_prop = mat_simple("RoofProps", (0.12, 0.13, 0.15), rough=0.7)
    m_ground = mat_simple("Ground", (0.015, 0.016, 0.02), rough=0.9)
    city['ground'].data.materials.append(m_ground)
    for b in city['buildings']:
        b.data.materials.append(m_bld)
    for b in city['roofs']:
        b.data.materials.append(m_roof)
    for p in city['props']:
        p.data.materials.append(m_prop)

    sign_mats = [mat_emission(f"Neon{i}", c, 5.0) for i, c in enumerate(SIGN_PALETTE)]
    for s in city['signs']:
        s['obj'].data.materials.append(sign_mats[s['color']])

    # --- туман между домами ---
    fog = make_mesh_object("FogVolume", [('box', (10.0, 0.0, FOG_H / 2), (110.0, 100.0, FOG_H))])
    fog.data.materials.append(mat_fog())
    setopt(fog, 'display_type', 'WIRE')
    setopt(fog, 'visible_shadow', False)

    # --- свет ---
    rig = robot_parts['rig']
    # Свет робота едет вместе с ним (риг без сжатия) и всегда смотрит на него.
    # Ключевой: тёплый, со стороны камеры (спереди-сбоку, +X −Y), сверху.
    add_light("RobotKey", 'SPOT', (3.0, -3.5, 3.2), 900.0, (1.0, 0.82, 0.62),
              radius=0.6, parent=rig, track=rig, spot_size=60.0)
    # Контровой: холодный, сзади-сбоку (−X +Y), очерчивает силуэт.
    add_light("RobotRim", 'SPOT', (-3.0, 3.0, 2.8), 700.0, (0.6, 0.8, 1.0),
              radius=0.4, parent=rig, track=rig, spot_size=50.0)
    # Слабая луна и заполняющий — только чтобы город не был чёрным.
    add_light("Moon", 'SUN', (0, 0, 60), 0.3, (0.55, 0.65, 1.0),
              rotation=(math.radians(55), 0.0, math.radians(-135)))
    add_light("Fill", 'SUN', (0, 0, 60), 0.06, (1.0, 0.78, 0.6),
              rotation=(math.radians(60), 0.0, math.radians(45)))
    # Свечение экрана на самом роботе.
    add_light("FaceGlow", 'POINT', (0.95, 0.0, 0.85), 12.0, (0.4, 0.9, 1.0),
              radius=0.3, parent=robot_parts['body'].parent)
    # Уличные фонари в просветах между зданиями (подсвечивают туман) — приглушены.
    n_street = 0
    for x in range(-8, 32, 6):
        for y in (-3.6, 6.8):
            if inside_any(city['aabb'], x, y, 3.5):
                continue
            add_light(f"Street{n_street:02d}", 'POINT', (x + rng.uniform(-1, 1), y, 3.5),
                      220.0, (1.0, 0.62, 0.3), radius=0.6)
            n_street += 1
    # Точечные источники у части вывесок, чтобы неон слегка красил стены и туман.
    for i, s in enumerate(city['signs'][:10]):
        c = SIGN_PALETTE[s['color']]
        add_light(f"SignLight{i:02d}", 'POINT', s['pos'] + Vector((0.0, -0.8, 0.0)),
                  60.0, c, radius=0.5)

    setup_glare(scene)


# ---------------------------------------------------------------------------
# 5. Сборка и рендер
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="scene.py")
    p.add_argument("--variant", choices=["blockout", "final"], required=True)
    p.add_argument("--out", required=True, help="папка для PNG-кадров")
    p.add_argument("--start", type=int, default=None)
    p.add_argument("--end", type=int, default=None)
    p.add_argument("--scale", type=int, default=100, help="resolution_percentage")
    return p.parse_args(argv)


def clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for blk in list(coll):
            if blk.users == 0:
                coll.remove(blk)


def main():
    args = parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    scene = bpy.context.scene
    clear_scene()
    rng = random.Random(SEED)

    # Общая часть: геометрия + анимация.
    robot_root, eyes, robot_parts = build_robot()
    rig = bpy.data.objects.new("RobotRig", None)       # едет за роботом, без сжатия
    rig.empty_display_type = 'PLAIN_AXES'
    scene.collection.objects.link(rig)
    robot_parts['rig'] = rig
    city = build_city(rng)
    cam, cam_target = build_camera()
    animate(robot_root, rig, cam, cam_target, eyes)

    # Внешний вид.
    if args.variant == 'blockout':
        look_blockout(scene)
    else:
        look_final(scene, robot_parts, city, rng)

    # Кадр, время, вывод.
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.frame_start = args.start if args.start is not None else FRAME_START
    scene.frame_end = args.end if args.end is not None else FRAME_END
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.resolution_percentage = max(1, min(100, args.scale))
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 50
    scene.render.use_file_extension = True
    scene.render.use_overwrite = True
    scene.render.filepath = os.path.join(out_dir, "####")

    print(f"[scene.py] variant={args.variant} engine={scene.render.engine} "
          f"frames={scene.frame_start}-{scene.frame_end} "
          f"res={RES_X}x{RES_Y}@{scene.render.resolution_percentage}% out={out_dir}")
    bpy.ops.render.render(animation=True)
    print("[scene.py] готово")


if __name__ == "__main__":
    main()
