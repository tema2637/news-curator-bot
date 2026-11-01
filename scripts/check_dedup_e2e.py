import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
from curator.db import (init_db, save_article, get_cluster_heads, update_cluster_sources,
                        mark_cluster_delivered, get_unreported_high_signal)
from curator.dedup import find_duplicate, build_source_entry, merge_sources, format_discussion_line

init_db()
conn = sqlite3.connect('news_curator.db')
conn.execute("UPDATE articles SET cluster_id = id WHERE cluster_id IS NULL")
conn.execute("DELETE FROM articles WHERE id LIKE 'test_%'")
conn.commit()

a = {'id': 'test_gh_pr30912',
     'title': 'llama.cpp b11792: llama : place d2t so it can stay on the GPU (#30912)',
     'url': 'https://github.com/ggml-org/llama.cpp/releases/tag/b11792',
     'source': 'github', 'signal': 0.95, 'fact': 1.0, 'hype': 0.05,
     'score': 0.95, 'category': 'tools', 'summary': 'POST A'}
a['cluster_id'] = a['id']
a['sources'] = merge_sources('[]', build_source_entry(a['title'], a['url'], 'github'))
save_article(a)

copies = [
    ('llama.cpp b11792 places d2t tensor on GPU (#30912)',
     'https://reddit.com/r/LocalLLaMA/dup1', 'reddit'),
    ('llama.cpp: keep d2t on GPU so speculative decoding is faster (#30912)',
     'https://news.ycombinator.com/item?id=999', 'hn'),
]

for t, u, s in copies:
    dup = find_duplicate(get_cluster_heads(hours=72), t, u)
    if dup:
        cid = dup.get('cluster_id') or dup['id']
        update_cluster_sources(cid, merge_sources(dup.get('sources') or '[]',
                                                  build_source_entry(t, u, s)))
        print(f'[{s}] merged into {cid}')
    else:
        print(f'[{s}] new page')

head = [h for h in get_cluster_heads(hours=72) if h['id'] == 'test_gh_pr30912'][0]
print()
print('Discussion:', format_discussion_line(head['sources']))
print('Rows in cluster:', conn.execute(
    "SELECT count(*) FROM articles WHERE id=? OR cluster_id=?", (a['id'], a['id'])).fetchone()[0])

mark_cluster_delivered(a['id'])
print('Delivered rows:', conn.execute(
    "SELECT count(*) FROM articles WHERE (id=? OR cluster_id=?) AND delivered_at IS NOT NULL",
    (a['id'], a['id'])).fetchone()[0])

conn.execute("DELETE FROM articles WHERE id LIKE 'test_%'")
conn.commit()
print('cleanup ok')
