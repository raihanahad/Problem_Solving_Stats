#!/usr/bin/env python3
"""Update the existing Problem_Solving_Stats README from public profile data.

The script intentionally keeps the last known count whenever a site cannot be
queried or its response cannot be parsed confidently. No passwords or API
secrets are required for the configured public endpoints.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
DATA_PATH = ROOT / "data" / "last_known_counts.json"
BDT = ZoneInfo("Asia/Dhaka")
UTC = timezone.utc

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (compatible; ProblemSolvingStatsBot/1.0; "
            "+https://github.com/raihanahad/Problem_Solving_Stats)"
        ),
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
)
TIMEOUT = 25

PLATFORMS: dict[str, dict[str, Any]] = {
    "codeforces": {
        "label": "Codeforces",
        "username": "RAIHAN_AHAD",
        "url": "https://codeforces.com/profile/RAIHAN_AHAD",
        "method": "automatic",
    },
    "vjudge": {
        "label": "VJudge",
        "username": "RAIHAN_AHAD",
        "url": "https://vjudge.net/user/RAIHAN_AHAD",
        "method": "automatic",
    },
    "codechef": {
        "label": "CodeChef",
        "username": "raihan_ahad",
        "url": "https://www.codechef.com/users/raihan_ahad",
        "method": "automatic",
    },
    "atcoder": {
        "label": "AtCoder",
        "username": "RAIHAN_AHAD",
        "url": "https://atcoder.jp/users/RAIHAN_AHAD",
        "method": "automatic",
    },
    "cses": {
        "label": "CSES",
        "username": "458666",
        "url": "https://cses.fi/user/458666",
        "method": "manual",
    },
    "hackerrank": {
        "label": "HackerRank",
        "username": "raihanahad",
        "url": "https://www.hackerrank.com/profile/raihanahad",
        "method": "manual",
    },
    "leetcode": {
        "label": "LeetCode",
        "username": "RAIHAN_AHAD",
        "url": "https://leetcode.com/u/RAIHAN_AHAD/",
        "method": "automatic",
    },
    "beecrowd": {
        "label": "beecrowd",
        "username": "1249238",
        "url": "https://judge.beecrowd.com/en/profile/1249238/",
        "method": "automatic",
    },
}


def get_json(url: str, *, params: dict[str, Any] | None = None,
             body: dict[str, Any] | None = None) -> Any:
    if body is not None:
        response = SESSION.post(url, json=body, timeout=TIMEOUT)
    else:
        response = SESSION.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_text(url: str) -> str:
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def accepted_time(epoch: Any) -> int | None:
    try:
        value = int(epoch)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_codeforces() -> dict[str, Any]:
    """Count unique accepted Codeforces problems via the official API."""
    payload = get_json(
        "https://codeforces.com/api/user.status",
        params={"handle": PLATFORMS["codeforces"]["username"], "from": 1, "count": 10000},
    )
    if payload.get("status") != "OK" or not isinstance(payload.get("result"), list):
        raise ValueError("Codeforces API returned an unexpected response")

    submissions = payload["result"]
    # Do not publish a potentially incomplete count if the API page is capped.
    if len(submissions) >= 10000:
        raise ValueError("Codeforces returned its 10,000-submission limit; retaining previous count")

    solved: set[str] = set()
    latest: int | None = None
    for submission in submissions:
        if submission.get("verdict") != "OK":
            continue
        problem = submission.get("problem") or {}
        contest_id = problem.get("contestId")
        index = problem.get("index")
        name = f"{contest_id}:{index}" if contest_id is not None and index else problem.get("problemsetName")
        if name:
            solved.add(str(name))
        stamp = accepted_time(submission.get("creationTimeSeconds"))
        if stamp and (latest is None or stamp > latest):
            latest = stamp
    return {"count": len(solved), "latest_epoch": latest}


def fetch_vjudge() -> dict[str, Any]:
    """Use VJudge's public solve-detail endpoint; keep old value if blocked."""
    payload = get_json(f"https://vjudge.net/user/solveDetail/{PLATFORMS['vjudge']['username']}")
    records = payload.get("acRecords") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        raise ValueError("VJudge response did not contain acRecords")
    total = 0
    recognized = 0
    for problems in records.values():
        if isinstance(problems, list):
            total += len({str(item) for item in problems})
            recognized += 1
    if recognized == 0:
        raise ValueError("VJudge response had no recognized accepted-problem lists")
    return {"count": total, "latest_epoch": None}


def fetch_codechef() -> dict[str, Any]:
    """Read the total-solved value from CodeChef's public profile HTML."""
    html = get_text(PLATFORMS["codechef"]["url"])
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.stripped_strings)
    patterns = [
        r"Total\s+Problems\s+Solved\s*[:\-]?\s*(\d{1,6})",
        r"Problems\s+Solved\s*[:\-]?\s*(\d{1,6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"count": int(match.group(1)), "latest_epoch": None}

    # Some page versions put the label and count in separate neighboring nodes.
    for node in soup.find_all(string=re.compile(r"Total\s+Problems\s+Solved", re.I)):
        parent = node.parent
        for _ in range(3):
            if parent is None:
                break
            nearby = " ".join(parent.stripped_strings)
            match = re.search(
                r"Total\s+Problems\s+Solved\D{0,20}(\d{1,6})",
                nearby,
                flags=re.IGNORECASE,
            )
            if match:
                return {"count": int(match.group(1)), "latest_epoch": None}
            parent = parent.parent
    raise ValueError("Could not confidently locate CodeChef's solved count in profile HTML")


def fetch_atcoder() -> dict[str, Any]:
    """Count unique accepted AtCoder problems using the AtCoder Problems API."""
    username = PLATFORMS["atcoder"]["username"]
    endpoint = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
    from_second = 0
    seen_submission_ids: set[str] = set()
    solved: set[str] = set()
    latest: int | None = None

    # The endpoint returns up to 500 submissions per request. Page carefully;
    # this API asks clients not to send requests more frequently than once/sec.
    for page in range(30):
        payload = get_json(endpoint, params={"user": username, "from_second": from_second})
        if not isinstance(payload, list):
            raise ValueError("AtCoder Problems API returned an unexpected response")
        if not payload:
            break

        new_ids = 0
        page_epochs: list[int] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            submission_id = str(item.get("id", ""))
            if not submission_id:
                submission_id = f"{item.get('epoch_second')}:{item.get('problem_id')}:{item.get('result')}"
            if submission_id not in seen_submission_ids:
                seen_submission_ids.add(submission_id)
                new_ids += 1
            epoch = accepted_time(item.get("epoch_second"))
            if epoch:
                page_epochs.append(epoch)
            result = str(item.get("result", "")).upper()
            if result in {"AC", "1", "ACCEPTED"}:
                problem_id = item.get("problem_id")
                if problem_id:
                    solved.add(str(problem_id))
                if epoch and (latest is None or epoch > latest):
                    latest = epoch

        if len(payload) < 500:
            break
        if not page_epochs:
            raise ValueError("AtCoder submission page did not contain timestamps")
        newest = max(page_epochs)
        # Avoid looping indefinitely if an API page repeats the same records.
        if new_ids == 0 and newest <= from_second:
            raise ValueError("AtCoder API pagination did not advance")
        from_second = newest
        time.sleep(1.1)
    else:
        raise ValueError("AtCoder pagination exceeded safety limit; retaining previous count")

    return {"count": len(solved), "latest_epoch": latest}


def fetch_leetcode() -> dict[str, Any]:
    """Use LeetCode's public GraphQL profile query."""
    query = """
    query userStats($username: String!) {
      matchedUser(username: $username) {
        username
        submitStats {
          acSubmissionNum { difficulty count submissions }
        }
      }
      recentAcSubmissionList(username: $username, limit: 20) {
        id title titleSlug timestamp statusDisplay
      }
    }
    """
    payload = get_json(
        "https://leetcode.com/graphql",
        body={"query": query, "variables": {"username": PLATFORMS["leetcode"]["username"]}},
    )
    if payload.get("errors"):
        raise ValueError("LeetCode GraphQL returned errors")
    data = payload.get("data") or {}
    user = data.get("matchedUser")
    if not isinstance(user, dict):
        raise ValueError("LeetCode did not return a public user profile")
    stats = (user.get("submitStats") or {}).get("acSubmissionNum") or []
    all_count = next((item.get("count") for item in stats if item.get("difficulty") == "All"), None)
    if all_count is None:
        raise ValueError("LeetCode response did not contain the overall accepted count")

    latest: int | None = None
    recent = data.get("recentAcSubmissionList") or []
    for submission in recent:
        if str(submission.get("statusDisplay", "")).lower() == "accepted":
            stamp = accepted_time(submission.get("timestamp"))
            if stamp and (latest is None or stamp > latest):
                latest = stamp
    return {"count": int(all_count), "latest_epoch": latest}


def fetch_beecrowd() -> dict[str, Any]:
    """Try to read the solved-problem total from the public beecrowd profile."""
    html = get_text(PLATFORMS["beecrowd"]["url"])
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", " ".join(soup.stripped_strings))
    patterns = [
        r"(?:solved\s+problems|problems\s+solved)\D{0,25}(\d{1,6})",
        r"(\d{1,6})\s+(?:solved\s+problems|problems\s+solved)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"count": int(match.group(1)), "latest_epoch": None}
    raise ValueError("Could not confidently locate beecrowd's solved count in profile HTML")


FETCHERS = {
    "codeforces": fetch_codeforces,
    "vjudge": fetch_vjudge,
    "codechef": fetch_codechef,
    "atcoder": fetch_atcoder,
    "leetcode": fetch_leetcode,
    "beecrowd": fetch_beecrowd,
}


def load_state() -> dict[str, Any]:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        state = json.load(file)
    if not isinstance(state.get("platforms"), dict):
        raise ValueError("Invalid data/last_known_counts.json: missing platforms object")
    for key, config in PLATFORMS.items():
        state["platforms"].setdefault(
            key,
            {"count": 0, "last_updated": "Not updated yet", "tracking": config["method"]},
        )
        state["platforms"][key]["tracking"] = config["method"]
    return state


def format_percent(value: float) -> str:
    return f"{value:.2f}%"


def replace_row_badge(cell: str, percent: float) -> str:
    return re.sub(
        r"(https://img\.shields\.io/badge/)\d+(?:\.\d+)?%25",
        lambda match: match.group(1) + f"{percent:.2f}%25",
        cell,
        count=1,
    )


def update_stats_table(readme: str, state: dict[str, Any], successful: set[str], today: str) -> str:
    platform_state = state["platforms"]
    total = sum(max(0, int(platform_state[key].get("count", 0))) for key in PLATFORMS)
    lines = readme.splitlines()
    in_table = False

    for i, line in enumerate(lines):
        if "AUTO_GENERATED_SECTION_START: STATS_TABLE" in line:
            in_table = True
            continue
        if "AUTO_GENERATED_SECTION_END: STATS_TABLE" in line:
            in_table = False
            continue
        if not in_table or not line.startswith("|"):
            continue

        cells = line.split("|")
        if len(cells) < 8:
            continue

        row_label = cells[1]
        matched_key = next(
            (key for key, config in PLATFORMS.items() if f"**{config['label']}**" in row_label),
            None,
        )
        if matched_key:
            count = max(0, int(platform_state[matched_key].get("count", 0)))
            share = (count / total * 100) if total else 0.0
            cells[3] = f" **{count}** "
            cells[4] = replace_row_badge(cells[4], share)
            if matched_key in successful:
                cells[5] = f" {today} "
            if PLATFORMS[matched_key]["method"] == "automatic":
                cells[6] = " ![Automatic](https://img.shields.io/badge/AUTO-2E7D32?style=flat) "
            else:
                cells[6] = " ![Manual](https://img.shields.io/badge/MANUAL-E65100?style=flat) "
            lines[i] = "|".join(cells)
            continue

        if row_label.strip() == "**TOTAL**":
            cells[2] = f" **{len(PLATFORMS)} Platforms** "
            cells[3] = f" **{total}** "
            cells[4] = " **100%** " if total else " **0%** "
            if successful:
                cells[5] = f" {today} "
            cells[6] = " **Mixed** "
            lines[i] = "|".join(cells)

    return "\n".join(lines) + ("\n" if readme.endswith("\n") else "")


def update_readme(readme: str, state: dict[str, Any], successful: set[str], now: datetime) -> str:
    counts = {key: int(value.get("count", 0)) for key, value in state["platforms"].items()}
    total = sum(max(0, count) for count in counts.values())
    today = now.strftime("%b %d, %Y")
    leader_key = max(PLATFORMS, key=lambda key: counts.get(key, 0))
    leader = PLATFORMS[leader_key]["label"]
    leader_url = PLATFORMS[leader_key]["url"]
    leader_badge = re.sub(r"[^A-Za-z0-9]", "", leader).upper()

    # Top badges.
    readme = re.sub(
        r"(!\[Last Updated\]\(https://img\.shields\.io/badge/Last%20Updated-)[^)]+(\))",
        lambda m: m.group(1) + now.strftime("%B%%20%d,%%20%Y") + "-77DDBB?style=for-the-badge&labelColor=161B22" + m.group(2),
        readme,
        count=1,
    )
    readme = re.sub(
        r"(!\[Total Problems\]\(https://img\.shields\.io/badge/Total%20Solved-)\d+(-77DDBB\?style=for-the-badge&labelColor=161B22\))",
        rf"\g<1>{total}\g<2>",
        readme,
        count=1,
    )

    # Synchronization line.
    sync_line = (
        '<p align="center">\n'
        f'  <sub><strong>Last Synchronized:</strong> {now.strftime("%d %B %Y at %I:%M:%S %p")} '
        '• Automatic</sub>\n'
        '</p>'
    )
    readme = re.sub(
        r"<!-- UPDATE_METADATA_START -->.*?<!-- UPDATE_METADATA_END -->",
        "<!-- UPDATE_METADATA_START -->\n" + sync_line + "\n<!-- UPDATE_METADATA_END -->",
        readme,
        count=1,
        flags=re.DOTALL,
    )

    # Overview total.
    readme = re.sub(
        r"<strong>\s*\d+\s*</strong>(\s*<br\s*/?>\s*<sub>Recorded Solves</sub>)",
        lambda m: f"<strong>{total}</strong>{m.group(1)}",
        readme,
        count=1,
        flags=re.IGNORECASE,
    )
    # Overview's leading platform card follows the currently highest count.
    readme = re.sub(
        r"<strong>[^<]+</strong>\s*<br\s*/?>\s*<sub>\d+ Recorded Solves</sub>",
        f"<strong>{leader}</strong>\n      <br/>\n      <sub>{counts[leader_key]} Recorded Solves</sub>",
        readme,
        count=1,
        flags=re.IGNORECASE,
    )

    # Highlights values under their existing captions.
    readme = re.sub(
        r"<strong>\d+ Problems</strong>(\s*<br\s*/?>\s*<sub>Highest recorded solve count</sub>)",
        lambda m: f"<strong>{counts[leader_key]} Problems</strong>{m.group(1)}",
        readme,
        count=1,
        flags=re.IGNORECASE,
    )
    readme = re.sub(
        r"<strong>\d+ Problems</strong>(\s*<br\s*/?>\s*<sub>Competitive programming practice</sub>)",
        lambda m: f"<strong>{counts['codeforces']} Problems</strong>{m.group(1)}",
        readme,
        count=1,
        flags=re.IGNORECASE,
    )
    readme = re.sub(
        r"<strong>\d+ Platforms</strong>(\s*<br\s*/?>\s*<sub>Learning across multiple judges</sub>)",
        lambda m: f"<strong>{len(PLATFORMS)} Platforms</strong>{m.group(1)}",
        readme,
        count=1,
        flags=re.IGNORECASE,
    )

    # Keep the first Highlights card linked to the current leading platform.
    highlights_pattern = r"<!-- AUTO_GENERATED_SECTION_START: KEY_HIGHLIGHTS -->.*?<!-- AUTO_GENERATED_SECTION_END: KEY_HIGHLIGHTS -->"
    highlights_match = re.search(highlights_pattern, readme, flags=re.DOTALL)
    if highlights_match:
        section = highlights_match.group(0)
        section = re.sub(
            r'(<a href=")[^"]+("\s*>\s*<img src="https://img\.shields\.io/badge/)[A-Z0-9%_-]+(-77DDBB\?style=for-the-badge&labelColor=161B22")',
            lambda m: m.group(1) + leader_url + m.group(2) + leader_badge + m.group(3),
            section,
            count=1,
        )
        section = re.sub(r'alt="CodeChef"', f'alt="{leader}"', section, count=1)
        readme = readme[:highlights_match.start()] + section + readme[highlights_match.end():]

    # Statistics table, including the total and each platform share.
    readme = update_stats_table(readme, state, successful, today)

    # Latest solve: use the latest accepted submission returned by a provider.
    latest = state.get("latest_solve") or {}
    platform = str(latest.get("platform", "Codeforces"))
    date = str(latest.get("date", "October 09, 2026"))
    readme = re.sub(
        r"(LATEST%20SOLVE-)[A-Z0-9%_-]+(-77DDBB)",
        lambda m: m.group(1) + re.sub(r"[^A-Za-z0-9]", "", platform).upper() + m.group(2),
        readme,
        count=1,
    )
    # Replace date only within the Latest Solve generated section.
    pattern = r"(<!-- AUTO_GENERATED_SECTION_START: LATEST_SOLVE -->.*?<strong>).*?(</strong>.*?<!-- AUTO_GENERATED_SECTION_END: LATEST_SOLVE -->)"
    readme = re.sub(pattern, lambda m: m.group(1) + date + m.group(2), readme, count=1, flags=re.DOTALL)
    # Keep Latest Solve link pointing at the platform that supplied the latest AC.
    url = PLATFORMS.get(next((key for key, item in PLATFORMS.items() if item["label"].lower() == platform.lower()), "codeforces"), PLATFORMS["codeforces"])["url"]
    latest_section_pattern = r"<!-- AUTO_GENERATED_SECTION_START: LATEST_SOLVE -->.*?<!-- AUTO_GENERATED_SECTION_END: LATEST_SOLVE -->"
    section_match = re.search(latest_section_pattern, readme, flags=re.DOTALL)
    if section_match:
        section = section_match.group(0)
        section = re.sub(r'(href=")[^"]+(")', lambda m: m.group(1) + url + m.group(2), section)
        section = re.sub(r'alt="Latest Solve on [^"]+"', f'alt="Latest Solve on {platform}"', section, count=1)
        section = re.sub(r'View [^<]+ Profile ↗', f'View {platform} Profile ↗', section, count=1)
        readme = readme[:section_match.start()] + section + readme[section_match.end():]

    return readme


def parse_date_midnight(value: str) -> int | None:
    try:
        dt = datetime.strptime(value, "%B %d, %Y").replace(tzinfo=BDT)
        return int(dt.timestamp())
    except (TypeError, ValueError):
        return None


def main() -> int:
    if not README_PATH.exists():
        print("ERROR: README.md was not found at repository root.", file=sys.stderr)
        return 1
    if not DATA_PATH.exists():
        print("ERROR: data/last_known_counts.json was not found.", file=sys.stderr)
        return 1

    state = load_state()
    original_readme = README_PATH.read_text(encoding="utf-8")
    original_state = json.dumps(state, sort_keys=True, ensure_ascii=False)
    now = datetime.now(BDT)
    today_long = now.strftime("%B %d, %Y")
    successful: set[str] = set()
    latest_candidates: list[tuple[int, str]] = []

    for key, fetcher in FETCHERS.items():
        try:
            result = fetcher()
            count = int(result["count"])
            if count < 0:
                raise ValueError("Fetched a negative count")
            state["platforms"][key]["count"] = count
            state["platforms"][key]["last_updated"] = today_long
            successful.add(key)
            stamp = accepted_time(result.get("latest_epoch"))
            if stamp:
                latest_candidates.append((stamp, PLATFORMS[key]["label"]))
            print(f"OK  {PLATFORMS[key]['label']}: {count} solved")
        except Exception as exc:  # One failing site must not block other platforms.
            print(
                f"WARN {PLATFORMS[key]['label']}: {type(exc).__name__}: {exc}. "
                "Keeping the last known count."
            )

    if not successful:
        print("No source returned usable data; leaving README and counts file unchanged.")
        return 0

    # Update the latest-solve section only if a provider returned an accepted
    # timestamp that is not older than the currently recorded latest-solve date.
    latest = state.get("latest_solve") or {}
    baseline_epoch = accepted_time(latest.get("timestamp"))
    if baseline_epoch is None:
        baseline_epoch = parse_date_midnight(str(latest.get("date", "")))
    if latest_candidates:
        candidate_epoch, candidate_platform = max(latest_candidates, key=lambda item: item[0])
        if baseline_epoch is None or candidate_epoch >= baseline_epoch:
            stamp_dt = datetime.fromtimestamp(candidate_epoch, tz=UTC).astimezone(BDT)
            state["latest_solve"] = {
                "platform": candidate_platform,
                "date": stamp_dt.strftime("%B %d, %Y"),
                "timestamp": candidate_epoch,
            }

    state["last_run_at"] = now.isoformat(timespec="seconds")
    updated_readme = update_readme(original_readme, state, successful, now)

    # Store state as readable JSON for later runs and manual troubleshooting.
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if updated_readme != original_readme:
        README_PATH.write_text(updated_readme, encoding="utf-8")
        print("README.md updated.")
    else:
        print("README.md did not need a content update.")

    new_state = json.dumps(state, sort_keys=True, ensure_ascii=False)
    print(f"Successful platform sources: {len(successful)}/{len(FETCHERS)}")
    print(f"Recorded total across platforms: {sum(int(item.get('count', 0)) for item in state['platforms'].values())}")
    print("Note: platform counts can overlap; the total is the sum of recorded platform counts.")
    if new_state == original_state and updated_readme == original_readme:
        print("No changes were necessary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
