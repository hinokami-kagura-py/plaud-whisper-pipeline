# plaud-whisper-pipeline

Download audio from your [Plaud](https://plaud.ai/) recordings and transcribe it locally with
[OpenAI Whisper](https://github.com/openai/whisper) — no cloud transcription service required.

For each recording, the script produces:
- a markdown transcript (`raw/<date>_<name>.md`) alongside the downloaded audio (`.mp3`)
- a lightweight review-checklist file (`judgement/<date>_<name>_criteria.md`)

Already-transcribed recordings are skipped on subsequent runs, so it's safe to run on a schedule.

## Prerequisites

- Python 3.10+
- [Plaud CLI](https://www.npmjs.com/package/@plaud-ai/cli): `npm install -g @plaud-ai/cli`
- `ffmpeg` on PATH (required by Whisper to decode audio)
- A Plaud account with recordings

## Setup

```bash
npm install -g @plaud-ai/cli
plaud login

pip install -r requirements.txt
```

### Optional: GPU acceleration (NVIDIA)

The default `pip install torch` gives you a CPU-only build. If you have an NVIDIA GPU, install a
CUDA-enabled build instead for a large speedup:

```bash
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

Check your driver's supported CUDA version with `nvidia-smi` first; any `cuXXX` build equal to or
older than what your driver reports will work. The script auto-detects CUDA and falls back to CPU
if it isn't available.

## Usage

```bash
# process only new/unprocessed recordings
python plaud_pipeline.py

# reprocess everything (existing audio files are reused, not re-downloaded)
python plaud_pipeline.py --all-force

# force-reprocess a single recording
python plaud_pipeline.py --file-id <recording_id>

# pick a different Whisper model size (tiny/base/small/medium/large)
python plaud_pipeline.py --model medium

# change where output is written (default: ./plaud_data)
python plaud_pipeline.py --data-dir D:\plaud
```

Output layout under `--data-dir` (default `./plaud_data`):

```
plaud_data/
  raw/         # downloaded audio (.mp3) + transcripts (.md)
  judgement/   # review-checklist files (.md)
  logs/        # one log file per day
```

## Running on a schedule (Windows Task Scheduler)

```powershell
$pythonExe = (Get-Command python).Source
$scriptPath = "C:\path\to\plaud_pipeline.py"

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName "PlaudWhisperPipeline" -Action $action -Trigger $trigger -Settings $settings
```

By default this only runs when the machine is logged in — see `Register-ScheduledTask` docs if you
need it to run while logged out.

## Notes

- The Plaud CLI has no bulk audio-export endpoint of its own; this script calls `plaud audio <id>`
  per recording to get a short-lived (24h) presigned download URL, then downloads it directly.
- Whisper's `small` model is a good default for meeting/lecture audio in Japanese; `medium` is more
  accurate but noticeably slower without a GPU.
