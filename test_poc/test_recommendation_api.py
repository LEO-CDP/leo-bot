"""FastAPI adapter for the recommendation service."""

from contextlib import asynccontextmanager
import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if __package__:
    from .test_recommendation import (
        Product, Profile, RecommendationInputError, RecommendationService,
    )
else:
    from test_recommendation import (
        Product, Profile, RecommendationInputError, RecommendationService,
    )

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RecommendationService.connect() as service:
        app.state.recommendations = service
        yield


app = FastAPI(
    title="CDP Recommendation API (PGVector)", version="2.0", lifespan=lifespan
)


class ProfileRequest(BaseModel):
    profile_id: str = Field(min_length=1)
    page_view_keywords: list[str] = Field(min_length=1)
    purchase_keywords: list[str] = Field(min_length=1)
    interest_keywords: list[str] = Field(min_length=1)
    additional_info: dict[str, Any] = Field(default_factory=dict)
    max_recommendation_size: int = Field(8, gt=0)
    except_product_ids: list[str] = Field(default_factory=list)

    def to_profile(self) -> Profile:
        return Profile(
            self.profile_id, self.page_view_keywords, self.purchase_keywords,
            self.interest_keywords, self.additional_info,
        )


class ProductRequest(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str
    product_category: str
    product_keywords: list[str]
    additional_info: dict[str, Any] = Field(default_factory=dict)

    def to_product(self) -> Product:
        return Product(
            self.product_id, self.product_name, self.product_category,
            self.product_keywords, self.additional_info,
        )


def get_service(request: Request) -> RecommendationService:
    return request.app.state.recommendations


@app.exception_handler(RecommendationInputError)
async def invalid_input(request: Request, exc: RecommendationInputError):
    logger.warning("Invalid recommendation request at %s: %s", request.url.path, exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/")
async def index():
    return {"message": "CDP Recommendation API using PostgreSQL + pgvector"}


@app.post("/add-profile/")
async def api_add_profile(
    profile: ProfileRequest, service: RecommendationService = Depends(get_service)
):
    await service.upsert_profile(profile.to_profile())
    return {"status": "Profile added successfully"}


@app.post("/add-profiles/")
async def api_add_profiles(
    profiles: list[ProfileRequest], service: RecommendationService = Depends(get_service)
):
    inserted = await service.upsert_profiles([profile.to_profile() for profile in profiles])
    return {"status": f"{inserted} profiles added/updated successfully"}


@app.post("/add-product/")
async def api_add_product(
    product: ProductRequest, service: RecommendationService = Depends(get_service)
):
    await service.upsert_product(product.to_product())
    return {"status": "Product added successfully"}


@app.post("/add-products/")
async def api_add_products(
    products: list[ProductRequest], service: RecommendationService = Depends(get_service)
):
    inserted = await service.upsert_products([product.to_product() for product in products])
    return {"status": f"{inserted} products added/updated successfully"}


@app.post("/recommend/")
async def api_recommend(
    profile: ProfileRequest, service: RecommendationService = Depends(get_service)
):
    await service.upsert_profile(profile.to_profile())
    result = await service.recommend(
        profile.profile_id, profile.max_recommendation_size, profile.except_product_ids
    )
    if not result["recommended_products"]:
        raise HTTPException(status_code=404, detail="No recommendations found")
    return result


@app.get("/recommend/{profile_id}")
async def api_get_recommend(
    profile_id: str,
    top_n: int = Query(8, gt=0),
    except_product_ids: str = "",
    service: RecommendationService = Depends(get_service),
):
    ids = [identifier for identifier in except_product_ids.split(",") if identifier]
    result = await service.recommend(profile_id, top_n, ids)
    if not result["recommended_products"]:
        raise HTTPException(status_code=404, detail="No recommendations found")
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "test_poc.test_recommendation_api:app", host="0.0.0.0", port=8000, reload=True
    )
