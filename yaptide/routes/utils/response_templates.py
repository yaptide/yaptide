from typing import Union
from flask import make_response, Response


def yaptide_response(message: str, code: int, content: dict = None) -> Response:
    """Function returning Response object"""
    response_dict = {'message': message}
    if content:
        response_dict.update(content)
    return make_response(response_dict, code)


def error_validation_response(content: dict = None) -> Response:
    """Function returning Response object when ValidationError occures"""
    return yaptide_response(message='Wrong data provided', code=400, content=content)


def error_internal_response(content: dict = None) -> Response:
    """Function returning Response object when Exception occures"""
    return yaptide_response(message='Internal server error', code=500, content=content)
