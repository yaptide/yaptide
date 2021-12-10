from flask import make_response, Response


def yaptide_response(message: str, code: int, content: dict = {}) -> Response:
    """Function returning Response object"""
    return make_response({
        'message': message,
        'content': content,
    }, code)


def error_validation_response() -> Response:
    """Function returning Response object when ValidationError occures"""
    return yaptide_response(message='Internal server error', code=500)


def error_internal_response() -> Response:
    """Function returning Response object when Exception occures"""
    return yaptide_response(message='Wrong data provided', code=400)

