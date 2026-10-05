#!/usr/bin/env python3

import json
import os
import urllib.request
from xml.sax.saxutils import escape

USERNAME = "Menanshin"
OUTPUT_FILE = "languages.svg"

API_BASE = "https://api.github.com"
TOKEN = os.getenv("GH_PAT")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}

if not TOKEN:
    raise RuntimeError(
        "GH_PAT is not set. "
        "Create a GitHub Actions secret named GH_PAT."
    )

HEADERS["Authorization"] = f"Bearer {TOKEN}"


def github_get(url):
    request = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")

        raise RuntimeError(
            f"GitHub API error {error.code}: {body}"
        ) from error


def get_repositories():
    """
    Get all repositories owned by the authenticated user,
    including public and private repositories.
    """

    repositories = []
    page = 1

    while True:
        url = (
            f"{API_BASE}/user/repos"
            f"?per_page=100"
            f"&page={page}"
            f"&visibility=all"
            f"&affiliation=owner"
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
    """
    Get language byte statistics for a repository.
    """

    url = f"{API_BASE}/repos/{USERNAME}/{repo_name}/languages"

    return github_get(url)


def collect_languages():
    """
    Aggregate language statistics from all owned repositories.

    Fork repositories are excluded because their code can duplicate
    another repository's code and distort personal statistics.
    """

    totals = {}

    repositories = get_repositories()

    print(f"Found {len(repositories)} owned repositories")

    for repo in repositories:
        repo_name = repo["name"]

        if repo.get("fork"):
            print(f"Skipping fork: {repo_name}")
            continue

        visibility = "private" if repo.get("private") else "public"

        print(f"Processing {visibility}: {repo_name}")

        languages = get_languages(repo_name)

        for language, bytes_count in languages.items():
            totals[language] = totals.get(language, 0) + bytes_count

    return totals


def calculate_percentages(totals):
    """
    Calculate language percentages based on total bytes.

    Languages below 0.1% are not displayed,
    but remain part of the denominator.
    """

    total_bytes = sum(totals.values())

    if total_bytes == 0:
        return []

    languages = []

    for language, bytes_count in totals.items():
        percentage = bytes_count / total_bytes * 100

        if percentage >= 0.1:
            languages.append(
                (language, percentage)
            )

    languages.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    return languages


def language_color(language):
    """
    GitHub-style colors for common languages.
    """

    colors = {
        "Python": "#3572A5",
        "TypeScript": "#3178C6",
        "JavaScript": "#F1E05A",
        "Java": "#B07219",
        "Kotlin": "#A97BFF",
        "Go": "#00ADD8",
        "Rust": "#DEA584",
        "C": "#555555",
        "C++": "#F34B7D",
        "C#": "#178600",
        "PHP": "#4F5D95",
        "Ruby": "#701516",
        "Swift": "#F05138",
        "Shell": "#89E051",
        "HCL": "#844FBA",
        "Dockerfile": "#384D54",
        "HTML": "#E34C26",
        "CSS": "#563D7C",
        "SCSS": "#C6538C",
        "Vue": "#41B883",
        "Dart": "#00B4AB",
        "Lua": "#000080",
        "R": "#198CE7",
        "SQL": "#DA5B0B",
    }

    return colors.get(language, "#8B949E")


def generate_svg(languages):
    """
    Generate compact dark GitHub-style SVG.
    """

    width = 520

    header_height = 42
    row_height = 26
    bottom_padding = 12

    height = (
        header_height
        + len(languages) * row_height
        + bottom_padding
    )

    label_x = 20
    dot_x = 20
    bar_x = 132
    bar_width = 250
    percentage_x = 500

    rows = []

    for index, (language, percentage) in enumerate(languages):

        y = header_height + index * row_height

        color = language_color(language)

        # Keep very small percentages visible as a tiny dot.
        fill_width = max(
            3,
            bar_width * percentage / 100,
        )

        rows.append(
            f"""
            <circle
                cx="{dot_x}"
                cy="{y - 5}"
                r="4"
                fill="{color}"
            />

            <text
                x="{label_x + 12}"
                y="{y}"
                class="language"
            >{escape(language)}</text>

            <rect
                x="{bar_x}"
                y="{y - 12}"
                width="{bar_width}"
                height="8"
                rx="4"
                class="bar-background"
            />

            <rect
                x="{bar_x}"
                y="{y - 12}"
                width="{fill_width:.2f}"
                height="8"
                rx="4"
                fill="{color}"
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
            stroke: #21262d;
            stroke-width: 1;
        }}

        .title {{
            fill: #f0f6fc;
            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            font-size: 16px;
            font-weight: 600;
        }}

        .language {{
            fill: #c9d1d9;
            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            font-size: 12px;
        }}

        .percentage {{
            fill: #8b949e;
            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            font-size: 12px;
        }}

        .bar-background {{
            fill: #21262d;
        }}
    </style>

    <rect
        x="0.5"
        y="0.5"
        width="{width - 1}"
        height="{height - 1}"
        rx="7"
        class="background"
    />

    <text
        x="{label_x}"
        y="27"
        class="title"
    >Languages</text>

    {"".join(rows)}
</svg>
"""

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(svg)


def main():
    print("Collecting GitHub language statistics...")

    totals = collect_languages()

    languages = calculate_percentages(totals)

    if not languages:
        raise RuntimeError(
            "No language statistics found."
        )

    generate_svg(languages)

    print("")
    print("Generated languages.svg")
    print("")

    for language, percentage in languages:
        print(
            f"{language:15} {percentage:5.1f}%"
        )


if __name__ == "__main__":
    main()
