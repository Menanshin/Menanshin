#!/usr/bin/env python3

import json
import os
import urllib.request
from xml.sax.saxutils import escape

USERNAME = "Menanshin"
OUTPUT_FILE = "languages.svg"

API_BASE = "https://api.github.com"
TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}

if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def github_get(url):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def get_repositories():
    repositories = []
    page = 1

    while True:
        url = (
            f"{API_BASE}/users/{USERNAME}/repos"
            f"?per_page=100&page={page}&type=owner"
        )

        data = github_get(url)

        if not data:
            break

        repositories.extend(data)

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_languages(repo_name):
    url = f"{API_BASE}/repos/{USERNAME}/{repo_name}/languages"
    return github_get(url)


def collect_languages():
    totals = {}

    for repo in get_repositories():
        if repo.get("fork"):
            continue

        languages = get_languages(repo["name"])

        for language, bytes_count in languages.items():
            totals[language] = totals.get(language, 0) + bytes_count

    return totals


def calculate_percentages(totals):
    total_bytes = sum(totals.values())

    if total_bytes == 0:
        return []

    languages = []

    for language, bytes_count in totals.items():
        percentage = bytes_count / total_bytes * 100

        if percentage >= 0.1:
            languages.append((language, percentage))

    languages.sort(key=lambda item: item[1], reverse=True)

    return languages


def generate_svg(languages):
    width = 620
    row_height = 32
    header_height = 54
    height = header_height + len(languages) * row_height + 16

    max_bar_width = 280
    label_x = 24
    bar_x = 150
    percentage_x = 590

    rows = []

    for index, (language, percentage) in enumerate(languages):
        y = header_height + index * row_height

        bar_width = max(2, max_bar_width * percentage / 100)

        rows.append(
            f"""
            <text
                x="{label_x}"
                y="{y}"
                class="language"
            >{escape(language)}</text>

            <rect
                x="{bar_x}"
                y="{y - 14}"
                width="{max_bar_width}"
                height="10"
                rx="5"
                class="bar-background"
            />

            <rect
                x="{bar_x}"
                y="{y - 14}"
                width="{bar_width:.2f}"
                height="10"
                rx="5"
                class="bar"
            />

            <text
                x="{percentage_x}"
                y="{y}"
                text-anchor="end"
                class="percentage"
            >{percentage:.1f}%</text>
            """
        )

    svg = f"""<svg
    xmlns="http://www.w3.org/2000/svg"
    width="{width}"
    height="{height}"
    viewBox="0 0 {width} {height}"
>
    <style>
        .background {{
            fill: #0d1117;
        }}

        .title {{
            fill: #f0f6fc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 16px;
            font-weight: 600;
        }}

        .language {{
            fill: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 13px;
        }}

        .percentage {{
            fill: #8b949e;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 13px;
        }}

        .bar-background {{
            fill: #21262d;
        }}

        .bar {{
            fill: #58a6ff;
        }}
    </style>

    <rect
        width="100%"
        height="100%"
        rx="8"
        class="background"
    />

    <text
        x="{label_x}"
        y="30"
        class="title"
    >Languages</text>

    {"".join(rows)}
</svg>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(svg)


if __name__ == "__main__":
    totals = collect_languages()
    languages = calculate_percentages(totals)
    generate_svg(languages)

    print("Generated languages.svg")

    for language, percentage in languages:
        print(f"{language}: {percentage:.1f}%")
