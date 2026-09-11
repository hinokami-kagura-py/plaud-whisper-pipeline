"""
Plaud audio download -> Whisper transcription -> markdown pipeline.

Downloads audio for Plaud recordings via the `plaud` CLI, transcribes them
locally with OpenAI Whisper (optionally on GPU), and writes a markdown
transcript plus a lightweight review-criteria file for each recording.

Prerequisites:
    npm install -g @plaud-ai/cli
    plaud login
    pip install -r requirements.txt
    ffmpeg must be on PATH (required by Whisper for audio decoding)

Usage:
    python plaud_pipeline.py                     # process only new/unprocessed recordings
    python plaud_pipeline.py --all-force          # reprocess every recording
    python plaud_pipeline.py --file-id <id>       # force-reprocess a single recording
    python plaud_pipeline.py --model medium       # use a different Whisper model size
    python plaud_pipeline.py --data-dir D:\\plaud  # change the output location
"""

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PLACEHOLDER_MARKERS = ("Pending transcription", "Awaiting audio download")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium", "large"],
                         help="Whisper model size (default: small)")
    parser.add_argument("--data-dir", default="./plaud_data",
                         help="Root output directory; audio+transcripts go to <data-dir>/raw, "
                              "criteria files to <data-dir>/judgement, logs to <data-dir>/logs "
                              "(default: ./plaud_data)")
    parser.add_argument("--all-force", action="store_true",
                         help="Reprocess every recording, even ones already transcribed")
    parser.add_argument("--file-id", default=None,
                         help="Only process this specific recording id, forcing reprocessing")
    parser.add_argument("--language", default="ja", help="Language code passed to Whisper (default: ja)")
    return parser.parse_args()


def log(msg: str, log_file: Path):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def preflight_check(log_file: Path):
    problems = []
    if shutil.which("plaud") is None:
        problems.append("`plaud` command not found. Run `npm install -g @plaud-ai/cli` and `plaud login`.")
    if shutil.which("ffmpeg") is None:
        problems.append("`ffmpeg` not found on PATH. Whisper needs it to decode audio.")
    try:
        import whisper  # noqa: F401
    except ImportError:
        problems.append("Python package `openai-whisper` not found. Run `pip install -r requirements.txt`.")

    if problems:
        for p in problems:
            log(f"ERROR: {p}", log_file)
        sys.exit(1)


def run_plaud(args: list[str]):
    plaud_path = shutil.which("plaud")
    cmd = ["cmd", "/c", plaud_path] + args if plaud_path.lower().endswith((".cmd", ".bat")) else [plaud_path] + args
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def list_recordings(log_file: Path):
    result = run_plaud(["files", "--page-size", "100"])
    if result.returncode != 0:
        log(f"ERROR: plaud files failed: {result.stderr}", log_file)
        sys.exit(1)

    recordings = []
    started = False
    for line in result.stdout.splitlines():
        if re.match(r"\s*ID\s+NAME\s+DATE\s+DURATION", line):
            started = True
            continue
        if not started:
            continue
        if re.match(r"\s*\W+\s*$", line) or not line.strip():
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 4:
            continue
        file_id, name, date, duration = parts[0], parts[1], parts[2], parts[3]
        recordings.append({"id": file_id, "name": name, "date": date, "duration": duration})
    return recordings


def safe_stem(name: str) -> str:
    return name.replace(":", "").replace(" ", "_")


def target_paths(raw_dir: Path, judgement_dir: Path, name: str):
    stem = safe_stem(name)
    return raw_dir / f"{stem}.md", judgement_dir / f"{stem}_criteria.md"


def needs_processing(md_path: Path) -> bool:
    if not md_path.exists():
        return True
    content = md_path.read_text(encoding="utf-8", errors="replace")
    return any(marker in content for marker in PLACEHOLDER_MARKERS)


def get_audio_url(file_id: str, log_file: Path):
    result = run_plaud(["audio", file_id])
    if result.returncode != 0:
        log(f"ERROR: plaud audio {file_id} failed: {result.stderr}", log_file)
        return None
    match = re.search(r"https://\S+", result.stdout)
    if not match:
        log(f"ERROR: could not find audio URL in output for {file_id}", log_file)
        return None
    return match.group(0)


def download_audio(url: str, dest: Path, log_file: Path) -> bool:
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        log(f"ERROR: audio download failed: {e}", log_file)
        return False


def transcribe(audio_path: Path, model, language: str, log_file: Path):
    try:
        result = model.transcribe(str(audio_path), language=language)
        return result["text"].strip()
    except Exception as e:
        log(f"ERROR: whisper transcription failed: {e}", log_file)
        return None


def write_markdown(md_path: Path, recording: dict, transcript_text: str, model_name: str):
    content = f"""# {recording['name']}

**Recording ID:** {recording['id']}
**Duration:** {recording['duration']}
**Transcribed at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Whisper model:** {model_name}

## Transcript

{transcript_text}

## Metadata

- ID: {recording['id']}
- Date: {recording['date']}
"""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(content, encoding="utf-8")


def write_criteria(criteria_path: Path, recording: dict, transcript_text: str):
    content = f"""# Review checklist -- {recording['name']}

**Recording ID:** {recording['id']}
**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Basic info

- Character count: {len(transcript_text)}
- Approx. word count: {len(transcript_text.split())}
- Duration: {recording['duration']}

## Review checklist

- [ ] Transcript matches the actual recording content
- [ ] No misrecognized names or technical terms
- [ ] Decide whether a summary / action items are needed
- [ ] No sensitive information is exposed

## Notes

(fill in after review)
"""
    criteria_path.parent.mkdir(parents=True, exist_ok=True)
    criteria_path.write_text(content, encoding="utf-8")


def main():
    args = parse_args()
    data_dir = Path(args.data_dir)
    raw_dir = data_dir / "raw"
    judgement_dir = data_dir / "judgement"
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"plaud-sync-{datetime.now().strftime('%Y%m%d')}.log"

    log("===== Plaud Pipeline Started =====", log_file)
    preflight_check(log_file)

    recordings = list_recordings(log_file)
    log(f"Found {len(recordings)} recordings", log_file)

    if args.file_id:
        recordings = [r for r in recordings if r["id"] == args.file_id]
        if not recordings:
            log(f"ERROR: file_id {args.file_id} not found in recordings list", log_file)
            sys.exit(1)
        log(f"Target mode: forcing reprocessing of {args.file_id}", log_file)
    elif args.all_force:
        log(f"All-force mode: forcing reprocessing of all {len(recordings)} recordings", log_file)

    force = bool(args.file_id) or args.all_force

    pending = []
    for rec in recordings:
        md_path, criteria_path = target_paths(raw_dir, judgement_dir, rec["name"])
        if force or needs_processing(md_path):
            pending.append((rec, md_path, criteria_path))

    log(f"{len(pending)} recording(s) need processing", log_file)
    if not pending:
        log("===== Plaud Pipeline Completed (nothing to do) =====", log_file)
        return

    import torch
    import whisper
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"Loading whisper model '{args.model}' on device '{device}' (first run downloads the model)...", log_file)
    model = whisper.load_model(args.model, device=device)

    success_count = 0
    for rec, md_path, criteria_path in pending:
        log(f"Processing {rec['id']} ({rec['name']}, {rec['duration']})...", log_file)

        stem = safe_stem(rec['name'])
        audio_path = raw_dir / f"{stem}.mp3"

        if not audio_path.exists():
            url = get_audio_url(rec["id"], log_file)
            if not url:
                continue
            log(f"Downloading audio to {audio_path}...", log_file)
            if not download_audio(url, audio_path, log_file):
                continue

        log("Transcribing with Whisper...", log_file)
        text = transcribe(audio_path, model, args.language, log_file)
        if not text:
            log(f"No speech detected for {rec['id']} ({rec['name']}), marking as done to avoid retrying", log_file)
            write_markdown(md_path, rec, "(no speech detected)", args.model)
            write_criteria(criteria_path, rec, "(no speech detected)")
            continue

        write_markdown(md_path, rec, text, args.model)
        write_criteria(criteria_path, rec, text)
        log(f"Wrote {md_path.name} and {criteria_path.name}", log_file)
        success_count += 1

    log(f"===== Plaud Pipeline Completed: {success_count}/{len(pending)} succeeded =====", log_file)


if __name__ == "__main__":
    main()
