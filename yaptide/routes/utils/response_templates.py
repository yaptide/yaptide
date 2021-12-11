from typing import Union
from flask import make_response, Response


def yaptide_response(message: str, code: int, content: Union[dict, str] = "") -> Response:
    """Function returning Response object"""
    if type(content) is str:
        return make_response({
            'message': message,
        }, code)
    return make_response({
        'message': message,
        'content': content,
    }, code)


def error_validation_response() -> Response:
    """Function returning Response object when ValidationError occures"""
    return yaptide_response(message='Wrong data provided', code=400)


def error_internal_response() -> Response:
    """Function returning Response object when Exception occures"""
    return yaptide_response(message='Internal server error', code=500)
