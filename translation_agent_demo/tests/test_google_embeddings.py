import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.live import LiveEnvironment
from translation_agent_demo.providers.embedding_protocol import EmbeddingError
from translation_agent_demo.providers.embeddings import embedding_client
from translation_agent_demo.providers.google_embeddings import GoogleEmbeddingClient


class EmbeddingSelectionTests(unittest.TestCase):
    def test_switch_uses_separate_profiles_and_never_falls_back_on_missing_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            settings = Path(directory) / "settings"
            settings.write_text("OPENAI_API_KEY=test")
            self.assertEqual(embedding_client(settings).model, "text-embedding-3-small")
            settings.write_text("EMBEDDING_PROVIDER=google\nOPENAI_API_KEY=test")
            with self.assertRaises(EmbeddingError):
                embedding_client(settings)
            settings.write_text("EMBEDDING_PROVIDER=google\nGEMINI_API_KEY=test")
            self.assertEqual(embedding_client(settings).model, "gemini-embedding-2")

    @patch("translation_agent_demo.providers.google_embeddings.build_opener")
    def test_google_batch_preserves_order_and_rejects_invalid_dimensions(self, factory):
        client = GoogleEmbeddingClient("test")
        vectors = [{"values": [float(i)] * 1536} for i in (1, 2)]
        opener = factory.return_value
        opener.open.return_value = io.BytesIO(json.dumps({"embeddings": vectors}).encode())
        batch = client.embed_texts(["alpha", "beta"])
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)["requests"]
        self.assertEqual([r["content"]["parts"][0]["text"] for r in payload], ["alpha", "beta"])
        self.assertEqual([r["outputDimensionality"] for r in payload], [1536, 1536])
        self.assertEqual([v[0] for v in batch.vectors], [1, 2])
        self.assertIsNone(batch.input_tokens)
        opener.open.return_value = io.BytesIO(b'{"embeddings":[{"values":[1]}]}')
        with self.assertRaises(EmbeddingError):
            client.embed_texts(["alpha"])

    def test_google_client_refuses_an_openai_snapshot(self):
        env = object.__new__(LiveEnvironment)
        env.manifest = {"profile": {"model": "text-embedding-3-small", "dimensions": 1536}}
        with patch("evaluation.live.embedding_client", return_value=GoogleEmbeddingClient("test")):
            with self.assertRaisesRegex(ValueError, "does not match"):
                env.embeddings()
