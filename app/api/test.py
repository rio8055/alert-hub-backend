from fastapi import APIRouter

router = APIRouter(prefix="/test", tags=["test"])


@router.get("")
def test_endpoint():
    return {"ok": True, "message": "Backend test endpoint is working"}
