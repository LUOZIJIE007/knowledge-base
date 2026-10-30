import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rag_pro

tests = [
    '消防联动控制有哪些？',
    '综合布线怎么设计？',
    '断路器和熔断器有什么区别？',
    '接地电阻要求多少？',
    '照明照度标准是多少？',
    '线缆截面怎么选择？',
    'RCD漏电保护器怎么选？',
]
for q in tests:
    r = rag_pro.rag_answer(q)
    src = len(r['sources'])
    ans_len = len(r['answer'])
    has_table = '|' in r['answer']
    has_formula = '```' in r['answer']
    has_steps = 'Step' in r['answer'] or '流程' in r['answer'] or '步骤' in r['answer']
    print(f'{q:25s} | intent={r["intent"]:8s} | src={src} | len={ans_len:4d} | table={has_table} | formula={has_formula} | steps={has_steps}')
