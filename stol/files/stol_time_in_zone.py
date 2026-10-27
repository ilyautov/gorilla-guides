"""Время в зоне для столов и очереди: логика примера roboflow/supervision examples/time_in_zone
(rfdetr_file_example.py), но без окна и с состоянием стола. Страница: https://ilyautov.github.io/gorilla-guides/stol/

RF-DETR (Apache-2.0) -> ByteTrackTracker (trackers, Apache-2.0) -> sv.PolygonZone -> FPSBasedTimer из примера.
Отличия от примера:
  * кадры пишутся в out/annotated.mp4, а не показываются в окне;
  * состояние стола: СВОБОДЕН / таймер / УБРАТЬ (людей нет больше 1 с, а детектор видит на столе посуду:
    cup, bowl, wine glass, bottle — в 60 % кадров последних 2 с; снимается ниже 10 %), подписи по-русски;
  * порог нового трека (--high) вынесен в параметр: в примере он 0,6, и сидящих людей трекер часто не берёт;
  * out/frames.json — по кадрам: сколько людей в каждой зоне, их номера и секунды; out/summary.json — сводка.

Положите файл в папку supervision/examples/time_in_zone (нужна её папка utils/) и запустите:
  python stol_time_in_zone.py --video zal.mp4 --zones zones.json --out out --size medium --resolution 896 \
      --high 0.35 --buffer 50 --device mps
zones.json — как от scripts/draw_zones.py (список полигонов) или словарь {"СТОЛ 7": [[x, y], ...], ...}.
Шрифт с кириллицей для подписей: переменная HUD_FONT (по умолчанию Arial Bold из macOS).
"""
import argparse, json, os, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import supervision as sv
from rfdetr import RFDETRMedium, RFDETRSmall, RFDETRNano
from trackers import ByteTrackTracker

HERE = os.path.dirname(os.path.abspath(__file__))
# utils/ из examples/time_in_zone: либо скрипт лежит в папке примера, либо путь в TIME_IN_ZONE_DIR
EX = os.environ.get('TIME_IN_ZONE_DIR') or (HERE if os.path.isdir(os.path.join(HERE, 'utils')) else os.path.join(HERE, '..', '_download', 'supervision-examples'))
sys.path.insert(0, EX)
from utils.timers import FPSBasedTimer      # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--video', required=True); ap.add_argument('--zones', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--size', default='medium'); ap.add_argument('--device', default='cpu'); ap.add_argument('--resolution', type=int, default=0)
ap.add_argument('--conf', type=float, default=0.3); ap.add_argument('--iou', type=float, default=0.7)
ap.add_argument('--high', type=float, default=0.6); ap.add_argument('--buffer', type=int, default=30)
ap.add_argument('--gt', default=''); ap.add_argument('--leave_s', type=float, default=1.0); ap.add_argument('--enter_s', type=float, default=1.0)
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

PERSON = 1                                  # rfdetr отдаёт id классов COCO: 1 = person
WARE = [44, 46, 47, 51]                     # bottle, wine glass, cup, bowl — посуда на столе (id COCO)
from collections import deque
M = {'medium': RFDETRMedium, 'small': RFDETRSmall, 'nano': RFDETRNano}[args.size]
model = M(device=args.device, **({'resolution': args.resolution} if args.resolution else {}))
# в примере: ByteTrackTracker(minimum_iou_threshold=0.5, track_activation_threshold=conf); остальное по умолчанию,
# в т.ч. high_conf_det_threshold=0.6 — новый трек заводится только с уверенности 0,6. Сидящих мультяшных людей
# детектор видит с уверенностью 0,3–0,5, поэтому порог нового трека — параметр (--high).
tracker = ByteTrackTracker(minimum_iou_threshold=0.5, track_activation_threshold=args.conf,
                           high_conf_det_threshold=args.high, lost_track_buffer=args.buffer, frame_rate=25)

info = sv.VideoInfo.from_video_path(args.video); fps = info.fps
named = json.load(open(args.zones))
if isinstance(named, list):                 # формат scripts/draw_zones.py: просто список полигонов
    named = {f'ЗОНА {i + 1}': p for i, p in enumerate(named)}
names = list(named)
zones = [sv.PolygonZone(polygon=np.array(named[n], np.int32), triggering_anchors=(sv.Position.CENTER,)) for n in names]
timers = [FPSBasedTimer(fps) for _ in zones]

FONT = os.environ.get('HUD_FONT', '/System/Library/Fonts/Supplemental/Arial Bold.ttf')   # нужен шрифт с кириллицей
try:
    F_BIG, F_SM = ImageFont.truetype(FONT, 30), ImageFont.truetype(FONT, 20)
except OSError:
    F_BIG = F_SM = ImageFont.load_default()
COL = {'free': (60, 200, 90), 'busy': (255, 140, 0), 'dirty': (255, 215, 0), 'queue': (0, 200, 220)}

# состояние зон
state = {n: ('queue' if n == 'ОЧЕРЕДЬ' else 'free') for n in names}
empty_run = {n: 0 for n in names}; busy_run = {n: 0 for n in names}
ware_hist = {n: deque(maxlen=max(1, int(2 * fps))) for n in names}   # была ли посуда в зоне в кадрах последних 2 с
events = []                                  # (t, зона, событие)
frames_log = []
first_seen = {}                              # tracker_id -> (зона, кадр входа)
dwell = {n: {} for n in names}               # зона -> tracker_id -> секунд в зоне (по примеру: от первого появления)
n_enter = int(args.enter_s * fps); n_leave = int(args.leave_s * fps)

box_ann = sv.BoxAnnotator(thickness=2, color=sv.Color.from_hex('#00E5FF'))
ware_ann = sv.BoxAnnotator(thickness=1, color=sv.Color.from_hex('#FFFFFF'))
gt = json.load(open(args.gt)) if args.gt and os.path.exists(args.gt) else None

sink = sv.VideoSink(os.path.join(args.out, 'annotated.mp4'), info)
with sink:
    for fi, frame in enumerate(sv.get_video_frames_generator(args.video)):
        t = fi / fps
        det_all = model.predict(frame[:, :, ::-1].copy(), threshold=args.conf)
        ware = det_all[np.isin(det_all.class_id, WARE)]
        det = det_all[det_all.class_id == PERSON]
        det = det.with_nms(threshold=args.iou)
        det = tracker.update(det)
        det = det[det.tracker_id != -1]
        rec = {'frame': fi, 't': round(t, 2), 'persons': int(len(det)), 'zones': {}}
        labels_draw = []
        for zi, (n, z) in enumerate(zip(names, zones)):
            inz = det[z.trigger(det)]
            times = timers[zi].tick(inz)
            ids = [int(x) for x in inz.tracker_id]
            for i, s in zip(ids, times): dwell[n][i] = round(float(s), 2)
            cnt = len(ids)
            if n != 'ОЧЕРЕДЬ':
                if cnt:
                    busy_run[n] += 1; empty_run[n] = 0
                else:
                    empty_run[n] += 1; busy_run[n] = 0
                nw = int(z.trigger(ware).sum()) if len(ware) else 0
                ware_hist[n].append(nw > 0); r = sum(ware_hist[n]) / len(ware_hist[n])
                # гистерезис: «посуда есть» с 60 % кадров за 2 с, «посуды нет» — только когда меньше 10 %
                has_ware = r >= 0.1 if state[n] == 'dirty' else r >= 0.6
                if state[n] in ('free', 'dirty') and busy_run[n] >= n_enter:
                    if state[n] == 'dirty': events.append((round(t - args.enter_s, 2), n, 'к грязному столу подошли'))
                    state[n] = 'busy'; events.append((round(t - args.enter_s, 2), n, 'в зоне люди: таймер пошёл'))
                elif state[n] != 'busy' and empty_run[n] >= n_leave:
                    new = 'dirty' if has_ware else 'free'
                    if new != state[n]:
                        events.append((round(t, 2), n, 'на пустом столе посуда: УБРАТЬ' if new == 'dirty' else 'стол чистый: СВОБОДЕН'))
                    state[n] = new
                elif state[n] == 'busy' and empty_run[n] >= n_leave:
                    state[n] = 'dirty' if has_ware else 'free'
                    events.append((round(t - args.leave_s, 2), n, 'люди ушли, посуда осталась: УБРАТЬ' if has_ware else 'люди ушли, посуды нет: СВОБОДЕН'))
                rec.setdefault('ware', {})[n] = nw
            rec['zones'][n] = {'count': cnt, 'ids': ids, 'sec': [round(float(s), 2) for s in times], 'state': state[n]}
            labels_draw.append((n, cnt, (max(times) if len(times) else 0.0)))
        frames_log.append(rec)

        # рисуем: полигоны состояний, боксы, таймеры
        out = frame.copy()
        overlay = out.copy()
        for n, z in zip(names, zones):
            c = COL[state[n]]; bgr = (c[2], c[1], c[0])
            cv2.fillPoly(overlay, [z.polygon], bgr)
        out = cv2.addWeighted(overlay, 0.18, out, 0.82, 0)
        for n, z in zip(names, zones):
            c = COL[state[n]]; cv2.polylines(out, [z.polygon], True, (c[2], c[1], c[0]), 3, cv2.LINE_AA)
        out = ware_ann.annotate(out, ware)
        out = box_ann.annotate(out, det)
        img = Image.fromarray(out[:, :, ::-1]); dr = ImageDraw.Draw(img)
        for (n, cnt, mx), z in zip(labels_draw, zones):
            x = int(z.polygon[:, 0].mean()); y = int(z.polygon[:, 1].max()) + 4
            st = state[n]
            if n == 'ОЧЕРЕДЬ':
                txt = f'ОЧЕРЕДЬ: {cnt} чел.' + (f' · {int(mx // 60):02d}:{int(mx % 60):02d}' if cnt else '')
            elif st == 'busy':
                txt = f'{n} · {int(mx // 60):02d}:{int(mx % 60):02d}'
            elif st == 'dirty':
                txt = f'{n} · УБРАТЬ'
            else:
                txt = f'{n} · свободен'
            w = dr.textlength(txt, font=F_SM)
            y = min(y, img.height - 30)
            dr.rectangle([x - w / 2 - 6, y, x + w / 2 + 6, y + 26], fill=(0, 0, 0))
            dr.text((x - w / 2, y + 2), txt, font=F_SM, fill=COL[st])
        for xyxy, tid in zip(det.xyxy, det.tracker_id):
            dr.text((int(xyxy[0]), int(xyxy[1]) - 22), f'#{tid}', font=F_SM, fill=(0, 229, 255))
        dr.rectangle([12, 12, 330, 52], fill=(0, 0, 0)); dr.text((22, 16), f'LIVE · ЗАЛ 1 · {t:05.2f} c', font=F_BIG, fill=(255, 255, 255))
        sink.write_frame(np.array(img)[:, :, ::-1])
        if fi % 50 == 0: print(f'frame {fi} t={t:.1f} persons={len(det)}', flush=True)

json.dump(frames_log, open(os.path.join(args.out, 'frames.json'), 'w'), ensure_ascii=False)

# сводка
def intervals(n, key):
    """Интервалы кадров, где зона в состоянии key."""
    res, cur = [], None
    for r in frames_log:
        on = r['zones'][n]['state'] == key
        if on and cur is None: cur = r['t']
        if not on and cur is not None: res.append([cur, r['t']]); cur = None
    if cur is not None: res.append([cur, frames_log[-1]['t']])
    return res

summary = {'video': os.path.basename(args.video), 'fps': fps, 'frames': len(frames_log), 'model': f'RF-DETR {args.size}',
           'resolution': args.resolution or 'default', 'conf': args.conf, 'high_conf_det_threshold': args.high, 'lost_track_buffer': args.buffer, 'events': events, 'zones': {}}
for n in names:
    cnts = [r['zones'][n]['count'] for r in frames_log]
    z = {'max_people': max(cnts), 'mean_people': round(float(np.mean(cnts)), 2),
         'tracks': {str(k): v for k, v in dwell[n].items()}}
    if n == 'ОЧЕРЕДЬ':
        z['frames_with_queue'] = int(sum(c > 0 for c in cnts))
    else:
        z['busy'] = intervals(n, 'busy'); z['dirty'] = intervals(n, 'dirty')
    summary['zones'][n] = z

if gt:
    acc = {}
    for n in names:
        g = gt['zone_count'][n][:len(frames_log)]; p = [r['zones'][n]['count'] for r in frames_log]
        exact = sum(a == b for a, b in zip(g, p)) / len(g)
        mae = float(np.mean([abs(a - b) for a, b in zip(g, p)]))
        acc[n] = {'exact_frames_pct': round(100 * exact, 1), 'mae_people': round(mae, 2), 'gt_max': max(g), 'pred_max': max(p)}
    summary['accuracy_vs_gt'] = acc
    tl = gt['timeline']; summary['gt_timeline_s'] = {k: round(v, 2) for k, v in tl.items()}
    gtp = [sum(1 for a in gt['actors'].values()) for _ in frames_log]
    summary['people_in_scene_gt'] = len(gt['actors'])

json.dump(summary, open(os.path.join(args.out, 'summary.json'), 'w'), ensure_ascii=False, indent=1)
print(json.dumps({k: summary[k] for k in ('events',)}, ensure_ascii=False))
if gt: print(json.dumps(summary['accuracy_vs_gt'], ensure_ascii=False))
