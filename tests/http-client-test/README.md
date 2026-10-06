# All HTTP Client test for API of test_recommendation_api.py

## Need:
    https://marketplace.visualstudio.com/items?itemName=humao.rest-client

Start the recommendation API from the repository root:

```bash
env/bin/python -m uvicorn test_poc.test_recommendation_api:app --port 8000
```

The demo is also runnable with:

```bash
env/bin/python test_poc/test_recommendation.py
```

Both entry points use `RecommendationService`, with `RecommendationConfig`,
`VectorBuilder`, and `RecommendationRepository` as separate, injectable components.
Set `PGSQL_DB_URL` (or `PGSQL_DB_URL`) and the hosted embedding settings in `.env`.
Profile and product embeddings use the same dimension (768 by default); HNSW
rejects dimensions above 2000.

Existing incompatible vector columns cause an explicit startup error rather
than a table reset. Migrate/re-embed old data deliberately before starting the
service. Changing embedding providers/models also requires re-embedding data,
even when the vector dimensions stay the same.