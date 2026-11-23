"""Generate a private, self-contained replay from one Neon row and an optional caller reply."""
import argparse
import json
from pathlib import Path
from uuid import UUID

if __package__:
    from .replay import read_trace, render_trace
else:
    from replay import read_trace, render_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reply", type=Path, help="Optional {id, question, response} JSON captured by the caller.")
    args = parser.parse_args()
    data = read_trace(args.run_id)
    if data is None:
        parser.error("No stored trace matched this request.")
    if args.reply:
        supplied = json.loads(args.reply.read_text(encoding="utf-8-sig"))
        if supplied["id"] != data["id"]:
            parser.error("The reply belongs to a different request.")
        response = supplied["response"]
        expressions = []
        for item in response.get("expressions", []):
            source = item.get("citation")
            citation = {k: source.get(k) for k in ("quote", "episode_title", "episode_url")} if source else None
            expressions.append({"expression": item["expression"], "citation": citation})
        data.update(question=supplied["question"], response={"expressions": expressions, "note": response.get("note")})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_trace(data), encoding="utf8")


if __name__ == "__main__":
    main()
