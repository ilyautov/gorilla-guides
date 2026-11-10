#!/usr/bin/env python3
"""Жюри из 12 зрителей для сценария рила. Каждая персона = отдельный вызов `claude -p`
без пользовательских настроек (`--setting-sources ""`) из пустой временной папки, ответ JSON.

  python3 jury.py verdict  <script.md> <out_dir> [--repeat N] [--workers 3]
  python3 jury.py hooks    <script.md> <out_dir> [--workers 3]

verdict: каждая персона называет секунду, на которой пролистала (или null = досмотрела),
         причину и одну правку. Итог «досмотрели N/12» и топ правок.
hooks:   один вызов придумывает 12 вариантов первой фразы, затем каждая персона
         голосует по всем 12 (остаюсь после 3 секунд или листаю). Хук зелёный, если
         остались ≥ 8 из 12 (порог --green).
Это симуляция LLM, а не реальные зрители: цифры годятся для сравнения версий одного
сценария между собой, не для прогноза охвата.
"""
import argparse, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PERSONAS = json.loads((HERE / "personas.json").read_text())


def claude(prompt: str, tries: int = 3) -> str:
    cwd = tempfile.mkdtemp(prefix="jury-")
    for i in range(tries):
        r = subprocess.run(["claude", "-p", "--setting-sources", "", prompt],
                           cwd=cwd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"claude failed: {r.returncode} {r.stderr[:300]}")


def parse_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    start = min([i for i in (body.find("{"), body.find("[")) if i >= 0])
    return json.loads(body[start:body.rfind("}" if body[start] == "{" else "]") + 1])


FEED = ("Ты листаешь ленту Instagram Reels со своего телефона. Ты не помощник и не критик, "
        "ты обычный зритель со своими привычками, вежливость не нужна. В ленте тысячи роликов, "
        "и ты листаешь дальше, как только становится неинтересно или непонятно.\n\n"
        "Кто ты: {name}. {card}\n\n")

VERDICT = FEED + (
    "Вот рил посекундно: что звучит и что видно на экране.\n\n{script}\n\n"
    "Представь, что этот рил появился у тебя в ленте. Реши честно, на какой секунде ты "
    "пролистнёшь его, или досмотришь до конца.\n"
    "Ответь строго одним JSON без пояснений вокруг:\n"
    '{{"swipe_at": <секунда числом, когда пролистнул, или null если досмотрел>, '
    '"reason": "<почему, одной фразой от первого лица>", '
    '"fix": "<одна правка, которая удержала бы тебя, одной фразой>"}}')

HOOKGEN = (
    "Ты сценарист коротких вертикальных роликов для Instagram Reels. Ниже сценарий рила "
    "посекундно. Автор жалуется: «у меня хук скучный». Придумай 12 разных вариантов первой "
    "фразы (0,0–2,5 с), которая заменит текущую. Правила: это реплика персонажа другому "
    "персонажу (обращение по имени, например «Клод, …»), а не закадровое описание; в первой "
    "фразе сразу результат, скандал или интрига; до 9 слов; по-русски, без слова «ИИ» и без "
    "англицизмов; варианты разные по приёму (цифра, конфликт, абсурд, вопрос, признание, "
    "угроза и т. п.); остальная часть сценария не меняется, хук должен к ней вести.\n\n"
    "{script}\n\n"
    'Ответь строго JSON: {{"hooks": [{{"text": "...", "device": "<приём одним-двумя словами>"}}, ...]}} '
    "ровно 12 элементов.")

HOOKVOTE = FEED + (
    "Ниже 12 вариантов начала одного и того же рила (первые 2–3 секунды; дальше идёт этот "
    "сюжет: {plot}). Для каждого варианта реши: ты остаёшься смотреть дальше третьей секунды "
    "или листаешь.\n\n{hooks}\n\n"
    'Ответь строго JSON: {{"votes": [{{"n": <номер>, "stay": true|false, "why": "<3–8 слов>"}}, ...]}} '
    "ровно 12 элементов, по порядку.")


def run_verdict(script_path, out, repeat, workers):
    script = Path(script_path).read_text()
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(rep, p) for rep in range(1, repeat + 1) for p in PERSONAS]

    def one(job):
        rep, p = job
        raw = claude(VERDICT.format(name=p["name"], card=p["card"], script=script))
        try:
            data = parse_json(raw)
        except Exception as e:
            data = {"swipe_at": None, "reason": f"PARSE_ERROR {e}", "fix": ""}
        rec = {"rep": rep, "persona": p["id"], "name": p["name"], **data, "raw": raw}
        (out / f"r{rep}-{p['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        return rec

    with ThreadPoolExecutor(workers) as ex:
        recs = list(ex.map(one, jobs))
    summary = {"script": str(script_path), "personas": len(PERSONAS), "repeats": repeat, "runs": []}
    for rep in range(1, repeat + 1):
        rr = [r for r in recs if r["rep"] == rep]
        stayed = [r for r in rr if r.get("swipe_at") is None]
        summary["runs"].append({
            "rep": rep,
            "watched_to_end": len(stayed),
            "of": len(rr),
            "swipes": sorted([(r["swipe_at"], r["persona"]) for r in rr if r.get("swipe_at") is not None]),
        })
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    for r in summary["runs"]:
        print(f"rep {r['rep']}: досмотрели {r['watched_to_end']}/{r['of']}  пролистали на: {r['swipes']}")
    return summary


def run_hooks(script_path, out, workers, green):
    script = Path(script_path).read_text()
    out.mkdir(parents=True, exist_ok=True)
    gen_raw = claude(HOOKGEN.format(script=script))
    hooks = parse_json(gen_raw)["hooks"][:12]
    (out / "hooks-generated.json").write_text(json.dumps({"hooks": hooks, "raw": gen_raw}, ensure_ascii=False, indent=1))
    plot_m = re.search(r"^Сюжет:\s*(.+)$", script, re.M)
    plot = plot_m.group(1) if plot_m else "см. сценарий"
    listing = "\n".join(f"{i+1}. «{h['text']}»" for i, h in enumerate(hooks))

    def one(p):
        raw = claude(HOOKVOTE.format(name=p["name"], card=p["card"], plot=plot, hooks=listing))
        try:
            votes = parse_json(raw)["votes"]
        except Exception as e:
            votes = []
        rec = {"persona": p["id"], "name": p["name"], "votes": votes, "raw": raw}
        (out / f"vote-{p['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        return rec

    with ThreadPoolExecutor(workers) as ex:
        recs = list(ex.map(one, PERSONAS))
    table = []
    for i, h in enumerate(hooks):
        stay = [r["persona"] for r in recs for v in r["votes"] if v.get("n") == i + 1 and v.get("stay")]
        table.append({"n": i + 1, "text": h["text"], "device": h.get("device", ""),
                      "stay": len(stay), "of": len(recs), "verdict": "green" if len(stay) >= green else "red",
                      "stayed": stay})
    table.sort(key=lambda x: -x["stay"])
    (out / "hooks-summary.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    for t in table:
        print(f"{'[G]' if t['verdict']=='green' else '[R]'} {t['stay']:2d}/{t['of']} «{t['text']}» ({t['device']})")
    return table


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["verdict", "hooks"])
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--green", type=int, default=8)
    a = ap.parse_args()
    if a.mode == "verdict":
        run_verdict(a.script, Path(a.out), a.repeat, a.workers)
    else:
        run_hooks(a.script, Path(a.out), a.workers, a.green)
