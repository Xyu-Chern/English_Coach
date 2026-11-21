"""Smoke-test local retrieval for the Chinese task set and render its actual passages."""

from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from translation_agent_demo.agents.contracts import SearchCorpusArgs
from translation_agent_demo.providers.embeddings import embedding_client
from translation_agent_demo.providers.local_embeddings import MODEL
from translation_agent_demo.storage.postgres import PostgresSettings, connect_database

from .freeze import verify_snapshot
from .live import configured_snapshot_dir
from .snapshot_search import SnapshotSearch
from .snapshot_store import SnapshotStore
from .tasks import Corpus, DATA, load_tasks
from translation_agent_demo.config import environment_values


def main():
    directory = configured_snapshot_dir()
    client = embedding_client()
    if client.model != MODEL:
        raise SystemExit("Select EMBEDDING_PROVIDER=local for the local retrieval demo.")
    corpus = Corpus(directory / "corpus.json.gz")
    tasks = load_tasks(DATA / "tasks.zh.jsonl")
    cards = []
    count = 0
    with connect_database(PostgresSettings.from_environment()) as conn:
        artifact = verify_snapshot(directory, live_conn=conn)
        store = SnapshotStore(conn, directory.name, schema=environment_values()["EVAL_SNAPSHOT_SCHEMA"],
                              expected_manifest_sha256=artifact["manifest_sha256"])
        store.verify(check_live_rights=True)
        search = SnapshotSearch(store, client)
        for task in tasks:
            # Test the English search leg in isolation, using the dataset's supplied gloss.
            result = search(SearchCorpusArgs(query=task.question_en, limit=3))
            hits = result.hits
            if result.status != "ok" or len(hits) != 3 or len({h.chunk_id for h in hits}) != 3:
                raise ValueError(f"Incomplete retrieval for {task.id}.")
            entries = []
            for hit in hits:
                raw = corpus.chunks[str(hit.chunk_id)]
                if hit.text != raw["text"] or str(hit.document_id) != str(raw["document_id"]):
                    raise ValueError(f"Passage mismatch for {hit.chunk_id}.")
                title = escape(hit.episode_title)
                if hit.transcript_url and urlsplit(hit.transcript_url).scheme in {"http", "https"}:
                    title = f'<a href="{escape(hit.transcript_url, quote=True)}">{title}</a>'
                entries.append(f'<li>{title} · {hit.similarity:.3f}<blockquote lang="en">{escape(hit.text)}</blockquote></li>')
            count += len(entries)
            cards.append(f'<details><summary>{escape(task.question)}</summary><p lang="en">{escape(task.question_en)}</p>'
                         f'<ol>{"".join(entries)}</ol></details>')
    output = Path(__file__).parent / "results" / directory.name / "report" / "retrieval.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>本地字幕检索</title>
<style>body{{max-width:850px;margin:auto;padding:24px;font:16px/1.65 system-ui,sans-serif;color:#17372e}}
details{{border-top:1px solid #bdd1c5;padding:12px 0}}summary{{cursor:pointer;font-weight:600}}
blockquote{{max-height:18em;overflow:auto;margin:8px 0 20px;white-space:pre-wrap}}a{{color:#146a56}}</style>
<h1>本地字幕检索</h1><p>{len(tasks)} 道中文题 · {len(corpus.documents)} 集 · {len(corpus.chunks)} 段字幕</p>
<p>展开题目，查看用题库自带的英文题意搜到的三段原文。数字是余弦相似度。
此页展示检索结果，智能体与基线的作答评分另行计算。</p>{"".join(cards)}</html>""", encoding="utf-8")
    print(f"{len(tasks)} queries, {count} passages verified. {output}")


if __name__ == "__main__":
    main()
