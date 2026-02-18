from __future__ import annotations

import argparse
import json
import sys
import os
import math
import wave
import struct
from typing import Any

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "generate_audio",
    "description": "Generate a simple audio file (WAV format) with sine wave tone.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Output filename (e.g., output.wav)"},
            "frequency": {"type": "number", "description": "Frequency in Hz (default: 440)"},
            "duration": {"type": "number", "description": "Duration in seconds (default: 2)"},
        },
        "required": ["filename"],
    },
}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    filename = input_data.get("filename", "output.wav")
    frequency = float(input_data.get("frequency", 440))
    duration = float(input_data.get("duration", 2))
    
    workdir = context.get("workdir", ".")
    filepath = os.path.join(workdir, filename)
    
    # Audio parameters
    sample_rate = 44100
    num_samples = int(sample_rate * duration)
    amplitude = 32767 / 2  # 16-bit audio
    
    # Generate sine wave
    samples = []
    for i in range(num_samples):
        value = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(value)
    
    # Write WAV file
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 2 bytes (16-bit)
        wav_file.setframerate(sample_rate)
        
        for sample in samples:
            wav_file.writeframes(struct.pack('h', sample))
    
    return {
        "success": True,
        "filepath": filepath,
        "frequency": frequency,
        "duration": duration,
        "message": f"Audio file generated: {filepath}"
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="generate_audio cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()

    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0

        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
