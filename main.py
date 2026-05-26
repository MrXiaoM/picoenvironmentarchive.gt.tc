from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

import BrowserManagement


BASE_URL = "https://picoenvironmentarchive.gt.tc/"
THEMES_URL = urljoin(BASE_URL, "themes.json")
ENVIRONMENT_URL_TEMPLATE = urljoin(BASE_URL, "environments/{id}.html")

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
ENVIRONMENTS_DIR = DATA_DIR / "environments"
THEMES_DIR = DATA_DIR / "themes"
IMAGES_DIR = DATA_DIR / "images"

PAGE_LOAD_TIMEOUT_SECONDS = 60
PAGE_SETTLE_SECONDS = 1
IMAGE_REQUEST_TIMEOUT_SECONDS = 30
WEBP_QUALITY = 82


@dataclass(slots=True)
class BackupFailure:
    theme_id: Any
    title: str
    error: str


def ensure_data_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ENVIRONMENTS_DIR.mkdir(parents=True, exist_ok=True)
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def wait_for_page_loaded(tab: Any, timeout_seconds: int = PAGE_LOAD_TIMEOUT_SECONDS) -> None:
    deadline = monotonic() + timeout_seconds

    while tab.states.is_loading:
        if monotonic() > deadline:
            raise TimeoutError(f"Page did not finish loading within {timeout_seconds} seconds")
        sleep(0.5)

    sleep(PAGE_SETTLE_SECONDS)


def get_body_text(tab: Any) -> str:
    body = tab.ele("tag:body", timeout=10)
    if body is None:
        return ""
    return body.text.strip()


def get_page_html(tab: Any, url: str) -> str:
    tab.get(url)
    wait_for_page_loaded(tab)
    return str(tab.html)


def get_page_text(tab: Any, url: str) -> str:
    tab.get(url)
    wait_for_page_loaded(tab)
    return get_body_text(tab)


def fetch_themes(tab: Any) -> list[dict[str, Any]]:
    text = get_page_text(tab, THEMES_URL)

    try:
        themes = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:500].replace("\n", " ")
        raise ValueError(f"Failed to parse themes JSON. Preview: {preview!r}") from exc

    if not isinstance(themes, list):
        raise ValueError(f"{THEMES_URL} did not return a JSON array")

    for index, theme in enumerate(themes):
        if not isinstance(theme, dict):
            raise ValueError(f"Theme at index {index} is not a JSON object")
        if "id" not in theme:
            raise ValueError(f"Theme at index {index} is missing required field: id")

    write_json(DATA_DIR / "themes.original.json", themes)
    return themes


def fetch_environment_html(tab: Any, theme_id: Any) -> str:
    url = ENVIRONMENT_URL_TEMPLATE.format(id=theme_id)
    return get_page_html(tab, url)


def extract_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    author_tag = soup.find(
        lambda tag: tag.name == "p" and "Author:" in tag.get_text(" ", strip=True)
    )
    images_tag = soup.find(
        lambda tag: tag.name == "h3" and "Images" in tag.get_text(" ", strip=True)
    )

    if author_tag is None or images_tag is None:
        return ""

    pieces: list[str] = []
    for node in author_tag.next_siblings:
        if node == images_tag:
            break
        if getattr(node, "name", None) == "p":
            text = node.get_text(" ", strip=True)
            if text:
                pieces.append(text)
        elif isinstance(node, str):
            text = node.strip()
            if text:
                pieces.append(text)

    return " ".join(pieces).strip()


def extract_download_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    download_links = [
        anchor
        for anchor in soup.find_all("a")
        if anchor.get_text(strip=True) == "Download File" and anchor.get("href")
    ]

    if not download_links:
        raise ValueError("No <a> tag with text 'Download File' and href was found")

    href = str(download_links[-1]["href"])
    return urljoin(page_url, href)


def build_theme_backup(theme: dict[str, Any], html: str) -> dict[str, Any]:
    theme_id = theme["id"]
    page_url = ENVIRONMENT_URL_TEMPLATE.format(id=theme_id)
    return {
        **theme,
        "description": extract_description(html),
        "downloadUrl": extract_download_url(html, page_url),
    }


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def is_theme_already_backed_up(theme_id: Any) -> bool:
    return (ENVIRONMENTS_DIR / f"{theme_id}.html").is_file() and (
        THEMES_DIR / f"{theme_id}.json"
    ).is_file()


def read_theme_backup(theme_id: Any) -> dict[str, Any]:
    path = THEMES_DIR / f"{theme_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_environment_html(theme_id: Any) -> str:
    path = ENVIRONMENTS_DIR / f"{theme_id}.html"
    return path.read_text(encoding="utf-8")


def build_merged_themes_json(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_themes: list[dict[str, Any]] = []

    for theme in themes:
        theme_id = theme["id"]
        theme_backup_path = THEMES_DIR / f"{theme_id}.json"
        if not theme_backup_path.is_file():
            raise FileNotFoundError(f"Missing theme backup file: {theme_backup_path}")
        merged_themes.append(read_theme_backup(theme_id))

    write_json(DATA_DIR / "themes.json", merged_themes)
    return merged_themes


def backup_theme_image(theme: dict[str, Any]) -> None:
    theme_id = theme["id"]
    image_path = IMAGES_DIR / f"{theme_id}.webp"
    if image_path.is_file():
        print("  IMAGE SKIPPED: local WebP already exists")
        return

    source_image_path = next(
        (
            candidate
            for candidate in (
                IMAGES_DIR / f"{theme_id}.png",
                IMAGES_DIR / f"{theme_id}.jpg",
                IMAGES_DIR / f"{theme_id}.jpeg",
            )
            if candidate.is_file()
        ),
        None,
    )

    if source_image_path is not None:
        with Image.open(source_image_path) as image:
            image.save(image_path, format="WEBP", quality=WEBP_QUALITY, method=6)
        print(f"  IMAGE CONVERTED: {source_image_path.name} -> {image_path}")
        return

    primary_image_url = theme.get("primaryImageUrl")
    if not isinstance(primary_image_url, str) or not primary_image_url:
        raise ValueError("Theme is missing primaryImageUrl")

    response = requests.get(primary_image_url, timeout=IMAGE_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    with Image.open(BytesIO(response.content)) as image:
        image.save(image_path, format="WEBP", quality=WEBP_QUALITY, method=6)

    print(f"  IMAGE SAVED: {image_path}")


def backup_theme(tab: Any, theme: dict[str, Any]) -> BackupFailure | None:
    theme_id = theme["id"]
    title = str(theme.get("title", ""))

    try:
        backup_theme_image(theme)

        if is_theme_already_backed_up(theme_id):
            html = read_environment_html(theme_id)
            theme_backup = build_theme_backup(theme, html)
            write_json(THEMES_DIR / f"{theme_id}.json", theme_backup)
            print("  SKIPPED: local backup already exists; metadata refreshed")
            return None

        html = fetch_environment_html(tab, theme_id)
        write_text(ENVIRONMENTS_DIR / f"{theme_id}.html", html)

        theme_backup = build_theme_backup(theme, html)
        write_json(THEMES_DIR / f"{theme_id}.json", theme_backup)
    except Exception as exc:  # noqa: BLE001 - keep backing up remaining themes.
        return BackupFailure(theme_id=theme_id, title=title, error=str(exc))

    return None


def backup() -> int:
    ensure_data_directories()

    browser = None
    try:
        print("Starting browser with DrissionPage...")
        browser = BrowserManagement.create()
        print("Browser setup complete.")
        print("Version:", browser.version)
        print("Process ID:", browser.process_id)
        print("User Data Path:", browser.user_data_path)

        tab = browser.latest_tab
        tab.run_cdp("Network.clearBrowserCookies")

        print(f"Fetching theme list: {THEMES_URL}")
        themes = fetch_themes(tab)
        print(f"Saved {len(themes)} original themes to {DATA_DIR / 'themes.original.json'}")

        failures: list[BackupFailure] = []
        skipped_count = 0
        for index, theme in enumerate(themes, start=1):
            theme_id = theme["id"]
            title = theme.get("title", "")
            print(f"[{index}/{len(themes)}] Backing up theme {theme_id}: {title}")

            was_already_backed_up = is_theme_already_backed_up(theme_id)
            failure = backup_theme(tab, theme)
            if failure is not None:
                failures.append(failure)
                print(f"  FAILED: {failure.error}", file=sys.stderr)
            elif was_already_backed_up:
                skipped_count += 1

        print(
            f"Completed: {len(themes) - skipped_count - len(failures)} downloaded, "
            f"{skipped_count} skipped, {len(failures)} failed"
        )

        if not failures:
            merged_themes = build_merged_themes_json(themes)
            print(f"Saved {len(merged_themes)} merged themes to {DATA_DIR / 'themes.json'}")

        if failures:
            print("Failures:", file=sys.stderr)
            for failure in failures:
                print(
                    f"- id={failure.theme_id!r}, title={failure.title!r}: {failure.error}",
                    file=sys.stderr,
                )
            return 1

        return 0
    finally:
        if browser is not None:
            browser.quit()


def main() -> None:
    raise SystemExit(backup())


if __name__ == "__main__":
    main()
