"""Separate availability of sales, costs, and margins for each farm result."""
def describe(response):
    blocks=response.blocks
    fields={'revenue':'revenue','cost':'cost','margin':'profit'}
    coverage={}
    for name,field in fields.items():
        included=[b.id for b in blocks if all(getattr(r,field) is not None for r in b.yearly)]
        coverage[name]={'complete':len(included)==len(blocks),'included_block_ids':included,'total_blocks':len(blocks)}
    matched=[]
    for year in response.years:
        rows=[r for b in blocks for r in b.yearly if r.year==year and r.profit is not None]
        matched.append({'year':year, 'revenue':sum(r.revenue for r in rows) if rows else None,
                        'cost':sum(r.cost for r in rows) if rows else None,
                        'profit':sum(r.profit for r in rows) if rows else None})
    coverage['matched_totals']=matched
    return coverage
