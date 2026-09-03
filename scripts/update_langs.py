#!/usr/bin/env python3
"""
Собирает статистику языков по всем репозиториям пользователя (включая приватные)
и рисует кольцевую диаграмму в двух темах: assets/langs-light.svg и assets/langs-dark.svg.
В README между маркерами подставляет <picture>, который сам переключается
светлая/тёмная тема GitHub.

Запуск:  GH_TOKEN=<token> python scripts/update_langs.py

Переменные окружения:
  GH_TOKEN        - токен с доступом к репозиториям (обязательно для приватных)
  GH_USER         - логин пользователя (по умолчанию Menanshin)
  README_PATH     - путь к README (по умолчанию README.md)
  ASSETS_DIR      - куда класть SVG (по умолчанию assets)
  BRANCH          - ветка в ссылках на картинки (в Actions определяется сама)
  MAX_SLICES      - сколько секторов рисовать, остальное схлопнется в "Прочее" (по умолчанию 6)
  MIN_PERCENT     - языки меньше N% уходят в "Прочее" (по умолчанию 1.5)
  INCLUDE_FORKS   - "1" чтобы учитывать форки (по умолчанию выключено)
  EXCLUDE_REPOS   - репозитории через запятую, которые не учитывать
  EXCLUDE_LANGS   - языки через запятую, которые не учитывать
"""

import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"

USER = os.environ.get("GH_USER", "Menanshin")
TOKEN = os.environ.get("GH_TOKEN", "")
README_PATH = os.environ.get("README_PATH", "README.md")
ASSETS_DIR = os.environ.get("ASSETS_DIR", "assets")
# Ветка для ссылок на картинки: в Actions берётся сама, локально — main
BRANCH = os.environ.get("BRANCH") or os.environ.get("GITHUB_REF_NAME") or "main"
MAX_SLICES = int(os.environ.get("MAX_SLICES", "6"))
MIN_PERCENT = float(os.environ.get("MIN_PERCENT", "1.5"))
INCLUDE_FORKS = os.environ.get("INCLUDE_FORKS", "") == "1"
EXCLUDE_REPOS = {r.strip().lower() for r in os.environ.get("EXCLUDE_REPOS", "").split(",") if r.strip()}
EXCLUDE_LANGS = {l.strip().lower() for l in os.environ.get("EXCLUDE_LANGS", "").split(",") if l.strip()}

START = "<!-- LANGS:START -->"
END = "<!-- LANGS:END -->"
OTHER = "Прочее"

# Фирменные цвета под стиль README (приоритетнее палитры linguist)
BRAND_COLORS = {
    "Python": "3776AB", "Java": "ED8B00", "JavaScript": "F7DF1E", "TypeScript": "3178C6",
    "HTML": "E34F26", "CSS": "1572B6", "Shell": "4EAA25", "Dockerfile": "2496ED",
    "Go": "00ADD8", "Kotlin": "7F52FF", "Ruby": "CC342D", "PHP": "777BB4",
    "Rust": "DEA584", "Solidity": "7B68EE", "Gherkin": "23D96C", "HCL": "623CE4",
    "Makefile": "427819", "Jupyter Notebook": "F37626", "PLpgSQL": "4169E1",
    "C#": "512BD4", "C++": "00599C", "Swift": "F05138", "Vue": "4FC08D",
    "Lua": "2C2D72", "PowerShell": "5391FE",
}

# Темы: поверхность и цвета текста под светлый/тёмный GitHub
THEMES = {
    "light": {"ink": "#1F2328", "muted": "#59636E", "surface": "#FFFFFF"},
    "dark": {"ink": "#F0F6FC", "muted": "#9198A1", "surface": "#0D1117"},
}

FONT = ('-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,'
        '"Noto Sans",sans-serif')

# Геометрия
W, H = 468, 200
CX, CY = 104, 100
R, SW = 64, 22          # радиус средней линии кольца и толщина
GAP_PX = 3.0            # разрыв поверхности между секторами, в пикселях дуги
LEGEND_X = 208
ROW_H = 23


def gh(path, token):
    req = urllib.request.Request(
        path if path.startswith("http") else API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "langs-donut-script",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_repos(token):
    """Все репозитории, которыми владеет пользователь: приватные + публичные."""
    repos, page = [], 1
    while True:
        if token:
            url = f"/user/repos?affiliation=owner&visibility=all&per_page=100&page={page}"
        else:
            url = f"/users/{USER}/repos?per_page=100&page={page}"
        batch = gh(url, token)
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_linguist_colors():
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/ozh/github-colors/master/colors.json",
            headers={"User-Agent": "langs-donut-script"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except Exception as e:
        print(f"! палитра linguist недоступна ({e}), беру только фирменные цвета", file=sys.stderr)
        return {}


def color_for(lang, palette):
    if lang == OTHER:
        return "8B949E"
    if lang in BRAND_COLORS:
        return BRAND_COLORS[lang]
    color = (palette.get(lang) or {}).get("color")
    return color.lstrip("#").upper() if color else "8B949E"


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(round(c)))):02X}" for c in rgb)


def _luma(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def adapt(hex_color, theme):
    """Держим сектор различимым на своей поверхности: очень тёмные цвета
    осветляем на тёмной теме, очень светлые притемняем на светлой."""
    try:
        rgb = _rgb(hex_color)
    except (ValueError, IndexError):
        rgb = (139, 148, 158)
    luma = _luma(rgb)
    if theme == "dark" and luma < 80:
        t = (80 - luma) / 80 * 0.75
        rgb = tuple(c + (255 - c) * t for c in rgb)
    elif theme == "light" and luma > 225:
        t = (luma - 225) / 30 * 0.55
        rgb = tuple(c * (1 - t) for c in rgb)
    return _hex(rgb)


def _oklab(rgb):
    """sRGB -> OKLab. Нужен, чтобы мерить различимость цветов так, как её видит глаз."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _delta_e(c1, c2):
    a, b = _oklab(c1), _oklab(c2)
    return math.dist(a, b) * 100


def separate(hex_color, taken, theme, threshold=10.0):
    """Фирменные цвета языков иногда почти совпадают (Python и TypeScript — оба синие).
    Двигаем светлоту нового цвета, пока он не станет отличим от уже занятых."""
    rgb = _rgb(hex_color.lstrip("#"))
    if not taken:
        return _hex(rgb)
    lo, hi = (60, 245) if theme == "dark" else (25, 215)
    best, best_gap = rgb, min(_delta_e(rgb, t) for t in taken)
    for direction in (1, -1):
        candidate = rgb
        for _ in range(14):
            if best_gap >= threshold:
                break
            target = 255 if direction > 0 else 0
            candidate = tuple(c + (target - c) * 0.09 for c in candidate)
            if not (lo <= _luma(candidate) <= hi):
                break
            gap = min(_delta_e(candidate, t) for t in taken)
            if gap > best_gap:
                best, best_gap = candidate, gap
    return _hex(best)


def resolve_colors(slices, theme, palette):
    """Цвет закреплён за языком, а не за его местом в списке."""
    colors, taken = {}, []
    for name, _ in slices:
        rgb = _rgb(adapt(color_for(name, palette), theme).lstrip("#"))
        final = separate(_hex(rgb), taken, theme)
        colors[name] = final
        taken.append(_rgb(final.lstrip("#")))
    return colors


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def build_svg(slices, theme, palette):
    """slices: список (язык, процент). Кольцо слева, легенда справа."""
    t = THEMES[theme]
    colors = resolve_colors(slices, theme, palette)
    circumference = 2 * math.pi * R
    parts = []

    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Распределение языков по репозиториям">'
    )
    parts.append(
        "<title>Языки: " + esc(", ".join(f"{n} {p:.1f}%" for n, p in slices)) + "</title>"
    )

    # Дорожка кольца — задаёт форму, когда сумма чуть меньше 100%
    parts.append(
        f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" '
        f'stroke="{t["muted"]}" stroke-opacity="0.14" stroke-width="{SW}"/>'
    )

    # Секторы: дуги через stroke-dasharray, разрыв поверхности вместо обводки
    parts.append(f'<g transform="rotate(-90 {CX} {CY})" stroke-linecap="butt">')
    offset = 0.0
    total = sum(p for _, p in slices) or 100.0
    for name, percent in slices:
        arc = percent / total * circumference
        drawn = max(arc - GAP_PX, 0.6)
        color = colors[name]
        parts.append(
            f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="{color}" '
            f'stroke-width="{SW}" stroke-dasharray="{drawn:.2f} {circumference - drawn:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += arc
    parts.append("</g>")

    # Крупная цифра в центре — лидирующий язык
    if slices:
        top_name, top_pct = slices[0]
        parts.append(
            f'<text x="{CX}" y="{CY - 2}" text-anchor="middle" font-family=\'{FONT}\' '
            f'font-size="27" font-weight="600" fill="{t["ink"]}">{top_pct:.0f}%</text>'
        )
        parts.append(
            f'<text x="{CX}" y="{CY + 16}" text-anchor="middle" font-family=\'{FONT}\' '
            f'font-size="11" fill="{t["muted"]}">{esc(top_name)}</text>'
        )

    # Легенда: имя и число текстом, чтобы читалось без опоры на цвет
    start_y = CY - (len(slices) * ROW_H) / 2 + ROW_H / 2
    for i, (name, percent) in enumerate(slices):
        y = start_y + i * ROW_H
        color = colors[name]
        parts.append(
            f'<rect x="{LEGEND_X}" y="{y - 5:.1f}" width="10" height="10" rx="3" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{LEGEND_X + 18}" y="{y + 4:.1f}" font-family=\'{FONT}\' font-size="13" '
            f'fill="{t["ink"]}">{esc(name)}</text>'
        )
        parts.append(
            f'<text x="{W - 16}" y="{y + 4:.1f}" text-anchor="end" font-family=\'{FONT}\' '
            f'font-size="13" fill="{t["muted"]}" '
            f'style="font-variant-numeric:tabular-nums">{percent:.1f}%</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    if not TOKEN:
        print("! GH_TOKEN не задан — приватные репозитории учтены не будут", file=sys.stderr)

    repos = fetch_repos(TOKEN)
    print(f"Найдено репозиториев: {len(repos)}")

    totals, counted = {}, 0
    for repo in repos:
        if repo.get("fork") and not INCLUDE_FORKS:
            continue
        if repo.get("name", "").lower() in EXCLUDE_REPOS:
            continue
        try:
            langs = gh(f"/repos/{repo['full_name']}/languages", TOKEN)
        except urllib.error.HTTPError as e:
            print(f"  пропуск {repo.get('name')}: HTTP {e.code}", file=sys.stderr)
            continue
        if not langs:
            continue
        counted += 1
        for lang, size in langs.items():
            if lang.lower() in EXCLUDE_LANGS:
                continue
            totals[lang] = totals.get(lang, 0) + size

    print(f"Учтено репозиториев с кодом: {counted}")
    if not totals:
        print("! языки не найдены, ничего не меняю", file=sys.stderr)
        return 1

    total_bytes = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)

    # Кольцо читается только пока секторов мало — хвост схлопываем в "Прочее"
    slices, tail = [], 0.0
    for lang, size in ranked:
        percent = size / total_bytes * 100
        if len(slices) < MAX_SLICES and percent >= MIN_PERCENT:
            slices.append((lang, percent))
        else:
            tail += percent
    if tail >= 0.05:
        slices.append((OTHER, tail))

    for name, percent in slices:
        print(f"  {name:<20} {percent:6.2f}%")

    palette = fetch_linguist_colors()
    os.makedirs(ASSETS_DIR, exist_ok=True)

    digest = hashlib.sha256()
    for theme in ("light", "dark"):
        svg = build_svg(slices, theme, palette)
        digest.update(svg.encode("utf-8"))
        path = os.path.join(ASSETS_DIR, f"langs-{theme}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"  записан {path}")

    # Хеш в query-параметре сбрасывает кеш картинок GitHub при изменении данных
    version = digest.hexdigest()[:10]
    base = f"https://raw.githubusercontent.com/{USER}/{USER}/{BRANCH}/{ASSETS_DIR}"
    alt = "Языки в моих репозиториях"
    block = (
        f"{START}\n"
        f"<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{base}/langs-dark.svg?v={version}">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="{base}/langs-light.svg?v={version}">\n'
        f'  <img alt="{alt}" src="{base}/langs-light.svg?v={version}" width="468">\n'
        f"</picture>\n"
        f"{END}"
    )

    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()

    if START not in readme or END not in readme:
        print(f"! в {README_PATH} нет маркеров. Добавь две строки:\n\n{START}\n{END}\n",
              file=sys.stderr)
        print("Готовый блок:\n")
        print(block)
        return 1

    updated = re.sub(re.escape(START) + r".*?" + re.escape(END),
                     lambda _: block, readme, flags=re.DOTALL)
    if updated != readme:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"{README_PATH} обновлён.")
    else:
        print("README без изменений.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
