"""P1 retrieval gate; paraphrases remain an explicitly separate P2 target."""

from graph_memory._base import GraphCliTestCase, require_graph
from graph_memory.eval.run_eval import evaluate, load_queries

require_graph()


class LexicalEvalTests(GraphCliTestCase):
    def test_lexical_recall_at_five_and_no_forbidden_results(self):
        """所有原词查询的 recall@5 为一且不得返回禁用线。"""
        cases = [case for case in load_queries() if case["kind"] == "lexical"]
        self.assertTrue(cases)
        report = evaluate(cases, k=5)
        self.assertEqual(report["groups"]["lexical"]["recall_at_k"], 1.0)
        self.assertEqual(report["groups"]["lexical"]["forbid_violations"], 0)
        for row in report["results"]:
            with self.subTest(query_id=row["id"]):
                self.assertTrue(row["hit"], row)
                self.assertEqual(row["forbidden"], [])
