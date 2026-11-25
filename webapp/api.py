from flask import jsonify, request


class ApiError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def api_ok(data=None):
    return jsonify(code=0, msg="ok", data={} if data is None else data)


def api_error(error: ApiError):
    return jsonify(code=error.status, msg=str(error), data={}), error.status


def json_object():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("请求必须是 JSON 对象")
    return body
