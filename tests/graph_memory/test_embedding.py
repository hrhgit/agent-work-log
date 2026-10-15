"""Embedding contract tests; deterministic vectors, no model dependency."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from graph_memory._base import GraphCliTestCase, LINES, SHARED, require_graph

require_graph()


def unit(axis):
    return [float(i == axis) for i in range(256)]


class EmbeddingTests(GraphCliTestCase):
    def fake(self, mapping):
        path = Path(self.temp.name) / 'vectors.json'
        path.write_text(json.dumps(mapping, ensure_ascii=False), encoding='utf-8')
        self.env['AGENT_WORK_LOG_EMBED'] = 'fake:' + str(path)
        self.calls = Path(str(path) + '.calls')
        return path

    def call_batches(self):
        return [json.loads(line) for line in self.calls.read_text(encoding='utf-8').splitlines()]

    def test_semantic_only_recall(self):
        """词项不命中但向量相近时，语义检索返回对应线。"""
        query = '逐个计量部件的运行时长'
        self.fake({query: unit(0), self.line_meta('A1')['method']: unit(0)})
        self.assertIn(LINES['A1'], self.ids(self.recall(query, '--by', 'method')))

    def test_unrelated_query_returns_nothing(self):
        """词项无交集且全部余弦低于阈值时，返回无相关历史。"""
        query = '火星基地氧气补给'
        self.fake({query: unit(0), **{self.line_meta(alias)['situation']: unit(1) for alias in LINES}})
        view = self.recall(query, '--by', 'situation')
        self.assertEqual(view['lines'], [])
        self.assertEqual(view['message'], '无相关历史')

    def test_semantic_supersession_redirect(self):
        """只在语义上命中被取代线时，沿关系返回最新线并保留 via。"""
        query = '丢掉过期的中间产物'
        self.fake({query: unit(0), self.line_meta('A3')['situation']: unit(0)})
        view = self.recall(query, '--by', 'situation')
        self.assertEqual(self.ids(view), [LINES['A4']])
        self.assertEqual(view['lines'][0]['via'], LINES['A3'])

    def test_semantic_archived_excluded(self):
        """只在语义上命中归档线时，返回空结果且不泄露归档哨兵。"""
        query = '矿石晶体折射校正'
        self.fake({query: unit(0), **{self.line_meta(alias)['situation']: unit(0 if alias == 'Z1' else 1) for alias in LINES}})
        view = self.recall(query, '--by', 'situation')
        self.assertEqual(view['lines'], [])
        self.assertEqual(view['message'], '无相关历史')
        self.assert_no_archived(view)
        self.assertNotIn(self.line_meta('Z1')['situation'], json.dumps(self.call_batches(), ensure_ascii=False))

    def test_incremental_cache(self):
        """重复查询不调用后端，修改一条线后只计算该线变化的视图文本。"""
        query = '金星岩层结构探测'
        self.fake({query: unit(0)})
        self.recall(query)
        initial = self.call_batches()
        self.recall(query)
        self.assertEqual(self.call_batches(), initial)  # query is cached too
        changed = '月球矿物表面光谱测量'
        self.change_line('A1', situation=changed)
        self.recall(query)
        added = self.call_batches()[len(initial):]
        # situation and content both change; method and every other line stay cached.
        self.assertEqual(len(added), 1)
        self.assertEqual(len(added[0]), 2)
        self.assertIn(changed, added[0])
        self.assertTrue(all(changed in text for text in added[0]))

    def test_reindex_preserves_cache(self):
        """全量重建索引保留向量缓存，未变化文本不重新计算。"""
        self.fake({'海底热泉压力测量': unit(0)})
        self.recall('海底热泉压力测量')
        initial = self.call_batches()
        self.assert_ok('reindex')
        self.recall('海底热泉压力测量')
        self.assertEqual(self.call_batches(), initial)

    def test_semantic_duplicate_blocks_open(self):
        """新线措辞完全不同但向量几乎相同时，退出三并返回已有候选。"""
        situation, method = '逐项计量组件运行时长', '绘制热点分布图'
        old = self.line_meta('A1')
        self.fake({situation + ' ' + method: unit(0), old['situation'] + ' ' + old['method']: unit(0)})
        result = self.assert_error(3, 'line', 'open', '--title', '部件计时', '--situation', situation,
                                   '--method', method, '--why', '找出最慢步骤', '--from', SHARED, '--json')
        self.assertIn(LINES['A1'], [item['id'] for item in json.loads(result.stdout)['candidates']])

    def test_unavailable_local_falls_back(self):
        """本地解释器不存在时仍正常命中词项，退出零且标准错误有回退提示。"""
        self.env['AGENT_WORK_LOG_EMBED'] = 'local'
        self.env['AGENT_WORK_LOG_EMBED_PYTHON'] = str(Path(self.temp.name) / 'missing-python')
        result = self.assert_ok('recall', 'profile', '--by', 'method', '--json')
        self.assertIn(LINES['A1'], self.ids(json.loads(result.stdout)))
        self.assertIn('embedding 不可用，已回退词项检索：', result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_none_preserves_p1(self):
        """关闭向量后词项检索与 P1 的结果和排序保持一致。"""
        self.env['AGENT_WORK_LOG_EMBED'] = 'none'
        baseline = self.recall('二分排查', '--by', 'method')
        self.assertEqual(set(self.ids(baseline)), {LINES['B1'], LINES['C1']})
        self.fake({'profile': unit(0)})
        self.recall('profile')
        self.env['AGENT_WORK_LOG_EMBED'] = 'none'
        self.assertEqual(self.recall('二分排查', '--by', 'method'), baseline)

    def test_l0_never_contains_node_bodies(self):
        """使用向量后 L0 仍只含线摘要，输出和计算请求均不含点正文哨兵。"""
        self.fake({'profile': unit(0)})
        result = self.assert_ok('recall', 'profile', '--json')
        self.assertIn(LINES['A1'], self.ids(json.loads(result.stdout)))
        self.assertNotIn('BODY_SENTINEL_', result.stdout)
        self.assertNotIn('BODY_SENTINEL_', self.calls.read_text(encoding='utf-8'))

    def test_model_identity_isolated_in_cache(self):
        """模型版本变化后重算并更新索引标识，不复用旧模型的向量。"""
        path = self.fake({'水星表层温度': unit(0)})
        self.recall('水星表层温度')
        before = len(self.call_batches())
        path.write_text(json.dumps({'水星表层温度': unit(1)}), encoding='utf-8')
        self.recall('水星表层温度')
        self.assertGreater(len(self.call_batches()), before)
        with closing(sqlite3.connect(self.log_dir / '.index' / 'embeddings.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT model_id) FROM vectors').fetchone()[0], 2)
        with closing(sqlite3.connect(self.log_dir / '.index' / 'graph.sqlite')) as db:
            model = db.execute("SELECT value FROM meta WHERE key='embedding_model_id'").fetchone()[0]
            self.assertTrue(model.startswith('fake@'))

    def test_field_selection_keeps_semantics_separate(self):
        """按问题或走法查询时，只比较指定字段的向量。"""
        query = '木卫二冰壳厚度勘测'
        self.fake({query: unit(0),
                   **{self.line_meta(alias)['situation']: unit(1) for alias in LINES},
                   self.line_meta('A1')['method']: unit(0)})
        self.assertEqual(self.recall(query, '--by', 'situation')['lines'], [])
        self.assertIn(LINES['A1'], self.ids(self.recall(query, '--by', 'method')))

    def test_semantics_affects_ranking_with_lexical_hits(self):
        """两条线均有词项命中时，语义得分仍按规定权重参与排序。"""
        query = '二分排查'
        self.fake({query: unit(0), self.line_meta('B1')['method']: unit(0),
                   self.line_meta('C1')['method']: unit(1)})
        # Both have lex=1. B1's cosine=1 wins over C1's newer timestamp.
        self.assertEqual(self.ids(self.recall(query, '--by', 'method'))[:2],
                         [LINES['B1'], LINES['C1']])

    def test_auto_missing_interpreter_is_silent(self):
        """自动模式的本地后端不可用时静默回退，保留词项结果。"""
        self.env['AGENT_WORK_LOG_EMBED'] = 'auto'
        self.env['AGENT_WORK_LOG_EMBED_PYTHON'] = str(Path(self.temp.name) / 'missing-python')
        result = self.assert_ok('recall', 'profile', '--by', 'method', '--json')
        self.assertIn(LINES['A1'], self.ids(json.loads(result.stdout)))
        self.assertEqual(result.stderr, '')
