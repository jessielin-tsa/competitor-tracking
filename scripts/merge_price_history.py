#!/usr/bin/env python3
"""在自動合併發生衝突時，針對「只會往後追加」的資料檔（price-history.json、
tracking-history.json）以「聯集」方式安全解衝突：兩邊的資料點全部保留，
同一鍵（日期）衝突時以目前分支（ours）為準。無法安全解時回傳非 0，
讓 workflow 退回「明確失敗」交給人處理，絕不亂猜。"""
import json, subprocess, sys


def stage(num, path):
    try:
        return json.loads(subprocess.check_output(['git', 'show', f':{num}:{path}']).decode())
    except subprocess.CalledProcessError:
        return None


def union_price(ours, theirs):
    out = {k: v for k, v in ours.items() if k != 'products'}
    prods = {p['id']: p for p in ours['products']}
    order = [p['id'] for p in ours['products']]
    for p in theirs['products']:
        if p['id'] not in prods:
            prods[p['id']] = p
            order.append(p['id'])
        else:
            o = prods[p['id']]
            od = {s['date']: s for s in o['series']}
            td = {s['date']: s for s in p['series']}
            o['series'] = [(od[d] if d in od else td[d]) for d in sorted(set(od) | set(td))]
    out['products'] = [prods[i] for i in order]
    return out


def union_snapshots(ours, theirs):
    od = {s['date']: s for s in ours.get('snapshots', [])}
    td = {s['date']: s for s in theirs.get('snapshots', [])}
    return {'snapshots': [(od[d] if d in od else td[d]) for d in sorted(set(od) | set(td))]}


HANDLERS = {
    'price-history.json': union_price,
    'tracking-history.json': union_snapshots,
}


def main(files):
    if not files:
        return 0
    for path in files:
        if path not in HANDLERS:
            print(f'無對應處理器，拒絕自動解：{path}', file=sys.stderr)
            return 2
        ours, theirs = stage(2, path), stage(3, path)
        if ours is None or theirs is None:
            print(f'取不到衝突版本，拒絕自動解：{path}', file=sys.stderr)
            return 2
        merged = HANDLERS[path](ours, theirs)
        with open(path, 'w') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        json.load(open(path))  # 驗證仍為合法 JSON
        subprocess.check_call(['git', 'add', path])
        print(f'已以聯集解衝突：{path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
