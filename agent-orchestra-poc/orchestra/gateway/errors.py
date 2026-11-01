class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, detail: str = ""):
        super().__init__(detail)
        self.detail = detail


class Unauthorized(ApiError):
    status, code = 401, "unauthorized"


class Forbidden(ApiError):
    status, code = 403, "forbidden"


class NotFound(ApiError):
    status, code = 404, "not_found"


class Conflict(ApiError):
    status, code = 409, "conflict"


class BudgetExhausted(ApiError):
    status, code = 429, "budget_exhausted"


class NotConfigured(ApiError):
    status, code = 409, "llm_not_configured"
