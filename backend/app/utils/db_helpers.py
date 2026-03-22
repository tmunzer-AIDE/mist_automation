"""
Shared database aggregation helpers.
"""


async def facet_counts(model, field: str, values: list[str]) -> dict[str, int]:
    """Run a single $facet aggregation that counts total + each field value."""
    facets: dict = {"total": [{"$count": "n"}]}
    for v in values:
        facets[v] = [{"$match": {field: v}}, {"$count": "n"}]
    results = await model.aggregate([{"$facet": facets}]).to_list()
    row = results[0] if results else {}
    out: dict[str, int] = {}
    for key in ["total"] + values:
        bucket = row.get(key, [])
        out[key] = bucket[0]["n"] if bucket else 0
    return out
